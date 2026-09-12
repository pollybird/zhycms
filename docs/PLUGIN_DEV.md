# 插件开发手册

> 适用版本：ZhyCMS ≥ 2.6.4　|　配套参考：`PLUGIN_DEPENDENCIES.md`（依赖/继承/最低版本详解）、[主题模板开发 API](THEME_TEMPLATE_API.md)

插件是 ZhyCMS 的核心扩展机制：后台菜单、前台页面、模板函数、导航、sitemap、全站搜索、REST API、存储驱动、演示数据，全部通过统一钩子接入。**启用/禁用即时生效，无需重启。**

- **实战样板**：`plugins/recruit`（最完整：独立路由 + 表单上传 + 搜索提供者）、`plugins/product`（栏目归属 + API）、`plugins/banner`（最简模板函数型）
- 本手册第 2 章内嵌一个**可直接落地的最小示例插件**，复制即用

---

## 1. 机制总览

### 1.1 目录约定

```
plugins/<slug>/
├── manifest.json     # 纯元数据（上传校验、后台展示用）
├── __init__.py       # PluginBase 子类 + 模块级 plugin 实例（必需）
├── models.py         # 数据模型（可选，导入即注册进 db.metadata）
├── admin.py          # 后台路由（可选，挂核心 admin_bp）
├── frontend.py       # 模板函数（可选）
├── frontend_routes.py# 前台蓝图（可选）
├── search.py         # 全站搜索提供者（可选）
├── migrations/versions/*.py  # 插件自有 Alembic 迁移（可选，自动合并）
├── translations/     # 插件独立翻译域（可选）
├── static/           # 前台静态资源（可选）
└── templates/        # 模板（后台 admin/<slug>/，前台 <slug>/）
```

### 1.2 加载与启停模型

```
启动期（discover_and_load）：
  全量导入所有插件 → 注册蓝图/模板函数/菜单/API/权限点/迁移/驱动 → 门控交给运行时

运行期：
  enabled_plugins 设置项（DB）单一开关 →
    视图守卫（未启用 404）、菜单隐藏、模板函数返回 fallback 值
  → 启停只改一个设置值，多 worker 天然一致，无需重启
```

要点：

- **启用**：种子权限点 → 给预设角色补授权 → `db.create_all()` 建表 → 写清单。历史数据保留可复用。
- **禁用**：仅从清单移除 slug，回调 `on_disabled()`；**表与数据保留**。
- **卸载**：验证码确认后物理删除目录；数据表保留（保守策略，防误删）。
- 模板解析链：**主题覆盖 → 插件自带 → default 主题兜底**。

---

## 2. 五分钟上手：最小完整示例插件

下面是一个完整可运行的「公告板」插件（slug: `notice`），包含：后台管理页、前台列表页、模板函数、导航贡献。新建 `plugins/notice/` 目录，放入以下文件，后台「插件管理」刷新即可看到并启用。

### 2.1 manifest.json

```json
{
  "slug": "notice",
  "name": "公告板",
  "version": "1.0.0",
  "description": "站点公告发布与前台展示，插件开发示例。",
  "author": "ZhyCMS 社区示例",
  "builtin": false,
  "min_core_version": "2.6.4",
  "requires": [],
  "extends": ""
}
```

### 2.2 `__init__.py`（入口，必需）

