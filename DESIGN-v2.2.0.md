# ZhyCMS v2.2.0 技术设计文档

> 状态：**评审中**（未实施）
> 版本目标：v2.2.0（核心库零表变更；插件启用时自动建各自表）
> 范围：**插件机制（核心底座）** + 轮播图插件 + 产品增强插件 + REST 内容 API（只读，核心 + 插件扩展点）
> 延后：多语言国际化（→ v3.0）
> 架构决策（评审定稿方向）：插件机制先行，轮播图、产品模型**以插件形式实现**，后台可启用/禁用，即时生效

---

## 一、背景与目标

| 目标 | 说明 |
| --- | --- |
| 插件机制 | 核心底座：定义插件目录、清单、加载与启停机制，不修改核心源码即可扩展功能（后台页面、前台路由、模板函数、数据表、API 端点） |
| 轮播图插件 | 作为**首个示范插件**验证插件机制：后台分组管理首页幻灯片，模板一行调用，替代碎片拼轮播 |
| 产品增强插件 | 多图相册 + 规格参数表，区别普通文章，适合制造业企业 |
| REST 内容 API | 只读输出栏目/文章/产品/轮播数据，核心提供基础端点，插件贡献各自端点（Headless 能力第一步） |

设计原则：

1. **与现有模式一致**——RBAC 权限、审计日志、上传中心、伪静态、页面缓存、主题机制全部复用；
2. **启停即时生效、无需重启**（沿用「后台前缀即时生效」同款工程文化，实现方式见 §2.3）；
3. **核心零迁移**——v2.1.1 → v2.2.0 覆盖代码即可，插件表在 `db.create_all()` 时自动创建；
4. **禁用即隐身**——禁用后后台菜单隐藏、前台路由 404、模板函数返回空值、API 404，模板无需改动不报错。

---

## 二、插件机制（核心底座）

### 2.1 目录结构与清单

```
plugins/
├── banner/                      # 轮播图插件
│   ├── manifest.json            # 元数据（仅供插件管理页展示，不含逻辑）
│   ├── __init__.py              # Plugin 类定义（插件入口）
│   ├── models.py
│   ├── admin.py                 # 后台蓝图
│   ├── frontend.py              # 前台贡献（详情路由/模板函数实现）
│   ├── templates/               # 插件模板（admin 与 frontend 分子目录）
│   └── static/                  # 插件静态资源
└── product/                     # 产品插件（结构同上）
```

`manifest.json`（纯元数据，未启用/未导入时也能读取展示）：

```json
{
  "slug": "banner",
  "name": "轮播图",
  "version": "1.0.0",
  "description": "首页幻灯片/广告位分组管理，模板 banner_items() 一行调用",
  "author": "ZhyCMS 官方",
  "min_core_version": "2.2.0"
}
```

### 2.2 插件类契约（`app/plugin_api.py` 提供基类）

```python
class PluginBase:
    # —— 元数据（与 manifest.json 一致，以类属性为准）——
    slug = ''; name = ''; version = ''; description = ''

    # —— 声明式注册信息 ——
    permissions: list = []       # [(code, label, desc)] 启用时种子写入 permissions 表
    preset_role_grants: dict = {}  # {'content_editor': ['banner:manage']} 启用时给预设角色补授权（幂等）
    audit_modules: list = []     # [('banner', '轮播图')] 审计页筛选下拉聚合

    # —— 代码钩子（核心在启动时统一调用）——
    def get_admin_blueprint(self): ...      # 返回 admin 蓝图（url_prefix='/<admin_prefix>/banner'）或 None
    def get_frontend_blueprint(self): ...   # 返回前台蓝图或 None
    def get_api_routes(self, api_bp): ...   # 直接向核心 api_bp 注册端点，或 no-op
    def jinja_globals(self): ...            # {'banner_items': fn} 核心**自动包裹启停守卫**
    def admin_menu(self): ...               # [{'group','label','endpoint','icon','permission'}]
    def sitemap_urls(self): ...             # yield {'loc','changefreq','priority','lastmod'}
    def demo_data(self, industry): ...      # 演示数据生成钩子
```

