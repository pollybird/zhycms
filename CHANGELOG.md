# 更新日志（Changelog）

本项目的所有显著变更都记录在本文件中。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。

## [2.3.0] - 2026-09-01

**国际化 + 统计插件 + 表单插件化**版本。**无数据库结构变更，v2.2.x 直接覆盖代码即可升级**；自定义表单由核心转为内置插件（表名/路由/设置键/审计模块代码不变，老站数据无缝保留），国际化默认关闭、不改变现有站点行为。

### Added

- **国际化（i18n，Flask-Babel）**：
  - 中英文自由切换，前台 + 后台全站生效；新增语种仅需追加翻译目录并编译（`pybabel init/update/compile`），无需改代码。
  - Locale 选择优先级：URL `?lang=xx`（一次性，写回 session）→ session → cookie → `Accept-Language` 自动匹配 → 默认语种 `zh` 兜底。
  - 后台「系统设置 → 国际化」可视化配置页（权限 `system:settings`）：总开关、默认语种、可用语种清单，改动写入审计。
  - 后台顶栏与前台主题 `base.html` 语言切换器（`available_locales()` / `current_locale()` 全局函数）；未启用时切换器自动隐藏。
  - 切换路由 `/admin/set-locale`（归属核心）；核心模板（后台 base 与全部主题 base 等界面文案）已标记 `_()` 并提供英文翻译（`app/translations/en/LC_MESSAGES/messages.po`）。
  - 默认关闭（`i18n_enable=0`）：关闭时全站按中文渲染，与 v2.2.0 行为完全一致；内容数据（栏目名/文章标题等动态数据）不在翻译范围，仅界面文案国际化。
- **统计代码插件 `analytics`（官方内置）**：
  - 后台「插件管理」独立配置页（权限 `analytics:manage`）：百度统计 / Google Analytics 4 / 站长工具（cnzz、51la 等）/ 自定义 head 与 body 代码，均为直接粘贴官方代码片段，保存即生效、无需重启。
  - 前台注入采用「插件 Jinja 全局函数 + 主题注入点」模式：主题 `base.html` 的 `</head>` 前调用 `{{ analytics_head()|safe }}`、`</body>` 前调用 `{{ analytics_body()|safe }}`，4 套内置主题均已接入；禁用插件时函数返回空串、模板零报错。
  - 仅注入前台页面，不注入后台管理页（避免后台流量污染统计）；设置存 Setting 键值（`analytics_*`），不建表、零迁移；操作写入审计（module=`analytics`）。

### Changed

- **自定义表单插件化（`form`，官方内置，v2.3.0 起由核心功能转为插件）**：
  - 新增 `plugins/form/`（manifest / 模型 / 后台路由 / 前台提交路由 / 通知 / 演示数据钩子 / 管理页模板），后台路由挂核心 `admin_bp`，路径与端点名与核心版完全一致（`/<admin>/forms`）；前台提交地址 `/form/<slug>` 不变。
  - **迁移四原则**（沿用 v2.2.0 友情链接迁移）：表名不变（`forms`/`form_fields`/`form_submissions`/`form_submission_values`）、审计模块代码不变（`form`/`form_submission`）、后台路由路径不变、通知设置键不变——旧表单数据、提交记录、历史审计日志、邮件/企业微信通知配置全部无缝保留。
  - 权限点改为插件自有 `form:view`/`form:manage`（沿用核心时代策略）；提交通知由插件复用核心通用传输层 `app/utils/notify_utils.py`（邮件/企业微信发送实现保留在核心）。
  - 核心移除：`app/models/form.py`、`app/admin/form.py`、`app/frontend/views.py` 表单提交视图、后台侧边栏固定「自定义表单」菜单项、演示数据内置表单生成（改由插件 `generate_demo_data` 钩子生成）。
  - **老站升级自动迁移**：v2.2.x 升级后首次启动自动启用表单插件一次（`form_plugin_migrated` Setting 标记，新装站点初始化时写入、不触发），无需手工操作。
- `notify_utils.py` 解耦为通用传输层：发送实现（SMTP 邮件/企业微信 Webhook）保留核心，业务触发移至插件，供各插件复用。
- 仪表盘「自定义表单统计」卡片随插件门控懒加载，禁用插件后自动隐藏。