```python
from app.plugin_api import PluginBase

# ⚠️ 顶部导入模型，保证在 db.create_all() 之前注册进 metadata
from .models import Notice

from .frontend import notice_list


class NoticePlugin(PluginBase):
    slug = 'notice'
    name = '公告板'
    version = '1.0.0'

    # 启用时幂等种子的权限点：(code, 名称, 描述)
    permissions = [('notice:manage', '公告管理', '站点公告的发布与维护')]
    # 启用时给预设角色补授权
    preset_role_grants = {'content_editor': ['notice:manage']}
    # 审计日志筛选下拉中的模块名
    audit_modules = [('notice', '公告板')]

    def get_admin_routes(self, admin_bp):
        from . import admin  # noqa: F401  导入即向 admin_bp 注册路由

    def get_admin_menu(self):
        return [{'label': '公告管理', 'endpoint': 'admin.notice_index',
                 'icon': 'fa-bullhorn', 'permission': 'notice:manage'}]

    def get_frontend_blueprint(self):
        from .frontend_routes import notice_frontend
        return notice_frontend

    def get_jinja_globals(self):
        return {'notices': notice_list}

    def get_jinja_fallbacks(self):
        # 插件禁用时模板函数返回这些空值，主题无需判空报错
        return {'notices': []}

    def get_frontend_menu(self):
        return [{'label': '网站公告', 'url': '/notices', 'target': ''}]


plugin = NoticePlugin()   # ⚠️ 必需：核心通过模块级 plugin 变量识别插件
```

### 2.3 models.py

```python
from datetime import datetime
from app import db


class Notice(db.Model):
    __tablename__ = 'notices'

    STATUS_ON = 'on'
    STATUS_OFF = 'off'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text)                # 富文本，前台 |safe 输出
    status = db.Column(db.String(10), default=STATUS_ON)
    sort_order = db.Column(db.Integer, default=0)
    is_deleted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    @classmethod
    def visible(cls):
        return (cls.query.filter_by(is_deleted=False, status=cls.STATUS_ON)
                .order_by(cls.sort_order.desc(), cls.id.desc()))
```

### 2.4 admin.py（后台路由，挂核心 admin_bp）

```python
from functools import wraps

from flask import abort, flash, redirect, render_template, request

from app import db
from app.admin import bp as admin_bp          # 核心 admin_bp，不要自建后台蓝本
from app.decorators import permission_required
from app.models.audit import audit_log
from app.plugin_system import plugin_enabled

from .models import Notice


def _gate(view):
    """三层守卫之一：插件启用门控（未启用直接 404）。"""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('notice'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


@admin_bp.route('/notice')
@_gate
@permission_required('notice:manage')        # 守卫之二：权限点
def notice_index():
    page = request.args.get('page', 1, type=int)
    pager = (Notice.query.filter_by(is_deleted=False)
             .order_by(Notice.sort_order.desc(), Notice.id.desc())
             .paginate(page=page, per_page=20, error_out=False))
    return render_template('admin/notice/index.html', pager=pager)


@admin_bp.route('/notice/add', methods=['POST'])
@_gate
@permission_required('notice:manage')
def notice_add():
    title = (request.form.get('title') or '').strip()
    if not title:
        flash('标题不能为空', 'danger')
        return redirect(admin_bp + '.notice_index') if False else redirect('/admin/notice')  # 见下方说明
    row = Notice(title=title, content=request.form.get('content') or '',
                 sort_order=request.form.get('sort_order', 0, type=int))
    db.session.add(row)
    db.session.commit()
    audit_log('notice', 'create', f'新增公告 #{row.id}', {'id': row.id, 'title': title})
    flash('公告已发布', 'success')
    return redirect('/admin/notice')


@admin_bp.route('/notice/<int:nid>/delete', methods=['POST'])
@_gate
@permission_required('notice:manage')
def notice_delete(nid):
    row = db.session.get(Notice, nid) or abort(404)
    row.is_deleted = True                     # 软删除，与核心内容一致
    db.session.commit()
    audit_log('notice', 'delete', f'删除公告 #{nid}', {'id': nid})
    flash('公告已删除', 'success')
    return redirect('/admin/notice')
```

> ⚠️ 实际项目中重定向请使用 `url_for('admin.notice_index')`（endpoint 归入 `admin.*` 命名空间后自动兼容后台前缀切换）。上面示例为排版紧凑做了简化。

### 2.5 frontend.py（模板函数）

