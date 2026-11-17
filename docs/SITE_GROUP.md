# 站群模式（多站点 / Site Group）设计方案

> 状态：**v3.2.0 已落地（M1–M4 全部完成）**。本文档保留设计依据，实现细节与偏差以文末「十四、落地记录」为准。
> 适用版本：v3.2.0。迁移脚本：`migrations/versions/0012_v3_2_0_sites.py`。

ZhyCMS 当前为**单实例 / 单站点**架构：全站无 `site_id`、子域、域名解析概念（已全局确认）。站群模式的本质是**一个后端实例 + 一个库，按「站点」维度切分内容**，让同一套 CMS 同时服务多个相互独立又共享后台/插件/资产的前台站点。

---

## 一、设计总纲

站群 = 在现有 i18n 的「语言维度」之上**再加一个「站点」维度**。站点是**主维度**（按域名/子域解析），语言是次维度，二者**正交**（一个站点自身仍可多语言）。

复用库里已有的两个成熟先例，最大化与现有架构的一致性：

1. **i18n 的「维度列 + 翻译表 + fallback + 请求级解析」范式**（`locale` 列 / `select_locale()` 五级优先 / `t_field()` fallback / 请求级缓存）——这是给内容「加一个正交维度」的最接近参照物；站点解析器 `select_site()` 完全照此范式实现。
2. **RBAC 的 `UserColumnPermission`（user→column 细粒度绑定）**——这是「把权限按一个资源维度收窄」的参照物；站点权限 `UserSitePermission` 直接镜像。

**核心兼容性保证**：默认站点 `site_id = 0`，等价于现网单站点。单站点部署**零感知**——解析器对唯一域名恒返回 0，所有查询 `site_id=0`，现有 slug/配置行迁移后 `(·,0)` 不变，**URL、行为、SEO 全部不变**。只有创建第 2 个站点时才激活多站点路径。

### 四项产品决策（已锁定）

| # | 决策点 | 结论 |
| --- | --- | --- |
| 1 | 站点寻址 | **泛解析子域 + 独立域名都要**：`sites.domain`（精确匹配全量域名）+ `sites.subdomain`（子域标签）双列，解析器「精确 domain → 子域标签 → 默认 0」三段回落 |
| 2 | 前台会员 | **超管可选共享/独立**：新增 `members.site_id` + 全局开关 `member_scope`（`shared` 默认 / `isolated`），共享模式复用 `site_id=0` 哨兵保持全局唯一 |
| 3 | 上传资产 | **跨站共享**：`uploaded_files` **不加** `site_id`，按 `content_hash` 全局去重、按 URL 引用，最大化去重收益，零改动 |
| 4 | 默认站点 | **落 `sites` 表 id=0**（`is_default=True`），注册表完整；MySQL 需临时 `NO_AUTO_VALUE_ON_ZERO` |

---

## 二、现状基线（设计依据，均已核实）

- `Column.slug` / `Fragment.slug` 均为 `unique=True`（**全局唯一**）→ 站群下不同站点必须能复用 `about`、`news` 等 slug，须改为**站点内唯一**（`(site_id, slug)`）。
- `Article` 无 slug，靠全局 `id` 解析（`/article-<aid>.html`、`/article/<aid>`）→ 站点维度通过其 `column_id` 隐式继承 + **冗余 `site_id`** 便于快速过滤。
- `Setting.key` 全局唯一，整表是「站点配置」载体（site_name/seo/theme/cache/analytics）→ 站点化配置须能按站点取值。
- `builder_pages` 唯一约束 `(scope, column_id)` → column 已站点化，天然站点内唯一，无需改。
- i18n：主表存默认语言、`*_translations` 存非默认语言、`t_field()` 按 locale 取 + fallback；`select_locale()` 五级优先级、请求级缓存 → **站点解析器照此范式**。
- `UserColumnPermission(user_id, column_id, can_review, can_publish)` → 站点权限 `UserSitePermission` 直接镜像。
- 前台 `column_detail(slug)` = `Column.query.filter_by(slug=slug, is_deleted=False)` → 仅需追加 `site_id=current_site_id()`。
- `get_active_theme()` 读全局 `Setting.get('site_theme')` → 扩展为「站点自定义主题 → 全局默认主题」fallback。
- 迁移：Alembic，`0001` 基线 + 幂等 `_table_exists()` 守卫 + `ensure_*` 回填（见 `Article.ensure_status_column`）→ 新迁移 `0010` 沿用。