### Fixed

- 统计插件管理页模板路径：插件注册前台蓝图（即使无前台路由）将自身 `templates/` 目录加入 Jinja 搜索路径，杜绝 `TemplateNotFound`。
- 表单插件后台菜单图标改用 Font Awesome 5 solid 图标（`fas` 前缀），并移除核心模板中硬编码的重复菜单。

## [2.2.0] - 2026-08-31

**插件优先架构**大版本。**无数据库结构变更，v2.1.x 直接覆盖代码即可升级**；插件模型表随 `db.create_all()` 自动补齐，插件启停仅改 Setting 值、无需重启。

### Added

- **主题管理机制（Theme Manager）**：
  - 新增后台「主题管理」页（系统设置子菜单，权限 `system:settings`）：列表展示名称/版本/作者/说明/模板数/产品列表支持徽标/状态（使用中·绿色高亮 / 未启用 / 模板不完整·标红含缺失模板明细）。
  - 主题压缩包上传（`.zip / .tar.gz / .tgz`）：8 步校验——扩展名白名单、压缩包完整性、路径穿越双重拦截（预检 + `_safe_join`）、符号链接静默跳过、manifest 合法性 + slug 格式正则、必备模板全量存在、形态 A（单目录）/ B（平铺）自动归一化、内置主题禁止覆盖 + 同名自定义主题先删后传；全程使用临时目录，任何失败不写入 `themes/`，finally 彻底清理。
  - 一键启用：启用前强检必备模板（`index/list/article/page/base/404/500.html` + manifest `template_required` 额外声明），缺失拒绝并给出补齐指引；启用动作写入 `OP_CONFIG_CHANGE` 审计；前台即时切换、无需重启。
  - 主题兜底：`get_active_theme()` 引用的主题目录不存在或模板不全时自动回退 `default`，杜绝前台空白页。
  - 4 套内置主题 manifest 标记 `builtin: true`，禁止删除与覆盖。
- **主题静态资源目录（css / js / images / fonts）**：每套主题目录下新增 `css/`、`js/`、`images/`、`fonts/` 独立目录，`base.html` 中的内联 `<style>` 全部移至 `css/style.css`；新增前台资源路由 `GET /themes/<主题>/css|js|images|fonts/*`（slug 正则 + 仅放行四个资源子目录 + 路径穿越拦截 + `Cache-Control` 缓存头），样式、脚本、图片、字体随主题目录分发，manifest 与模板文件不对外暴露。
- **插件压缩包上传**：后台「插件管理」支持直接上传开发好的插件压缩包（`.zip / .tar.gz / .tgz`）解压至 `plugins/`；8 层顺序校验（扩展名白名单 → 压缩包完整性 → 路径穿越拦截 → 符号链接处理 → 插件根识别 → 必备文件 `manifest.json`/`__init__.py` → manifest 合法性 → 目标目录存在性），非法包整体拒绝；成功后写入 `OP_UPLOAD` 审计。
- **插件 / 主题打包下载**：两个管理页操作列新增「下载」按钮，将插件/主题目录打包为 zip（单目录形态，与上传校验完全兼容）下载；内置、启用中、加载失败的插件与主题均可下载；下载动作写入 `OP_EXPORT` 审计（含版本/文件数/大小）。下载包可在其他站点直接重新上传复用。
- **插件 / 主题卸载删除（危险操作二次确认）**：
  - 列表操作列新增「卸载 / 删除」按钮：内置（灰显提示原因）、启用中（灰显要求先禁用/切换）不可操作；其余点击后弹出红色警告模态框，告知后果并要求输入图形验证码确认（验证码一次性消费防重放，独立于登录验证码，图片点击可刷新）。
  - 卸载即物理删除 `plugins/<slug>/`（或 `themes/<slug>/`）目录：slug 正则校验防穿越 → 内置拒绝 → 启用中拒绝 → 删除 → 审计（`OP_DELETE`）。
  - 插件卸载同步移除运行期注册表并清理 `sys.modules` 缓存：菜单/列表/sitemap/审计聚合立即消失，同进程重新上传同名包即可恢复；**数据表与数据保留**。
  - 主题删除后若为当前启用主题系统自动兜底回退 `default`（删除前已双重拦截启用中主题）。