- 插件内 `from app.plugin_api import PluginBase`，可直接 `import` 使用核心的 `db`、`Setting`、上传中心、权限装饰器等。
- **模型导入即注册**：`models.py` 在插件包导入时把模型挂入 SQLAlchemy metadata，`db.create_all()` 自然覆盖。

### 2.3 加载与启停机制（关键设计）

**启动时：全量导入、全量注册**

1. 扫描 `plugins/*/manifest.json` 得到插件清单（不导入代码即可展示于管理页）；
2. 对**所有**发现的插件执行导入（`try/except` 隔离：单个插件导入失败仅记录错误并在管理页标红，不拖垮启动），注册其蓝图、模板全局、菜单、审计模块、API 端点、sitemap 钩子；
3. `db.create_all()` 一并创建已发现插件的表（未启用也只有空表，无害）。

**运行时：Setting 门控，即时生效**

- 启用清单存 `site_settings` 键 `enabled_plugins`（逗号分隔 slug，如 `'banner,product'`）。
- 核心提供 `plugin_enabled(slug)`（带请求级缓存读取 Setting）。所有插件相关入口经守卫：
  - 后台视图装饰器：未启用 → 404（菜单本就隐藏，直敲 URL 也进不来）；
  - 前台路由守卫：未启用 → 404；
  - 模板全局守卫：**核心在注册 `jinja_globals` 时统一包裹**，未启用返回安全空值（`[]`/`None`），主题模板零改动、不崩溃；
  - API 端点守卫：未启用 → 404（与 `api_enable=off` 行为一致，不暴露存在性）。
- 因此**启用/禁用只改一个 Setting 值，全站即时生效，无需重启、无 url_map 手术**，且天然兼容多 worker 部署（守卫每请求读库，各 worker 一致）。这是相对「动态增删 URL rule」方案的取舍：牺牲一点路由表整洁度，换取实现简单与多进程一致性。

**启用动作（管理页点击「启用」）**：

1. 幂等种子权限点（`permissions` 表按 code 去重插入）；
2. 幂等给 `preset_role_grants` 声明的预设角色补授权（不影响已自定义的角色绑定）；
3. `db.create_all()` 兜底建表；
4. 写入 `enabled_plugins`；审计留痕。

**禁用动作**：仅从 `enabled_plugins` 移除 + 审计留痕。**不删表、不清数据、不回收权限绑定**（重新启用原样恢复）；「卸载并清除数据」留待后续版本。

### 2.4 插件管理后台页

- 路由 `/<admin_prefix>/plugins`（GET 列表 + POST 启停），新增核心文件 `app/admin/plugins.py`。
- 列表项：名称、slug、版本、描述、作者、状态（已启用/未启用/导入失败标红）、启停按钮。
- 权限：`system:settings`；审计：核心新增模块常量 `MODULE_PLUGIN = 'plugin'`（标签「插件管理」）。

### 2.5 菜单 / 模板 / 静态资源

- **后台菜单**：核心菜单构建器聚合各启用插件的 `admin_menu()`，沿用现有「无权限即隐藏」逻辑。
- **前台模板解析链**（插件前端模板）：`themes/<当前主题>/<name>.html` → `plugins/<slug>/templates/<name>.html` → `themes/default/<name>.html`。**主题优先、插件兜底**：企业可按主题覆盖插件模板，插件保证开箱可用。
- **静态资源**：插件蓝图自带 `static_folder`，经 `url_for('<slug>_plugin.static', filename=...)` 引用，路径形如 `/plugins-static/<slug>/...`。

---

## 三、轮播图插件（plugins/banner，首个示范插件）

### 3.1 数据模型（`plugins/banner/models.py`）