```python
from .models import Notice


def notice_list(limit=10):
    """模板函数：主题里 {{ notices(5) }} 直接取最新公告。"""
    return [{'id': n.id, 'title': n.title,
             'url': f'/notice-{n.id}.html'}
            for n in Notice.visible().limit(limit)]
```

### 2.6 frontend_routes.py（前台蓝图）

```python
from functools import wraps

from flask import Blueprint, abort, render_template

from app.plugin_system import plugin_enabled
from app.utils.themes import get_active_theme
import os

from .models import Notice

notice_frontend = Blueprint('notice_frontend', __name__,
                            template_folder='templates',
                            static_folder='static',
                            static_url_path='/plugins-static/notice')


def _gate(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('notice'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def _resolve_template(name):
    """机制：主题覆盖 → 插件自带 → default 兜底。"""
    theme = get_active_theme()
    if os.path.isfile(os.path.join('app/frontend/templates/themes', theme, name)):
        return f'themes/{theme}/{name}'
    return f'notice/{name}'


@notice_frontend.route('/notices')
@_gate
def notice_page():
    page = request.args.get('page', 1, type=int)
    pager = Notice.visible().paginate(page=page, per_page=15, error_out=False)
    return render_template(_resolve_template('notices.html'), pager=pager)
```

### 2.7 模板（插件自带，主题可覆盖）

`templates/admin/notice/index.html`（后台，继承后台基模板）：

```jinja
{% extends 'admin/base.html' %}
{% block content %}
<h4 class="mb-3">公告管理</h4>
<form method="post" action="{{ url_for('admin.notice_add') }}" class="form-inline mb-3">
  <input name="title" class="form-control mr-2" placeholder="公告标题" required>
  <input name="sort_order" type="number" class="form-control mr-2" value="0" style="width:100px">
  <button class="btn btn-primary">发布</button>
</form>
<table class="table table-sm">
  {% for n in pager.items %}
  <tr>
    <td>{{ n.title }}</td>
    <td>{{ n.created_at|datetime }}</td>
    <td>
      <form method="post" action="{{ url_for('admin.notice_delete', nid=n.id) }}"
            onsubmit="return confirm('确认删除该公告？')">
        <button class="btn btn-sm btn-outline-danger">删除</button>
      </form>
    </td>
  </tr>
  {% endfor %}
</table>
{% endblock %}
```

`templates/notice/notices.html`（前台，继承当前主题）：

```jinja
{% extends theme_base %}
{% block title %}网站公告 - {{ site_settings.site_name }}{% endblock %}
{% block content %}
<div class="container py-4">
  <h2>网站公告</h2>
  <ul class="list-group">
    {% for n in pager.items %}
    <li class="list-group-item d-flex justify-content-between">
      <span>{{ n.title }}</span>
      <small class="text-muted">{{ n.created_at|date }}</small>
    </li>
    {% else %}
    <li class="list-group-item text-muted">暂无公告</li>
    {% endfor %}
  </ul>
</div>
{% endblock %}
```

完成。目录结构：

```
plugins/notice/
├── manifest.json
├── __init__.py
├── models.py
├── admin.py
├── frontend.py
├── frontend_routes.py
└── templates/
    ├── admin/notice/index.html
    └── notice/notices.html
```

---

## 3. manifest.json 字段参考

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `slug` | string | ✅ | 插件标识，`^[a-zA-Z0-9_-]{2,32}$`，与目录名一致 |
| `name` | string | ✅ | 显示名称 |
| `version` | string | ✅ | 插件版本（语义化版本） |
| `description` | string | 建议 | 一句话描述 |
| `author` | string | 建议 | 作者 |
| `builtin` | bool | 建议 | `true` 内置保护：禁止卸载/覆盖上传 |
| `min_core_version` | string | 建议 | 最低核心 CMS 版本，低于拒绝启用（v2.6.4） |
| `requires` | string[] | 可选 | 依赖插件 slug 列表，启用前须已启用（v2.6.4） |
| `extends` | string | 可选 | 父插件 slug（二次开发），须已安装且启用（v2.6.4） |