---

## 三、总体架构

```
请求 → [① 站点解析器 select_site()] → g.current_site_id (=0 默认)
         │  依据 request.host / ?site= / 后台切换
         ▼
   [② SiteScoped 内容表]  columns / articles / fragments / settings / members …
         全部查询追加 site_id = current_site_id()
         ▼
   [③ 站点化配置 / 主题]  站点自定义 → 全局默认 fallback
         ▼
   [④ 站点注册表 sites + RBAC UserSitePermission]
```

新增四件事：**站点解析层**（`app/sites.py`）、**`site_id` 维度列**（`SiteScopedMixin`）、**站点化配置/主题**、**站点注册表 + RBAC**。

---

## 四、数据模型

### 4.1 新增 `sites` 表（站点注册表）

```python
class Site(db.Model):
    __tablename__ = 'sites'
    id           = db.Column(db.Integer, primary_key=True)   # 默认站点固定为 0
    name         = db.Column(db.String(100), nullable=False)
    slug         = db.Column(db.String(100), unique=True, nullable=False)  # 后台标识
    domain       = db.Column(db.String(255), unique=True)        # 全量域名，如 www.b.com（精确匹配）
    subdomain    = db.Column(db.String(100), index=True)          # 子域标签，如 b（配合泛解析 *.main.com）
    status       = db.Column(db.String(16), default='open')        # open / closed（站点级维护）
    theme        = db.Column(db.String(64))                        # 站点主题，空则回退全局 site_theme
    is_default   = db.Column(db.Boolean, default=False, nullable=False)  # 仅 site 0 为 True
    # 站点级 SEO（冗余，便于按站点直取，无需 join settings）
    seo_title    = db.Column(db.String(255))
    seo_keywords = db.Column(db.String(255))
    seo_description = db.Column(db.String(500))
    sort_order   = db.Column(db.Integer, default=0, nullable=False)
    is_deleted   = db.Column(db.Boolean, default=False, nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at   = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
```

**domain 与 subdomain 并存**的原因：覆盖两种真实站群部署——① 独立域名（`www.a.com` / `www.b.com`）用 `domain` 精确匹配；② 泛解析子域（`*.main.com`，一条 DNS `*` 解析到同一实例）用 `subdomain` 标签匹配。两者皆可，解析器按「精确 domain 优先 → 子域标签 → 默认站点」回落。

> **MySQL 注意**：默认站点显式插入 `id=0`。SQLite/PostgreSQL 原生支持；MySQL 需在迁移内临时 `SET sql_mode=NO_AUTO_VALUE_ON_ZERO`（会话级），或将 `id` 改为非自增、由应用 `max(id)+1` 分配。本项目**默认 SQLite**（`config.py` 回退 `instance/zhycms.db`），首选前者。

### 4.2 `site_id` 列挂载（DRY：`SiteScopedMixin`）

新增 `app/models/site.py`：

```python
class SiteScopedMixin:
    """内容按站点切分的统一维度列（镜像 i18n 的 locale 维度）。"""
    site_id = db.Column(db.Integer, nullable=False, default=0,
                        server_default='0', index=True)
```