```python
class BannerGroup(db.Model):
    """轮播分组：一个分组对应模板上一个轮播位。"""
    __tablename__ = 'banner_groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)          # 如「首页大图」
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)  # 如 home-hero
    remark = db.Column(db.String(255))
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
    items = db.relationship('Banner', backref='group', lazy='dynamic',
                            cascade='all, delete-orphan',
                            order_by='Banner.sort_order.asc(), Banner.id.asc()')


class Banner(db.Model):
    __tablename__ = 'banners'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('banner_groups.id'), nullable=False, index=True)
    title = db.Column(db.String(200))                          # alt 文案
    image_id = db.Column(db.Integer, db.ForeignKey('uploaded_files.id'), nullable=False)
    link_url = db.Column(db.String(500))                       # 留空纯展示
    link_target = db.Column(db.String(16), default='_self')
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    start_at = db.Column(db.DateTime)                          # 可选定时上线
    end_at = db.Column(db.DateTime)                            # 可选定时下线
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
    image = db.relationship('UploadedFile')
```

- 图片复用上传中心，保存/删除维护 `ref_count`（+1/-1）；分组删除级联清空并释放引用。

### 3.2 插件声明

```python
class BannerPlugin(PluginBase):
    slug = 'banner'; name = '轮播图'; version = '1.0.0'
    permissions = [('banner:manage', '轮播图管理', '轮播分组与图片管理')]
    preset_role_grants = {'content_auditor': ['banner:manage'],
                          'content_editor': ['banner:manage']}
    audit_modules = [('banner', '轮播图')]
    admin_menu = [{'group': '内容', 'label': '轮播图', 'endpoint': 'banner_admin.group_index',
                   'icon': 'fa-images', 'permission': 'banner:manage'}]
    jinja_globals -> {'banner_items': banner_items}
    get_api_routes -> GET /api/v1/banners/<slug>
```

### 3.3 后台页面（蓝图 `banner_admin`）

| 路由 | 说明 |
| --- | --- |
| `/banners` | 分组列表（含各组图片数） |
| `/banners/create`、`/banners/<gid>/edit`、`/banners/<gid>/delete` | 分组 CRUD |
| `/banners/<gid>/items`、`.../items/create`、`.../items/<bid>/edit`、`.../items/<bid>/delete`、`.../items/batch` | 图片管理：上传/选图、排序、启停、定时上下线、批量操作 |

页面模板放 `plugins/banner/templates/admin/`，交互复用碎片/友链页面模式（列表 + 表单 + flash + 批量）。

### 3.4 前台调用

```python
# plugins/banner/frontend.py —— 经核心包裹启停守卫后注册为全局函数
def banner_items(slug, limit=None):
    """分组内当前生效轮播图（is_enabled 且时间窗内）；
    Flask-Caching 缓存（TTL 复用 cache_ttl_column），后台保存时清理；
    返回 [{title, image_url, link_url, link_target}]；未启用/无分组返回 []。"""
```

```jinja
{% set banners = banner_items('home-hero') %}
{% if banners %}
<div class="hero-carousel">
  {% for b in banners %}
  <a href="{{ b.link_url or 'javascript:;' }}" target="{{ b.link_target }}">
    <img src="{{ b.image_url }}" alt="{{ b.title }}">
  </a>
  {% endfor %}
</div>
{% endif %}
```

- 轮播交互用纯 CSS + 少量原生 JS，不引第三方库；default 主题首页接入，blue 同步，manufacturing/service 回退 default（§2.5 解析链）。

---

## 四、产品增强插件（plugins/product）

### 4.1 设计取舍

- 独立 `Product` 模型（规格参数/多图相册塞文章自定义字段体验差；产品无工作流/版本需求）。
- 产品**归属列表栏目**：复用栏目树做产品分类、复用栏目级内容授权（`UserColumnPermission`）与伪静态/SEO/缓存体系；无工作流，仅 `is_enabled`。

### 4.2 数据模型（`plugins/product/models.py`）

```python
class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    column_id = db.Column(db.Integer, db.ForeignKey('columns.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    summary = db.Column(db.Text)                     # 列表页简介
    content = db.Column(db.Text)                     # 富文本详情（CKEditor）
    cover_file_id = db.Column(db.Integer, db.ForeignKey('uploaded_files.id'))  # 空则取相册第一张
    gallery = db.Column(db.Text)                     # JSON：相册文件 ID 有序列表 [12,13,14]
    specs = db.Column(db.Text)                       # JSON：规格参数（结构见下）
    seo_title = db.Column(db.String(255))
    seo_keywords = db.Column(db.String(255))
    seo_description = db.Column(db.String(500))
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
```