- **插件机制（Plugin First Architecture）**：
  - `plugins/<slug>/` 目录 + `manifest.json` + `PluginBase` 基类，零侵入扩展后台页面、前台路由/模板函数、数据表、只读 API、后台菜单、sitemap、演示数据钩子、审计筛选。
  - 运行时门控 `site_settings.enabled_plugins`；启用自动种子权限/预设角色授权/建表；禁用仅移除清单、不删数据、前端隐身。
  - 后台「插件管理」页：发现清单、启停、导入错误标红、导入错误提示。
  - 初始化向导新增「功能插件」步骤，默认勾选**轮播图 + 产品展示 + 友情链接**（可取消）。
- **轮播图插件 `banner`（官方内置）**：分组/排序/链接/开关/封面；后台管理页 + 审计；`banner_items()` 模板函数 + `banner/hero_carousel.html` partial；四套主题首页自动接入；`GET /api/v1/banners/<slug>`；制造业/服务业演示数据各 3 张。
- **产品展示插件 `product`（官方内置）**：产品模型归属栏目树（复用授权/伪静态/SEO/缓存），相册有序可拖拽、规格参数分组 JSON；动态 + 伪静态详情路由；4 套主题 `list_product.html` 列表模板；制造业首页优先展示产品卡片；`GET /api/v1/columns/<slug>/products` + `GET /api/v1/products/<id>`；制造业演示数据 2 子栏目共 6 产品附相册/规格；sitemap 收录 2000 条内启用产品。
- **友情链接插件 `friend_link`（官方内置，v2.2.0 起由核心功能转为插件）**：
  - 新增 `plugins/friend_link/`（manifest / 模型 / 后台路由 / 前台模板函数 / 演示数据钩子 / 管理页模板），后台路由挂核心 `admin_bp`，路径与端点名与核心版完全一致（`/<admin>/friend-links`、`admin.friend_link_*`），升级后书签与习惯零变化。
  - 权限点改为插件自有 `friend_link:manage`（沿用核心时代策略：仅超级管理员默认可管理，可在「角色权限」自行授权）；操作全部写入审计（module=`friend_link`，核心版原本未落审计）。
  - 前台模板改用插件全局函数 `friend_links()`（核心自动包裹启用守卫，未启用返回 `[]`），default / blue / manufacturing / service 四套主题首页已同步切换，禁用插件时友链区块自动隐藏、页面零报错。
  - 核心移除：`app/models/friend_link.py`、`app/admin/friend_link.py`、首页视图注入、后台侧边栏固定菜单项、审计核心下拉项、演示数据 `_init_friend_links()`；友情链接演示数据改由插件 `generate_demo_data` 钩子生成（幂等，内容沿用核心演示数据）。
  - **老站升级自动迁移**：v2.1.x 升级后首次启动自动启用友情链接插件一次（`friend_link_plugin_migrated` Setting 标记，新装站点在初始化时写入、不触发）；旧 `friend_links` 表结构不变、数据无缝保留，历史审计日志经插件 `audit_modules` 声明（module 代码同为 `friend_link`）自动正常翻译。
- **REST 内容 API（核心）**：`/api/v1` 蓝本、统一 `{code,message,data,meta}` 包、`api_cache` 装饰器、核心 4 个端点（栏目树/栏目详情/栏目文章列表/文章详情）、`api_enable` 总开关 + `api_token` 鉴权 + `api_cors_origins` CORS；后台「内容 API」可视化配置页与审计留痕。
- **sitemap 聚合**：`collect_sitemap_urls()` 聚合启用插件 URL 到 `sitemap.xml`。
- **审计模块聚合**：`plugin_audit_modules()` 把启用插件审计模块拼入筛选下拉与列表徽标翻译。

### Changed