| 表 | 是否加 `site_id` | 理由 |
| --- | --- | --- |
| `columns` | ✅ **权威来源** | 栏目属于站点；slug 改 `(site_id, slug)` 唯一 |
| `articles` | ✅ **冗余**（由 column 同步） | 首页跨栏目、后台列表需免 join 快速过滤；迁移时由 `columns.site_id` 回填；栏目移动时同步 |
| `fragments` | ✅ | 碎片站点化（site_name/footer 等）；slug 改 `(site_id, slug)` 唯一 |
| `settings` | ✅（见 4.3） | 站点化配置 |
| `members` | ✅（见 4.4，配合 `member_scope` 开关） | 超管可选共享/独立；共享模式恒为 0 |
| `audit` | ➕ 加 `site_id` 列（默认 0） | 仅用于溯源「操作发生在哪个站点」，表本身全局 |
| `builder_pages` | ⬜ 不加 | `(scope, column_id)` 已站点内唯一，column 已携带站点 |
| `column_fields` / `column_field_values` | ⬜ 不加 | 经 `column_id` 继承站点 |
| `uploaded_files` | ⬜ **不加（决策 3：跨站共享）** | 按 `content_hash` 去重、按 URL 引用，跨站点共享资产最大化去重收益 |
| `users/roles/permissions/user_roles` | ⬜ 不加 | 后台账号跨站点；站点访问是**权限**问题（见 §8 RBAC） |
| `member_oauths` / `member_sms_codes` | ⬜ 不加 | 经 `member_id` 继承归属 |
| 插件内容表（`forms`/`friend_links`/product/job…） | ✅（插件侧迁移） | 见 §9 插件 SDK；slug 类改 `(site_id, slug)` |

### 4.3 `settings` 站点化

`settings` 整表是站点配置载体，必须能按站点取值。最一致的做法：**给 `settings` 加 `site_id`，唯一约束 `key` → `(key, site_id)`，现有行全部迁移为 `(key, 0)`**。

读取语义（在 `Setting.get/set` 内实现）：

- 引入**全局键**集合 `GLOBAL_KEYS`（每实例一份、与站点无关）：`redis_*`、`oss_*`/`storage_*`、`api_*`/`jwt_*`、`i18n_*`、`search_*`、`login_*`、`upload_*`（安全策略）、`audit_*`/`backup_*`、`member_scope`。这些**恒取 `site_id=0`**。
- **站点键**（`site_name`/`seo_*`/`site_theme`/`site_status`/`site_close_reason`/`footer_copyright`/`analytics_*`/`cache_*`/`form_notify_*`/`notify_*` 等）取**当前站点** `site_id`。
- 默认站点（0）读取 `(key,0)` = 迁移后的现有行 → **行为完全不变**。

请求级缓存 `_settings_map` 键改为 `_settings_map_{sid}`；`set()` 后按对应 `sid` 失效。

### 4.4 前台会员 共享/独立（决策 2）

核心技巧：**复用 `site_id=0` 哨兵**，让「共享」自然等价于「全局唯一」，无需两套逻辑。

1. `members` 加 `site_id`（`Integer, default=0, server_default='0'`）。
2. `username` 由**全局 `unique=True`** 改为**复合唯一 `UniqueConstraint('site_id','username')`**：
   - **共享模式**（`member_scope=shared`，默认）：所有会员 `site_id=0` → `(0, username)` 约束 = 全局唯一，**与现网完全一致**；
   - **独立模式**（`member_scope=isolated`）：会员归属当前站点（`site_id=当前站`）→ 各站独立唯一，互不冲突。
3. 新增全局 Setting `member_scope` ∈ `shared`（默认，向后兼容）/ `isolated`。超管在后台切换。
4. 影响点清单（改造时按此执行）：
   - 会员注册时按 `member_scope` 决定是否写入 `current_site_id()`；
   - `member` 插件 `frontend_routes.py` 的 `Member.query.filter_by(username=...)`（及按 phone 登录/短信验证码）在**独立模式下**追加 `site_id=current_site_id()`；共享模式行为不变；
   - 前台会员相关查询（`member_only` 栏目判定、会话归属）同样按模式追加站点过滤。