`specs` JSON（分组 + 键值，渲染规格表）：

```json
[
  {"group": "基本参数", "items": [{"name": "型号", "value": "ZX-100"}, {"name": "材质", "value": "304 不锈钢"}]},
  {"group": "技术参数", "items": [{"name": "额定功率", "value": "5.5 kW"}]}
]
```

`gallery` 引用计数规则：保存时 diff 新旧列表增减 `ref_count`；封面切换同理；软删除不释放，物理删除整体释放；封面为空取 `gallery[0]` 兜底。

### 4.3 插件声明

```python
class ProductPlugin(PluginBase):
    slug = 'product'; name = '产品展示'; version = '1.0.0'
    permissions = [('product:manage', '产品管理', '产品增删改与相册/规格维护')]
    preset_role_grants = {'content_auditor': ['product:manage'],
                          'content_editor': ['product:manage']}
    audit_modules = [('product', '产品管理')]
    admin_menu = [{'group': '内容', 'label': '产品管理', 'endpoint': 'product_admin.index',
                   'icon': 'fa-box-open', 'permission': 'product:manage'}]
    get_frontend_blueprint -> /column/<slug>/product/<int:pid>、/product-<int:pid>.html
    get_api_routes -> GET /api/v1/columns/<slug>/products、GET /api/v1/products/<int:pid>
    sitemap_urls -> 启用产品详情页
```

- **权限分层**：`product:manage` 管插件入口（菜单/列表页可见性）；栏目内增删改沿用 `content:create/edit/delete/batch` + 栏目绑定（与文章完全一致），编辑角色在其授权栏目内可直接管理产品。

### 4.4 后台页面（蓝图 `product_admin`）

| 路由 | 说明 |
| --- | --- |
| `/products` | 产品列表（按栏目筛选 + 关键词分页，样式同文章列表） |
| `/products/create`、`/products/<pid>/edit` | 基础信息 + CKEditor 详情 + **相册多图上传（可拖拽排序）** + **规格参数编辑器**（分组行内增删，前端 JS 组装 JSON） |
| `/products/<pid>/delete`、`/products/batch` | 软删除与批量启停/删除/移动栏目 |
| `/columns/<cid>/products` | 栏目维度入口（同文章习惯） |

- 相册上传基于现有上传中心接口（走既有安全校验/压缩/缩略图/去重链路，零改动）；拖拽排序自托管 Sortable.js 或 ≤50 行原生实现（开放问题 §11.3）。

### 4.5 前台路由与模板

| 路由 | 说明 |
| --- | --- |
| `/column/<slug>/product/<int:pid>` | 产品详情动态 URL（与文章对称） |
| `/product-<int:pid>.html` | 产品详情伪静态 URL |

- **伪静态优先级**：`/product-{id}.html` 与 `/article-{id}.html` 同级，**先于 `/{slug}-{N}.html` 分页规则匹配**（复用 v2.1.0 的解析实现与回归用例，含 `pro-2024` 类 slug 不误切）。
- **呈现方式**：列表栏目 `list_template` 选 `product_list` 时，`column_detail` 查询该栏目产品分页（`sort_order, id desc`，page_size 取栏目配置）。
- **模板解析链**（§2.5）：`themes/<主题>/product_detail.html` → `plugins/product/templates/product_detail.html` → `themes/default/product_detail.html`。插件自带 default 风格两模板；manufacturing 主题提供行业化覆盖版本。
- 详情上下文：`product`（含 `gallery_urls`、`specs_grouped`、封面 URL、SEO meta）、`column`、同栏目上/下一个产品。
- **URL 助手** `frontend_product_url(product, column)` 注册为 Jinja 全局（伪静态开 → `/product-{id}.html`；关 → 动态 URL）。

### 4.6 SEO / 缓存集成