- **初始化向导行业演示数据与官方插件联动**：选择任一行业演示数据（制造业/服务业）时，**轮播图（banner）、友情链接（friend_link）自动启用**，无需勾选；选择**制造业**演示数据时，**产品展示（product）**同样自动启用——制造业演示数据的产品页依赖该插件（多图相册/规格参数/伪静态详情），演示钩子自动将「精密零部件 / 自动化设备」子栏目切换为 `list_product` 列表模板。不生成演示数据时仍按向导勾选启用；向导页补充联动规则提示。
- **初始化轮播数据改由 banner 插件生成**：制造业/服务业演示数据不再写入 `home_banner_1/2/3` 碎片，首页轮播统一由 banner 插件演示钩子生成 `home-hero` 分组 3 张图；行业主题中的碎片轮播兜底逻辑保留，老站升级后行为不变。
- 初始化向导：「演示数据」后新增「功能插件」复选步骤，安装结果提示随启用插件变化。
- **网站设置页前台主题设置项迁移**：移除原主题下拉框，替换为引导卡片（展示当前启用主题并链接到「主题管理」）；主题切换、上传、删除统一在「主题管理」完成。
- 制造业主题首页：产品插件启用时优先 `product_latest()`，否则回退原文章卡片。
- 4 套主题（default/blue/manufacturing/service）新增 `list_product.html` 栏目列表备选模板。

### Fixed

- 后台插件/主题管理页脚本块误用 `{% block scripts %}`（父模板不存在该块）导致整个页面脚本未输出，「卸载 / 删除」确认弹窗点击无反应；统一修正为 `{% block js %}`。

## [2.1.1] - 2026-08-30

配置与治理完善版本，**无数据库结构变更**，v2.1.0 直接覆盖代码即可升级。

### Changed

- **环境变量前缀统一为 `ZHYCMS_`**（与项目名一致）：`ZHYCMS_ENV`、`ZHYCMS_SECRET_KEY`、`ZHYCMS_DB_URI`；旧前缀 `ZHOCMS_*`（v2.1 前的历史拼写差异）仍被识别作为兼容回退，将在未来主版本移除。部署脚本/systemd 配置建议改用新前缀。
- **初始化向导数据库选项重排**：MySQL/PostgreSQL（生产推荐徽标）置顶，SQLite 标注「仅开发/测试」；顶部新增 SQLite 并发写入风险提示。

### Added

- **项目治理文件**：`CONTRIBUTING.md`（贡献指南）、`CODE_OF_CONDUCT.md`（行为准则）、`SECURITY.md`（安全策略）、`CHANGELOG.md`（变更日志）。
- **README 生产数据库提示**：环境要求明确标注「SQLite 仅用于开发/测试，生产环境请使用 MySQL 5.7+ 或 PostgreSQL 12+」，wiki 手册数据库选择章节同步。

### Improved

- **仪表盘「最近操作审计」详情人性化**：`audit_detail` 过滤器新增 `compact` 紧凑模式（单行摘要、最多 3 项、"；"分隔、超 70 字截断），仪表盘最近操作区块与审计日志页共用同一套中文翻译与 ID→名称映射，不再显示原始 JSON。

## [2.1.0] - 2026-08-29

v2.0 的体验优化与缺陷修复版本，**无数据库结构变更**，v2.0 直接覆盖代码即可升级。

### Fixed

- 后台用户列表不显示：v2.0 中添加用户后列表恒显示「暂无用户」（模板取值字段错误）；同时角色展示改用预加载数据，消除逐行查询（N+1）。
- 后台菜单按权限隐藏：当前角色无权访问的菜单项直接隐藏（此前显示但点击后报 403）；内容编辑角色可正常进入栏目列表页浏览，敏感操作仍受权限校验。
- 审计日志记录健壮性：定时任务、命令行脚本等无请求上下文场景写审计不再因 `request`/`current_user` 访问异常而静默丢失。
- 升级迁移脚本两处回填缺陷：SQL 优先级缺括号导致隐藏文章可能被误置为「已发布」；`ALTER ADD COLUMN DEFAULT` 立即填充默认值导致 `is_enabled` 映射失效（现以 `schema_migrations` 版本记录保证幂等且不覆盖运行期数据）。

### Changed

