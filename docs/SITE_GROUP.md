# 站群模式（多站点 / Site Group）设计方案

> 状态：**设计敲定（含四项产品决策）**，待按 M1–M4 分阶段落地。
> 适用版本：v3.2.0（拟）。本文是站群模式的**设计依据**，后续拆 issue / 实现 M1 均以本文为准。

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
    site = db.relationship('Site', lazy='joined')
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

1. 新增权限点 **`site:manage`**（站点管理：增删改站点、配置域名），授予超管/审核员。
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

- 插件内容模型直接 **`class Form(SiteScopedMixin, db.Model)`**，一行获得 `site_id`。
- `plugin_api` 暴露 **`current_site_id()`** 与 `SiteScopedMixin`；文档约定「内容查询按当前站点过滤、slug 类唯一约束改 `(site_id, slug)`」。
- 插件**各自**加迁移补 `site_id`（沿用核心幂等 `_table_exists` 守卫范式）；内置插件（form / friend_link / product / job / analytics 等）随核心 `0010` 一并处理。
- 插件后台管理页需按当前站点过滤列表（插件开发者按 SDK 文档自行处理；SDK 提供 `site_filter(model)` 辅助）。

---

## 十一、数据迁移方案（Alembic 新迁移 `0010_v3_2_0_sites.py`）

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
| **M1** | `sites` 表 + `site_id` 列（columns/articles/fragments/settings/members）+ 迁移 `0010` + 解析器（恒返回 0）+ 查询过滤 | 极低（恒等变换） |
| **M2** | 后台站点 CRUD + 切换器 + RBAC（`site:manage` / `UserSitePermission`） | 中（权限路径） |
| **M3** | 站点化 settings/theme/sitemap/search/缓存命名空间 + 会员 `member_scope` 开关 | 中 |
| **M4** | 插件 SDK（`SiteScopedMixin` + `plugin_api.current_site_id()`）+ 内置插件改造 + 文档 | 中 |

每阶段可独立合并、可回滚（迁移 `downgrade` 对称）。