- 产品列表/详情复用 `cache_ttl_column` / `cache_ttl_article`，保存时清理相关缓存 key。
- sitemap：经插件 `sitemap_urls()` 钩子收录启用产品详情页（频率/优先级沿用文章规则）。

---

## 五、REST 内容 API（只读）

### 5.1 总体

- 核心新增蓝图 `app/api/__init__.py`：`api_bp = Blueprint('api', __name__, url_prefix='/api/v1')`。
- 插件通过 `get_api_routes(api_bp)` 向同一蓝图贡献端点，享受统一的鉴权/缓存/CORS 处理。
- 只输出与前台一致的数据（启用/未删除/文章已发布；自定义字段解析后输出）；不输出敏感字段；图片输出绝对 URL。
- 统一响应包：

```json
{"code": 0, "message": "ok", "data": {...}, "meta": {"page": 1, "per_page": 10, "total": 42, "total_pages": 5}}
{"code": 404, "message": "资源不存在", "data": null, "meta": null}
```

### 5.2 端点清单

| 来源 | 方法 | 端点 | 说明 |
| --- | --- | --- | --- |
| 核心 | GET | `/api/v1/site` | 站点信息：site_name、logo、备案、导航栏目树 |
| 核心 | GET | `/api/v1/columns` | 栏目列表/树（`?parent_id=&type=`） |
| 核心 | GET | `/api/v1/columns/<slug>` | 栏目详情：基础信息 + SEO + 自定义字段（单页含 page_content） |
| 核心 | GET | `/api/v1/columns/<slug>/articles` | 文章分页列表（`?page=&per_page=&keyword=`，per_page ≤ 50） |
| 核心 | GET | `/api/v1/articles/<int:aid>` | 文章详情：正文 HTML + 字段 + SEO + 上/下篇 |
| banner 插件 | GET | `/api/v1/banners/<slug>` | 轮播分组数据（同 `banner_items()` 输出） |
| product 插件 | GET | `/api/v1/columns/<slug>/products` | 产品分页列表 |
| product 插件 | GET | `/api/v1/products/<int:pid>` | 产品详情：gallery_urls、specs_grouped、content、SEO |

列表项不输出正文大字段；分页语义与后台一致（`error_out=False`）。

### 5.3 鉴权 / 缓存 / CORS

- `api_enable=off` → 所有 `/api/v1/*` 404；插件端点额外受插件启用门控（§2.3）。
- `api_token` 空 → 公开只读；非空 → 校验请求头 `X-API-Token`（`hmac.compare_digest` 恒时比较），失败 401。
- 缓存：`cache.memoize(timeout=api_cache_ttl)`（默认 60s），按端点+全参数 key；不做精确失效（文档标注最长延迟）。
- CORS：`api_cors_origins` 非空时 `after_request` 追加 `Access-Control-Allow-Origin`；`OPTIONS` 预检 204。
- 限流：v2.2 不实现，wiki 给出 Nginx 层限流建议。

---

## 六、新增设置项

「系统设置」新增「内容 API」页（写入 `site_settings`，审计翻译字典补齐）：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `api_enable` | `on` | 内容 API 总开关 |
| `api_token` | （空） | 非空时要求 `X-API-Token` 头 |
| `api_cache_ttl` | `60` | 接口缓存秒数 |
| `api_cors_origins` | （空） | 跨域白名单，逗号分隔，`*` 全部 |

插件自身配置（本版不需要）约定键名前缀 `plugin_<slug>_`，存 `site_settings`，插件自行读写。

---

## 七、数据库与升级策略

| 项 | 说明 |
| --- | --- |
| 核心表 | **零变更**（仅 `site_settings` 新增 4 键，读取缺省兜底） |
| 插件表 | `banner_groups`、`banners`、`products` 三张全新表；启动全量导入模型后 `db.create_all()` 自动创建（未启用也只有空表，无害） |
| 权限数据 | 启用插件时幂等种子 `banner:manage` / `product:manage` 并按 `preset_role_grants` 补授预设角色 |
| schema_migrations | 记录 `v2.2.0`（沿用现有机制） |
| 升级方式 | v2.1.x **覆盖代码即升级，无手工 SQL**；升级后插件默认禁用（`enabled_plugins` 空），老站到「插件管理」自行启用 |
| 新装 | 初始化向导新增「插件」步骤，默认勾选轮播图 + 产品（演示数据依赖），可取消 |