启用校验顺序：**最低核心版本 → requires → extends**；禁用被依赖插件会被反向拦截。详见 `PLUGIN_DEPENDENCIES.md`。

---

## 4. PluginBase API 参考

### 4.1 类属性

| 属性 | 说明 |
| --- | --- |
| `slug` / `name` / `version` / `description` / `author` | 元数据，与 manifest.json 保持一致（**以类属性为准**） |
| `min_core_version` / `requires` / `extends` | 依赖三件套（v2.6.4），与 manifest 一致 |
| `permissions` | `[(code, label, desc)]`，启用时幂等写入 permissions 表 |
| `preset_role_grants` | `{role_code: [perm_code]}`，启用时给预设角色补授权 |
| `audit_modules` | `[(module_code, label)]`，审计日志筛选下拉聚合 |

### 4.2 钩子方法

| 钩子 | 返回 | 说明 |
| --- | --- | --- |
| `get_admin_routes(admin_bp)` | None | 在核心后台蓝本注册路由（endpoint 归入 `admin.*`，兼容前缀切换） |
| `get_frontend_blueprint()` | Blueprint/None | 前台蓝本，建议命名 `<slug>_frontend` |
| `get_api_routes(api_bp)` | None | 向 `/api/v1` 注册只读端点，自动享受鉴权/CORS/缓存 |
| `get_jinja_globals()` | dict | `{函数名: 函数}`，核心自动包裹「启用守卫」 |
| `get_jinja_fallbacks()` | dict | `{函数名: 未启用返回值}`，未声明默认 None |
| `get_admin_menu()` | list | 后台菜单：`{'label','endpoint','icon','permission','active_prefix'}` |
| `get_frontend_menu()` | list | 前台导航：`{'label','url','target'}`，仅启用时聚合 |
| `get_frontend_guard()` | dict/None | v2.6.4 前台登录守卫（会员体系）：`{'is_authenticated': callable, 'login_url': callable}` |
| `get_sitemap_urls()` | yield dict | `{'loc','lastmod','changefreq','priority'}`，loc 为完整 URL |
| `get_search_provider()` | SearchProvider/None | v2.5.2 全站搜索提供者（见 §8.3） |
| `get_migration_files()` | list | 自动发现 `migrations/versions/*.py`，一般无需覆写 |
| `get_storage_drivers()` | list | 存储驱动类注册（oss_storage 插件使用） |
| `generate_demo_data(industry)` | None | 演示数据钩子，仅启用时调用 |
| `get_i18n_dir()` | str | 插件翻译目录，默认 `translations/` |
| `on_disabled()` | None | 禁用回调：清理外部资源（如搜索索引残留） |
| `_(message)` / `ngettext(s, p, n)` | str | 插件域翻译便捷函数 |

### 4.3 可用的核心工具函数

| 函数 | 位置 | 用途 |
| --- | --- | --- |
| `plugin_enabled(slug)` | `app.plugin_system` | 视图守卫：插件是否启用 |
| `permission_required(code)` | `app.decorators` | 权限点装饰器 |
| `audit_log(module, action, detail, data)` | `app.models.audit` | 写审计日志 |
| `reindex_object(type, id)` / `unindex_object(type, id)` | 搜索工具 | 保存/删除时同步搜索索引 |
| `save_upload_file(file, exts)` | `app.utils.helpers` | 安全上传（从原始文件名取后缀，兼容中文文件名） |
| `api_ok(data)` / `api_err(code, msg)` / `api_cache(type)` | API 工具 | REST 端点统一响应与缓存 |
| `t_field(obj, field)` | `app.utils.i18n_content` | 内容级多语言取值（空回退主表） |

---

## 5. 数据模型规范