5. 注意点：`shared ↔ isolated` 是**数据操作**而非纯开关——切换时已有会员的 `site_id` 归属需明确（约定：切 isolated 时存量会员保留 `site_id=0` 归默认站点，新注册按当前站落）。`phone`/`email` 本就是非唯一索引，独立模式下天然可跨站共存。

---

## 五、站点解析层（新增 `app/sites.py`，镜像 `app/i18n.py`）

```python
def select_site():
    """每请求首调，结果缓存于 g.current_site_id。返回 int（0=默认站点）。"""
    if has_app_context() and getattr(g, 'current_site_id', None) is not None:
        return g.current_site_id
    sid = _resolve_site_id()
    g.current_site_id = sid
    return sid

def current_site_id():
    return getattr(g, 'current_site_id', None) or 0
```

`_resolve_site_id()` 优先级（对齐 `select_locale()` 的「显式 → 持久 → 兜底」范式）：

1. 后台/预览：`?site=<slug或id>`（写回 `session['admin_site_id']`）；
2. **Host 精确匹配**：`request.host`（小写、去端口）== `sites.domain` → 该站；
3. **子域标签匹配**：主域泛解析时，取 `sub.domain` 的首标签 → `sites.subdomain`；
4. **兜底**：主域 / 未命中 → **默认站点 0**。

注册时机：`create_app()` 中前台 `frontend_bp.before_request`（在 `check_site_status` 之前，使其改为**站点级**维护判断：读当前站点 `sites.status` / 站点化 `site_status`），后台蓝图同样挂载（后台以 `session['admin_site_id']` 为准，默认 0）。

站点域名表做请求级缓存（`g._sites_by_host`），避免每请求两次查询；站点 CRUD 后由 service 层失效（与 `Column.invalidate_tree_cache` 同款手法）。

---

## 六、前台路由与渲染改造（改动面小、收益大）

所有「内容查询」追加 `site_id=current_site_id()`，URL 形状**不变**（子域/域名即站点根，伪静态 SEO 不变）：

- `column_detail(slug)`：`Column.query.filter_by(slug=slug, site_id=sid, is_deleted=False)`
- `article_detail`：文章经 `site_id == sid`（冗余列）+ column 校验（`article.column_id == col.id`）
- `_build_nav()` / `_home_section_data()` / 首页 `index` / 侧栏最新 / 上下篇：均加 `site_id=sid`
- `_try_cache` 缓存键加站点前缀：`f'site{sid}:index'`（见 §8）
- 新增 `site_url(site_id, endpoint, **kw)`：生成跨站点绝对 URL（站群导航/底部互链用；**默认不互链**，符合 SEO 最佳实践，避免权重分散）

**主题**：`get_active_theme()` 改为「当前站点 `sites.theme` → 全局 `site_theme`」fallback；`theme_template()` 随之取站点主题（主题文件仍在磁盘共享，仅选择器变化）。

---

## 七、后台改造

1. **站点管理**（`admin/system/` 新增）：站点 CRUD（name/slug/domain/subdomain/status/theme/SEO）。默认站点 0 不可删除、`is_default` 唯一；`domain`/`subdomain` 冲突校验。
2. **站点切换器**：后台侧栏下拉选择「当前站点」→ 写 `session['admin_site_id']`；栏目/文章/碎片/构建器/表单/友链等列表全部按当前站点过滤。
3. 默认站点（0）下，所有后台行为与现网一致（无切换器或切换器仅显示一个站点）。

---

## 八、RBAC 与站点权限