---

## 八、演示数据与初始化向导

`generate_demo_data(industry)` 扩展（经插件 `demo_data()` 钩子，仅对启用插件生效）：

| 行业 | 轮播图插件 | 产品插件 |
| --- | --- | --- |
| manufacturing | 「首页大图」分组 3 张 | 「产品中心」栏目（list_template=product_list）+ 6 个产品（3-5 张相册、两组规格参数） |
| service | 「首页横幅」分组 3 张 | 不生成 |

演示数据先经 `_clean_demo_data()` 清理（含插件表，防唯一约束冲突，沿用现有惯例）；向导流程：选库 → 基础信息 → **插件勾选** → 演示数据（依赖前一步的启用结果）。

---

## 九、文档与发布清单

| 项 | 内容 |
| --- | --- |
| README.md | 特性一览补「插件机制」；新增「v2.2.0 更新内容」（插件机制/两个首批插件/API）；发布时更新版本声明 |
| CHANGELOG.md | `[2.2.0]` 章节（Added 为主 + 升级方式说明） |
| wiki.html | 手册新增：插件机制与启停、轮播图使用、产品管理、内容 API（端点表 + 调用示例）；发布时更新版本徽标 |
| UPGRADE.md | v2.1→v2.2 小节（覆盖代码即可 + 验证清单：插件管理页可见、启用后菜单/前台/API 生效、禁用后 404 且模板不崩） |
| 插件开发指南 | wiki 或独立文档：目录结构、PluginBase 契约、钩子清单、模板解析链、最小示例 |
| 版本号 | 发布时 `Setting.CMS_VERSION = '2.2.0'` |

---

## 十、测试清单（实施时逐项验证）

1. **插件机制**：发现/导入失败隔离（放一个坏插件不拖垮启动）；启用→表创建+权限种子+菜单出现+前台生效；禁用→菜单隐藏+路由 404+模板函数返回空+API 404；重复启停幂等；审计留痕。
2. **轮播图插件**：分组/图片 CRUD、排序、启停、定时上下线边界、`ref_count` 增减与删除拦截、缓存失效、`banner_items` 未启用返回 `[]` 且模板不报错、API 端点。
3. **产品插件**：多图上传/拖拽排序/删除、规格分组编辑与前台渲染、封面兜底、伪静态 `/product-{id}.html` 与分页规则互不干扰（`pro-2024` 回归）、栏目级权限（未授权栏目不可见）、批量操作、软删除恢复、sitemap 收录、缓存清理。
4. **API**：全端点 200/404/401、`api_enable=off` 整体 404、token 恒时比较、分页边界、CORS 头、缓存 TTL、无敏感字段、与前台渲染一致性抽查、插件端点随插件禁用消失。
5. **升级与新装**：v2.1.1 库覆盖代码启动 → 核心表无变化、插件表自动创建、老功能冒烟；新装向导插件步骤与演示数据联动。
6. **多 worker 模拟**：gunicorn 2 worker 下启停插件，两个 worker 行为一致。

---

## 十一、开放问题（评审时确定）

1. 产品「型号/价格」独立字段 vs 全走规格参数 JSON？（当前：全走 specs）
2. `frontend` 蓝图的伪静态兜底：`/product-{id}.html` 在关闭伪静态时是否仍可访问？（当前设计：动态 URL 始终可用，伪静态 URL 开启后生效，二者并存，与文章行为对齐）
3. 相册拖拽排序：自托管 Sortable.js（~40KB）vs 原生实现？
4. 栏目 slug 保留字校验：`article`、`product`（新增），是否对存量 slug 一次性检查并提示？
5. 预设角色补授权（`preset_role_grants`）是否需要在插件管理页展示「将影响哪些预设角色」的确认提示？
6. 插件开发指南的载体：wiki.html 新章节 vs 独立 `PLUGINS.md`？