1. **自动建表**：启用时 `db.create_all()` 幂等补齐；模型必须在插件 `__init__.py` 顶部导入。
2. **schema 变更**：新字段直接加列对 SQLite 无效，需在 `plugins/<slug>/migrations/versions/` 放 Alembic 脚本，核心启动自动合并进 `version_locations`（见运维 FAQ「迁移失败处理」）。
3. **多语言**：主表存默认语言，翻译表存非默认语言（`<table>_translations`，含 `locale` 与外键 `ondelete='CASCADE'`）；前台用全局 `t(obj, 'field')`、Python 用 `t_field`，查不到翻译自动回退主表。
4. **软删除**：内容类数据用 `is_deleted`，与核心行为一致；展示查询统一过滤。

---

## 6. 后台开发要点

- **路由**：一律挂核心 `admin_bp`（`@admin_bp.route('/<slug>/...')`），endpoint 自动归入 `admin.*`；不要自注册后台蓝本，否则后台前缀切换不生效。
- **三层守卫**：`_gate`（启用）→ `@permission_required`（权限）→ 业务校验（参数/状态）。
- **菜单**：`get_admin_menu()` 声明；启用且有权限才显示。
- **审计**：写操作调 `audit_log()`；`audit_modules` 让模块出现在筛选下拉。
- **模板**：放 `templates/admin/<slug>/`，继承 `admin/base.html`；脚本块用 `{% block js %}`（父模板不存在同名 block 会被静默丢弃）。

## 7. 前台开发要点

- **蓝本**：`Blueprint(f'{slug}_frontend', __name__, template_folder='templates', static_folder='static', static_url_path=f'/plugins-static/{slug}')`。
- **守卫**：每个视图套启用门控；含验证码/flash 的交互页不要接页面缓存。
- **模板解析**：优先主题内同名文件（`themes/<theme>/<name>.html`），回退插件自带；参考 §2.6 `_resolve_template()`。
- **模板函数**：返回 dict/list（避免直接返回模型对象，防止懒加载异常）；**必须**在 `get_jinja_fallbacks()` 声明禁用时的空值。
- **导航**：`get_frontend_menu()` 追加在栏目之后；归属栏目的插件（如 product）无需实现。
- **伪静态**：详情页同时提供动态路由与 `/<slug前缀>-<id>.html` 伪静态路由；伪静态路由在 `seo_rewrite_enable` 关闭时应 404。不得使用 `article-` / `job-` 之外与核心冲突的前缀。
- **会员可见性**（v2.6.4）：实现 `get_frontend_guard()` 后，核心会对 `member_only` 栏目做导航隐藏与登录跳转。

## 8. 能力集成

### 8.1 文件上传

复用 `save_upload_file()`：从**原始文件名**提取后缀（防 `secure_filename` 丢中文后缀）、白名单校验、路径安全。下载用户上传的敏感文件时用 `werkzeug.utils.safe_join` 二次校验路径。

### 8.2 验证码与表单安全

- 图形验证码一次性消费（`session.pop(...)`），用后即焚；
- 写操作用 POST + PRG（提交后重定向）防重复提交；
- 记录来源 IP 便于审计。

### 8.3 全站搜索提供者（v2.5.2）

```python
from app.utils.search import SearchProvider

class NoticeSearchProvider(SearchProvider):
    type = 'notice'                      # 全局唯一，索引 uid 前缀

    def iter_docs(self, locale):         # 重建索引：逐条产出可见文档
        for n in Notice.visible():
            yield self._doc(n, locale)

    def get_doc(self, obj_id, locale):   # 实时索引；返回 None 表示移出索引
        n = db.session.get(Notice, obj_id)
        return self._doc(n, locale) if n and not n.is_deleted else None

    def sql_search(self, keyword, locale, page=1, per_page=20):
        ...                              # 索引故障时的 LIKE 兜底，返回 (items, total)

    def build_url(self, item):
        return f'/notice-{item["id"]}.html'   # 或 url_for(...)
```