1. 新增权限点 **`site:manage`**（站点管理：增删改站点、配置域名），仅授予超管或显式勾选该权限的自定义角色（v3.2.3 起审核员不再默认拥有）。
2. 新增 **`UserSitePermission(user_id, site_id, can_review, can_publish, unique(user_id,site_id))`**，把内容编辑/审核**收窄到指定站点**（镜像 `UserColumnPermission`）。
3. 访问判定 `can_access_site(user, site_id)`：
   - 超管（`is_super`）全通；
   - 编辑/审核员需有对应 `UserSitePermission` 行，或既有全局 `content_manage:all_columns` + 站点绑定；
   - 只读查看员默认全站点可见（按现网语义）。
4. 后台切换站点时按 `can_access_site` 过滤可见站点列表。
5. 审计条目落 `site_id`，超管可跨站点检索审计日志。

---

## 九、周边子系统（逐一给方案）

- **缓存**：`_try_cache` 键、浏览量缓存、`Setting` 请求缓存均按 `site_id` 命名空间隔离；TTL 取站点化 `cache_ttl_*`。
- **搜索**：索引文档写入 `site_id` 字段，查询时按当前站点过滤（Meilisearch 用 filterable attribute；Whoosh 存字段过滤；SQL 兜底加 `site_id` 条件）——单引擎、结果按站隔离。
- **Sitemap / robots**：`collect_sitemap_urls` 按站点生成，各子域/域名各自 `/sitemap.xml` 仅含本站栏目/文章；robots 同理。
- **备份**：单库 dump 天然覆盖全部站点；后续可加「按站点导出」（增强项，非 M1–M4 必需）。
- **i18n 交互**：站点与语言**正交**——一个站点自身可多语言。`t_field()` 逻辑不变（对象已站点化），只需保证**先解析站点、再解析语言**（`select_site()` 在 `select_locale()` 之前执行）。默认站点（0）即现网，i18n 配置不变。
- **统计代码（analytics 插件）**：按站点键读取（站点化 Setting），各站点注入各自的统计代码。

---

## 十、插件 SDK（影响面收敛）

插件各自 `db.create_all()` 建表（见 `plugins/form/models.py` 约定），不能只靠核心迁移。提供统一接入：

- 插件内容模型直接 **`class Form(SiteScopedMixin, db.Model)`**，一行获得 `site_id`（`from app.plugin_api import SiteScopedMixin`）。
- `plugin_api` 暴露 **`current_site_id()`**、**`site_filter(query, model=None)`**（模型无 `site_id` 列时原样返回）与 `SiteScopedMixin` / `DEFAULT_SITE_ID`；文档约定「内容查询按当前站点过滤、slug 类唯一约束改 `(site_id, slug)`」。
- 插件**各自**加迁移补 `site_id`（沿用核心幂等 `_table_exists` 守卫范式）；内置插件（form / friend_link / product / recruit / banner / member 等）已随核心 `0012` 一并处理。
- 插件后台管理页需按当前站点过滤列表（插件开发者按 SDK 文档自行处理；SDK 提供 `site_filter(query)` 辅助）。

---

## 十一、数据迁移方案（Alembic 迁移 `0012_v3_2_0_sites.py`）

沿用 `0001` 基线 + 幂等守卫 + `ensure_*` 回填范式：

1. `CREATE TABLE sites`，**插入默认站点 id=0**（`is_default=True`，name 取现 `Setting.site_name`，domain 留空表示「兜底站点」）。MySQL 需会话级 `NO_AUTO_VALUE_ON_ZERO`。
2. 给 `columns` / `articles` / `fragments` / `settings` / `members` 加 `site_id`（`NOT NULL, server_default='0'`）→ 存量行自动归 0。
3. `articles.site_id` 由 `columns.site_id` 回填（join update，仿 `Article.ensure_status_column`）。
4. **唯一约束改造**：`columns.slug`、`fragments.slug`、`settings.key`、`members.username` → `(site_id, slug)` / `(key, site_id)` / `(site_id, username)`；内置插件 slug（`forms.slug`、`friend_links.slug` 等）同步。
5. 建索引：`columns(site_id, slug)`、`fragments(site_id, slug)`、`articles(site_id)`、`settings(key, site_id)`、`members(site_id, username)` 等。
6. `audit` 加 `site_id`（可空/默认 0）。
7. 插入全局 Setting 行 `member_scope = 'shared'`（site_id=0）。
8. `downgrade()` 对称回滚（删列、复原唯一约束、删表、删 Setting 行）。