- 审计日志详情人性化：从原始 JSON 改为中文可读描述（键名/配置项/操作类型翻译、状态与开关值语义化、`(旧值, 新值)` 与 `changed` 嵌套渲染为「旧值 → 新值」、角色/栏目 ID 显示名称、超长截断、HTML 转义防 XSS）。
- 伪静态列表分页：开启伪静态后列表分页使用 `/{slug}-{页码}.html` 格式，新增 `frontend_pager_url` 模板助手，内置 4 套主题 8 个列表模板全适配；第 1 页自动规范化，旧动态 URL `?page=` 向后兼容。
- 版本号集中管理：新增 `Setting.CMS_VERSION` 常量并注入全模板，后台页脚版本一处维护。
- 文案修正：后台安全页移除 v1.1 遗留的「修改后需重启服务才能生效」提示（v2.0 起保存后即时生效）。

## [2.0.0] - 2026-08-29

面向「企业级安全、可控、可运维」的大版本升级，新增八大模块。**自 v1.1 升级必须运行 `scripts/upgrade_v2.py` 迁移脚本**（见 [UPGRADE.md](UPGRADE.md)），仅覆盖代码无法完成迁移。

### Added

- **RBAC 权限体系**：角色/权限点/用户多角色管理，栏目级授权（all_columns/all_authors 授权优先级），预设 4 角色与 17 权限点。
- **审计日志**：全后台操作留痕（登录/增删改/配置变更/备份恢复等），支持筛选、导出、保留天数策略与定时清理。
- **内容工作流**：文章状态机（草稿/待审核/已驳回/已发布/已归档），审核通过/驳回，版本快照与一键还原，定时发布。
- **备份与恢复**：mysqldump/JSON/PGDump 三种备份方式，一键恢复（自动处理连接池持锁），备份保留策略，gzip 完整性校验。
- **登录安全加固**：密码错误防暴破锁定（可配置次数/时长）、图形验证码、异地登录提醒、后台地址前缀即时切换（无需重启）。
- **上传安全与图片优化**：MIME + 后缀双重校验（拦截伪装脚本）、SHA-256 内容去重（引用计数）、Pillow 压缩与缩略图、上传索引表。
- **表单消息通知**：提交后邮件/企业微信双渠道推送，全局开关静默安全，完整 SMTP/企业微信配置。
- **SEO 与站点性能**：伪静态开关（`/{slug}.html` 与 `/{slug}-{页码}.html`）、sitemap 自定义更新频率/优先级、robots 可视化编辑、页面缓存（Flask-Caching）、图片默认 ALT 批量填充。
- **升级迁移工具**：`scripts/upgrade_v2.py` 幂等迁移脚本 + `UPGRADE.md` 升级迁移指南（手工 SQL 兜底、验证清单、回滚方案）。

## [1.1.0] - 2026-08-17

### Added

- 文章新增支持从 Word 文档（.docx）导入正文。

### Changed

- 版本号升级至 1.1.0，放宽依赖版本约束。
- 前台底部增加「Powered by ZhyCMS」链接。

## [1.0.0] - 2026-08-10

### Added

- 首个正式版本：栏目（列表/单页）、文章（富文本 CKEditor 全功能汉化版）、自定义字段（单页直录）、碎片管理、友情链接、自定义表单、多主题模板。

### Fixed

- 修复中文文件名上传被误判为类型不允许。
- 修复带路径参数路由（如文章列表）分页链接 BuildError。
- 修复单页栏目自定义字段内容录入问题。

[Unreleased]: https://gitee.com/pollybird/zhycms/compare/v2.3.0...HEAD
[2.3.0]: https://gitee.com/pollybird/zhycms/compare/v2.2.0...v2.3.0
[2.2.0]: https://gitee.com/pollybird/zhycms/compare/v2.1.1...v2.2.0
[2.1.1]: https://gitee.com/pollybird/zhycms/compare/v2.1.0...v2.1.1
[2.1.0]: https://gitee.com/pollybird/zhycms/compare/v2.0...v2.1.0
[2.0.0]: https://gitee.com/pollybird/zhycms/compare/a717ad4...v2.0
[1.1.0]: https://gitee.com/pollybird/zhycms/compare/v1.0...a717ad4
[1.0.0]: https://gitee.com/pollybird/zhycms/releases/tag/v1.0