文档 dict 字段：`id, title, summary, content(可含 HTML，核心自动去标签), column_id, column_name, column_slug, published_at`。⚠️ `iter_docs/get_doc` 必须自己过滤下架/删除内容。

### 8.4 REST API 扩展

```python
def get_api_routes(self, api_bp):
    @api_bp.route('/notices')
    @api_cache('notice')
    def list_notices():
        if not plugin_enabled('notice'):
            return api_err(404, '资源不存在')
        return api_ok([{'id': n.id, 'title': n.title}
                       for n in Notice.visible().limit(50)])
```

### 8.5 插件国际化

`translations/en/LC_MESSAGES/messages.po` 编译为 `.mo` 后自动加载为独立域：

- Jinja：`{{ _p('notice', '公告') }}`
- Python：`self._('公告')`

### 8.6 存储驱动 / 演示数据 / 迁移

- 存储驱动：`get_storage_drivers()` 返回 `CloudStorageDriver` 子类列表（契约见 `plugins/oss_storage/drivers/base.py` docstring）；按归属插件门控，禁用即回退本地。
- 演示数据：`generate_demo_data(industry)` 在初始化向导勾选时调用。
- Alembic：`plugins/<slug>/migrations/versions/xxx.py` 自动并入迁移链（rev 需自行衔接核心链尾或插件内前序版本）。

## 9. 打包、上传与生命周期

| 事项 | 规则 |
| --- | --- |
| 压缩包格式 | 仅 `.zip` / `.tar.gz` / `.tgz`；必须含 `manifest.json` 与 `__init__.py`（`api.py` 可选） |
| slug 校验 | manifest 必须为合法 JSON 对象且 slug 匹配 `^[a-zA-Z0-9_-]{2,32}$` |
| 路径安全 | 含 `../` 越界、绝对路径、symlink/hardlink/fifo 的包被拒绝或跳过 |
| 上传过程 | 全程临时目录，任何失败不写入 `plugins/`；同名插件先备份删除再覆盖 |
| 危险操作 | 卸载/删除需验证码确认；启用中或内置插件拒绝删除 |
| 打包下载 | 后台一键 zip 导出，可在其他站点复用 |

## 10. 自测清单

- [ ] 启动无异常，插件管理页显示「已加载」
- [ ] 启用后权限点/角色授权/数据表创建成功，菜单出现
- [ ] 后台 CRUD 正常且审计有记录；无权限用户 403
- [ ] 前台页面动态访问 200；伪静态开关两种模式均正常
- [ ] 禁用后：后台 404、前台 404、导航/sitemap/API 消失、模板函数返回 fallback
- [ ] 搜索：保存可搜到、删除后消失、禁用插件无索引残留
- [ ] 多语言：翻译留空回退默认语言
- [ ] 卸载目录删除、重新上传可恢复；上传带路径穿越的包被拒绝

## 11. 常见陷阱

| 陷阱 | 后果 |
| --- | --- |
| 忘写 `plugin = MyPlugin()` | 核心识别不到插件，显示未加载 |
| 模型导入晚于 `db.create_all()` | 表缺失，SQL 报 1146/no such table |
| 后台路由自建蓝本 | 后台前缀切换后路由失效 |
| 模板里用 `{{ j.url }}` 而模型无该属性 | Jinja 静默输出空 href |
| `get_jinja_fallbacks()` 漏声明 | 禁用插件后主题渲染报错 |
| 交互页接了页面缓存 | 验证码/flash 错乱、用户间串数据 |
| 伪静态前缀与核心 `article-` 冲突 | 路由劫持，文章页 404 |
| SearchProvider 未过滤下架内容 | 已下架内容仍可被搜到 |
| 后台模板用了 `scripts` block | 脚本不执行（正确为 `{% block js %}`） |
| 字典取值 `g.items` | 命中 dict 方法名，取不到数据（应为 `g['items']`） |