> 唯一约束改造在 SQLite 上需「建新表→拷数据→删旧表→改名」流程；MySQL/PostgreSQL 可 `ALTER TABLE ... DROP CONSTRAINT / ADD CONSTRAINT`。迁移内按 `db_type` 分支处理。

---

## 十二、兼容性保证（最关键）

- **单站点部署零感知**：解析器对唯一域名恒返回 0；所有查询 `site_id=0`；现有 slug/配置/会员行迁移后 `(·,0)` 不变；**URL、行为、SEO 全部不变**。
- **渐进激活**：只有创建第 2 个站点时才进入多站点路径；默认站点继续复用现有全局配置行（现 `(·,0)`）。
- **可灰度**：解析器与 `site_id` 过滤对 `site_id=0` 是恒等操作，可独立先行落地、验证无回归后再开放站点 CRUD。
- **会员向后兼容**：`member_scope` 默认 `shared`，存量会员 `site_id=0`，登录/会话行为与现网一致。

---

## 十三、分阶段落地路线图

| 阶段 | 内容 | 回归风险 |
| --- | --- | --- |
| **M1** | `sites` 表 + `site_id` 列（columns/articles/fragments/settings/members）+ 迁移 `0012` + 解析器（恒返回 0）+ 查询过滤 | 极低（恒等变换） |
| **M2** | 后台站点 CRUD + 切换器 + RBAC（`site:manage` / `UserSitePermission`） | 中（权限路径） |
| **M3** | 站点化 settings/theme/sitemap/search/缓存命名空间 + 会员 `member_scope` 开关 | 中 |
| **M4** | 插件 SDK（`SiteScopedMixin` + `plugin_api.current_site_id()`）+ 内置插件改造 + 文档 | 中 |

每阶段可独立合并、可回滚（迁移 `downgrade` 对称）。

---

## 十四、落地记录（v3.2.0）

| 里程碑 | 落地内容 | 关键文件 |
| --- | --- | --- |
| M1 | `sites` 表 + `site_id` 维度列（columns/articles/fragments/settings/members/audit_logs）+ 迁移 `0012` + 解析器 | `app/models/site.py`、`app/sites.py`、`migrations/versions/0012_v3_2_0_sites.py` |
| M2 | 后台站点 CRUD / 切换器 / `site:manage` / `UserSitePermission` | `app/admin/system/sites.py`、`app/models/rbac.py`、`admin/base.html` |
| M3 | 站点化 settings/theme/sitemap/search/缓存命名空间 + `member_scope` | `app/models/setting.py`、`app/utils/themes.py`、`app/utils/search.py`、`app/frontend/views.py` |
| M4 | 插件 SDK（`current_site_id()` / `site_filter()` / `SiteScopedMixin`）+ 内置插件改造 + 文档 | `app/plugin_api.py`、`plugins/{form,friend_link,product,recruit,banner,member}/`、`docs/PLUGIN_DEV.md` |

实现与设计的三处偏差：

1. **迁移编号**为 `0012`（v3.1.5 已占用 `0011`），不是文中的 `0010`。
2. **搜索后端**现为 Tantivy（主）/ Meilisearch / SQL 兜底，不存在 Whoosh；Tantivy 通过 schema 版本标记 `.schema_version` 检测到旧索引后自动全量重建。
3. **SQLite 唯一约束**通过「唯一索引」实现（`CREATE UNIQUE INDEX`），避免 `ALTER TABLE ADD CONSTRAINT` 不支持的问题；MySQL/PostgreSQL 走复合唯一约束。

测试：`tests/test_sites_v320.py`（15 项）覆盖站点解析、后台切换、slug 跨站复用、栏目/文章 API 隔离、站点化配置、全局键、站点关闭 503、站点 CRUD 权限、账号站点权限绑定与审计按站点筛选。

## 十五、缺陷修复（v3.2.1）

v3.2.0 第三方测试报告的缺口已在 v3.2.1 闭环，实现口径如下（回归测试见 `tests/test_sites_v321.py`）：

| 问题 | 修复口径 | 关键文件 |
| --- | --- | --- |
| 站点权限可被 `?site=` 绕过 | 解析层写会话前校验 `can_access_site()`；`admin_bp` 统一 `before_request` 校验当前站点（GET 越权回退、显式越权与写请求 403），插件后台自动继承 | `app/sites.py`、`app/admin/__init__.py` |
| 未绑定账号的兼容 | 无任何 `UserSitePermission` 行 → 全站可见（升级不锁定存量编辑）；有绑定行 → 仅绑定站点 | `app/sites.py` |
| `status=closed` 覆盖不全 | 关闭校验提升为 app 级 `before_request`：前台/API/插件前台蓝本统一 503；API 返回 JSON、`healthz` 固定 200、后台与根文件豁免 | `app/frontend/views.py`、`app/__init__.py` |
| 独立会员会话跨站 | `member_scope=isolated` 时 `current_member()` 校验会员站点，不一致清会话 | `plugins/member/scope.py`、`plugins/member/security.py` |
| 站点 SEO 不生效 | `_seo()` 与 `/api/v1/site` 采用「站点 SEO → 全局设置」回退链 | `app/frontend/views.py`、`app/api/views.py` |
| `0012` 降级半回滚 | 降级任何 DDL 前预检跨站重复 `slug/key/username`，冲突即中止并输出清单 | `migrations/versions/0012_v3_2_0_sites.py` |
| P3 边界项 | `accessible_sites` 批量化、`subdomain` 唯一（迁移 `0013`）、域名 DNS label 校验、`sort_order` 表单校验、删站内容检查、`site_url()` 子域支持、`b.localhost`、JWT 配置延后读取 | 见 CHANGELOG v3.2.1 |

## 十六、缺陷修复（v3.2.2）

v3.2.1 潜在威胁报告的 11 项缺口已在 v3.2.2 闭环：v3.2.1 解决「查询带站点」，v3.2.2 补齐「表结构与写入带站点」（回归测试见 `tests/test_sites_v322.py`，迁移 `0014`）：

| 问题 | 修复口径 | 关键文件 |
| --- | --- | --- |
| 教程跨站可见/可改（P0） | 两表补 `site_id`，`slug` 改站内唯一；前台/后台/模板函数/构建器组件按站过滤；演示数据只清当前站 | `plugins/tutorial/models.py`、`plugins/tutorial/*.py` |
| 页面构建跨站读写（P0） | `builder_pages` 补 `site_id`，唯一约束改 `(site_id, scope, column_id)`；服务层按站查询，跨站编辑器 404；卸载检查仍跨站扫描 | `app/models/builder.py`、`app/builder/service.py`、`app/admin/builder/__init__.py` |
| 上传跨站复用（P0） | `uploaded_files` 补 `site_id` + `(site_id, content_hash)` 索引；去重按站；新路径 `uploads/site{N}/...` | `app/models/upload.py`、`app/utils/uploads.py` |
| 删站检查遗漏（P1） | 补充教程/构建/上传索引/OAuth 表计数 | `app/admin/system/sites.py` |
| 会员删除无站点校验（P1） | 删除与编辑一致校验所属站点 | `plugins/member/admin.py` |
| OAuth 跨站串号（P1） | `member_oauths` 补 `site_id`，唯一约束改 `(site_id, provider, openid)`，口径走 `scope_site_id()` | `plugins/member/models.py`、`plugins/member/frontend_routes.py` |
| 备份/监控权限过宽（P1） | 收敛为超管或 `site:manage`，后台守卫加平台入口豁免 | `app/admin/system/backup.py`、`app/admin/__init__.py` |
| 缓存失效键不匹配（P1） | 按 `frontend/site{N}/*` 前缀失效，不支持模式删除时回退整体清空 | `app/utils/helpers.py` |
| 浏览量全局单键（P1） | 键改 `article:viewed:pending:site{N}`，按站合并并过滤文章 | `app/frontend/views.py` |
| 插件 SQL 搜索无站点条件（P1） | `sql_search` 增可选 `site_id`，上层签名探测兼容旧插件 | `app/utils/search.py`、`plugins/product/search.py`、`plugins/recruit/search.py` |
| 平台入口被站点守卫误拦（P2） | 站点/插件/存储/迁移/翻译/统计/备份/监控入口豁免 | `app/admin/__init__.py` |
| 后台域名登录不落对应站点 | 后台未显式选择站点时也按 Host 解析（domain → 子域），默认管理当前域名站点；显式切换仍以 session 为准；无权站点回退可访问站点 | `app/sites.py` |

## 十七、角色体系站点化（v3.2.3）

用户管理的分组重新规划：新增「站点管理员」，内容审核员/内容编辑/只读查看员也绑定到具体站点。迁移 `0015`，回归测试见 `tests/test_rbac_sites.py`。

### 17.1 角色边界

| 角色 | 范围 | 关键权限 |
| --- | --- | --- |
| 超级管理员 `super_admin` | 整个系统 | 全部权限（`is_super` 兜底），含 `site:manage`、`system:backup` |
| 站点管理员 `site_admin` | 指定站点 | 站点内全部后台功能：设置、用户、审计、栏目、内容、页面构建、表单；**不含** `site:manage` / `system:backup` |
| 内容审核员 `content_auditor` | 指定站点 | 审核/发布/归档/回滚、栏目、页面构建发布；v3.2.3 移除全局 `site:manage` |
| 内容编辑 `content_editor` | 指定站点 | 创建/编辑/提交审核、页面构建草稿 |
| 只读查看员 `readonly_viewer` | 指定站点 | 只读查看、表单数据与审计日志列表 |

### 17.2 数据模型

- `user_roles.site_id`：`NULL` = 平台级/全局角色（兼容存量与超管），非空 = 只在指定站点生效。
- 唯一约束：`(user_id, role_id, site_id)`，支持一人多站多角色。
- `User.has_permission(perm_code, site_id=None)`：传 `site_id` 时只认「全局角色 + 该站点角色」；不传时按全部角色判断（菜单可见性）。

### 17.3 站点可见性

- `can_access_site(user, site_id)`：超管/`site:manage` 全通；命中 `user_roles.site_id` 或 `UserSitePermission` 行即可访问；存量全局角色（`site_id IS NULL`）在无显式站点绑定时全站可见，有绑定时以绑定为准。
- `accessible_sites(user)`：平台管理员 → 全部；站点级角色 → 角色所属站点 ∪ `UserSitePermission`；存量全局角色 → 全部（有绑定时取绑定）。

### 17.4 账号管理边界

- 平台管理员（超管或 `site:manage`）：可查看全部账号，分配全局角色与任意站点角色。
- 站点管理员：账号列表只显示「角色全部落在自己可管理站点、且无全局角色」的账号；新增/编辑时只能选择自己管理的站点与四种站点角色；不能授予超管或越权站点。
- 角色与权限配置页（`/admin/roles`）仅平台管理员可用，站点管理员访问返回 403。
- 插件安装/启停/卸载（`/admin/plugins`）、备份恢复、系统监控与数据库迁移属于平台级功能，站点管理员访问返回 403。
- 站点管理员保存账号时，不会删除其看不到的其他站点授权（范围外 `user_roles` 行保持不动）。
