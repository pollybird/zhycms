# 更新日志（Changelog）

本项目的所有显著变更都记录在本文件中。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。

## [2.5.0] - 2026-09-06

**内容级多语言（i18n 2.0）+ Redis 缓存与 Session**，企业出海刚需版本。无破坏性变更，覆盖代码 + 执行迁移即可升级。

### Added

- **内容级多语言（i18n 2.0）**：文章/栏目/碎片支持多语言版本存储。
  - 新增 `article_translations`、`column_translations`、`fragment_translations` 三张翻译关联表（Alembic 迁移 `0005`）。
  - 主表保留默认语言字段（冗余），翻译表存非默认语言；查不到翻译时 fallback 默认语言。
  - 前台模板新增 Jinja 全局 `t(obj, field)`，6 套主题共 44 个模板的内容字段已接入。
  - 后台文章/栏目/碎片编辑页新增「多语言版本」Tab，按语种切换录入翻译。
  - `slug` 不随语言变化，URL 保持稳定；语言切换沿用 `?lang=xx` + session 机制。
  - 页面缓存键加入 locale，不同语言互不串扰。
- **Redis 缓存后端 + 服务端 Session**：
  - 配置 `REDIS_URL` 环境变量后，Flask-Caching 切 RedisCache、Flask-Session 存 Redis，支撑多实例负载均衡。
  - 未配置 `REDIS_URL` 时自动回退 SimpleCache + Cookie Session，单机部署零依赖。
  - `docker-compose.yml` 新增可选 `redis` profile（redis:7-alpine + 256MB LRU），`install.sh` 新增 Redis 交互选项。

### Changed

- 版本号 `CMS_VERSION` 由 `2.4.2` 升级为 `2.5.0`。
- `requirements.txt` 新增 `redis>=5.0,<6.0`、`Flask-Session>=0.8,<1.0`。

### Fixed

- 修复前台文章详情页浅拷贝对象丢失 `translations` 关系导致多语言翻译无法渲染的问题。
- 修复 `t_field` 依赖 babel 缓存 locale 导致 `?lang=` 切换不生效的问题，改为直接调用 `select_locale()`。

### 升级说明

- v2.4.x 站点：`git pull` → `pip install -r requirements.txt` → `flask db upgrade` → 重启应用。
- 启用多语言：后台「系统设置 → 国际化」开启，配置默认语言与可用语种，编辑内容时在「多语言版本」Tab 录入翻译。
- 启用 Redis：Docker 部署在 `install.sh` 中选择启用 Redis；源码部署设置 `REDIS_URL` 环境变量。
- 未启用 i18n / Redis 的站点，行为与 v2.4.2 完全一致。

## [2.4.2] - 2026-09-06

**安全加固 + 部署修复版本**，针对 v2.4.1 安全复检报告的遗留建议进行纵深防御加固，并修复 Docker 部署链路中的多项问题，**无功能变更、无数据库结构变更**，覆盖代码即可升级。

### Security

- **CSRF 纵深防御 —— Origin/Referer 同源校验**：v2.4.1 仅显式启用 `SameSite=Lax`（对现代浏览器有效），本次在 `before_request` 增加同源校验钩子：所有 Cookie 鉴权的 POST/PUT/PATCH/DELETE 请求必须携带与本站一致的 `Origin`（或 `Referer`）头，跨站来源直接 403；REST API（`/api/`，X-API-Token 鉴权不依赖 Cookie）豁免；无 Origin/Referer 的非浏览器客户端（curl/SDK）放行。覆盖旧浏览器（不识别 SameSite）与同站子域名攻击场景。
- **纯文本字段移除 `|safe`（存储型 XSS 防御加固）**：6 套主题的 `footer_copyright`（页脚版权）、`site_close_reason`（关站提示）、表单插件 `form.description`（表单说明）以及招聘插件 `job.description`（岗位描述）均为后台纯文本录入（普通 input/textarea，非富文本），此前模板以 `|safe` 输出存在 XSS 隐患，共 19 处改为自动转义。富文本字段（文章正文、单页内容、richtext 自定义字段、统计代码）保持原样，属 CMS 富文本设计范畴。

### Fixed

- **修复维护模式（站点关闭）页面 500 错误**：`check_site_status` 渲染关站模板时未传入 `seo` 变量，而主题 `base.html` 的 meta keywords 依赖该变量，导致开启维护模式后所有前台页面报 `UndefinedError`；现补传 `seo=_seo()`，维护模式恢复正常（HTTP 503 关站页）。
- **修复 Docker 部署 worker 启动失败**：`requirements.txt` 新增 `cryptography` 依赖，解决 PyMySQL 连接 MySQL 8+（`caching_sha2_password` 认证）时 worker boot 失败；`entrypoint.sh` 以 root 修正挂载目录属主后经 `gosu` 降权运行，并增加数据库就绪等待逻辑；`Dockerfile` 安装 `gosu`、CMD 改为 shell 形式使 `GUNICORN_WORKERS` 环境变量生效。
- **修复 CSP 拦截 CDN 静态资源**：后台（AdminLTE/FontAwesome/jQuery/icheck-bootstrap）与 6 套前台主题（Bootstrap/FontAwesome）引用的 jsdelivr CDN 资源被 v2.4.1 引入的 CSP（`script/style-src 'self'`）拦截，新增 `app/static/vendor/` 本地化全部静态资源，9 个模板共 36 处外链改为 `url_for('static')` 本地引用，CSP 保持严格 `'self'` 不放宽。
- **修复 Docker 初始化向导填 localhost 连库失败**：检测到 `ZHYCMS_DB_URI` 环境变量时，初始化向导隐藏数据库配置区（提示已由部署环境统一配置），POST 完全忽略数据库相关表单字段，直接使用启动时已连通的引擎创建管理员，避免用户误填 `localhost` 导致 `Connection refused`。
- **修复 install.sh 自定义数据库密码不生效**：MySQL/PostgreSQL 仅在首次初始化空数据卷时应用密码，已有数据卷重跑脚本换新密码不会同步到数据库，install.sh 检测到已有数据卷时提供「沿用旧密码 / 清空重建」选择，启动后主动校验数据库凭据并给出明确指引。

### Added

- **Docker 一键安装/卸载脚本**：`docker/install.sh` 交互式完成数据库选择、密钥生成、镜像加速、Meilisearch 可选、端口与 Worker 配置，自动生成 `.env` 并构建启动；`docker/uninstall.sh` 清理容器、卷、镜像与配置。`docker-compose.yml` 改用 YAML 锚点替代 `extends` 以兼容 Compose v2，支持自定义端口 `WEB_PORT`。

### Changed

- 版本号 `CMS_VERSION` 由 `2.4.1` 升级为 `2.4.2`。
- install.sh 中 PostgreSQL 的定位描述由「轻量替代」修正为「高并发性能更强」。

## [2.4.1] - 2026-09-05

**安全修复版本**。针对 v2.4.0 安全审计发现的 8 项问题进行修复，**无功能变更、无数据库结构变更**，v2.4.0 站点直接覆盖代码即可升级。

### Security

- **【严重】修复硬编码默认 SECRET_KEY 导致的会话伪造漏洞（CWE-798）**：移除 `app/config.py` 中的硬编码回退密钥，改为环境变量 > `instance/secret_key` 持久化文件 > 首次启动自动生成 `secrets.token_hex(32)` 并落盘（权限 600）。存量部署首次启动会自动生成新密钥并使旧会话失效（需重新登录），攻击者无法再通过公开源码中的默认密钥离线伪造管理员会话。
- **【高危】修复搜索结果页存储型 XSS（CWE-79）**：`highlight` 过滤器先对标题/摘要原文与关键词做 `markupsafe.escape`，再仅对转义后的匹配文本包裹 `<mark>` 标签，杜绝文章标题中的 HTML/JS 在搜索页执行。
- **【中危】修复登录与语种切换的开放重定向漏洞（CWE-601）**：`/admin/login` 与 `/admin/set-locale` 的 `next` 参数拒绝协议相对 URL（`//evil.com`、`/\evil.com`），仅允许站内相对路径。
- **【中危】修复 `run.py` 硬编码 `debug=True`（CWE-489）**：`debug` 取值跟随当前配置类（`app.config['DEBUG']`），生产环境（`ZHYCMS_ENV=production`）不再误开启 Werkzeug 调试器；文档明确生产环境推荐使用 gunicorn（`wsgi:app`）启动。
- **【中危】显式设置会话 Cookie `SameSite=Lax`**：在 `Config` 中显式声明 `SESSION_COOKIE_SAMESITE='Lax'`，生产环境 `ProductionConfig` 启用 `SESSION_COOKIE_SECURE=True`，不再依赖浏览器默认行为。
- **【低危】修复备份恢复上传在 Web 可访问目录残留副本（CWE-552）**：`/admin/backups/restore-upload` 不再经 `save_upload_file` 写入 `app/static/uploads`，改为直接落盘到 `instance/backups`（非 Web 目录），恢复完成后立即删除，全库备份不再可被匿名下载。
- **【低危】修复表单导出 Excel 公式注入（CWE-1236）**：`plugins/form` 导出 xlsx 时对以 `=`、`+`、`-`、`@`、制表符、回车开头的字符串前置单引号转义，访客提交的恶意公式不再在管理员打开 Excel 时执行。
- **【低危】补齐安全响应头基线**：全站 `after_request` 统一注入 `X-Frame-Options: SAMEORIGIN`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: strict-origin-when-cross-origin`、`Content-Security-Policy`（含 `frame-ancestors 'self'`），防点击劫持、MIME 嗅探与 Referrer 外带。

### Changed

- 版本号 `CMS_VERSION` 由 `2.4.0` 升级为 `2.4.1`。

## [2.4.0] - 2026-09-04

**Alembic 迁移 + 全文搜索 + Docker 容器化 + 对象存储 OSS**版本。v2.3.x 覆盖代码升级后首次启动自动 stamp baseline + 执行增量迁移，无需手动操作；全文搜索默认使用 Whoosh + jieba 中文分词，SQL LIKE 自动回退；Docker 支持 MySQL / PostgreSQL 一键部署；新增官方内置 `oss_storage` 插件，支持阿里云 OSS / 腾讯云 COS / 七牛云 Kodo 云端对象存储与本地存储一键切换（默认本地，零行为变化）。

### Added

- **Alembic 数据库迁移框架（Flask-Migrate）**：
  - 引入 Flask-Migrate（封装 Alembic），提供 `flask db upgrade/downgrade/stamp` CLI；`create_app()` 启动时自动检测旧库（v2.3.0 及更早）并 stamp baseline，仅执行增量迁移，旧站零手动操作。
  - 基线迁移 `0001` 标记 v2.3.0 完整 schema；`0002` 新增 `search_index` 元数据表；`0003` 幂等插入 6 个搜索设置默认值。
  - 插件迁移钩子：`PluginBase.get_migration_files()` 返回插件 `migrations/versions/` 下的迁移脚本路径，核心自动合并到 Alembic `version_locations`，插件 schema 变更纳入统一管理；无迁移文件的插件仍由 `db.create_all()` 兜底建表。
  - `render_as_batch=True` 启用 SQLite batch 模式，兼容 SQLite 表结构变更限制。
- **全文搜索引擎（Whoosh + jieba + Meilisearch 可选）**：
  - 默认使用 Whoosh（纯 Python）+ jieba 中文分词，索引标题 + 正文（去 HTML）+ 摘要 + 栏目名，支持相关度排序；索引存 `instance/search_index/`，文章保存/删除时通过 `clear_content_cache` 钩子自动更新。
  - 可选 Meilisearch 后端（大型站点），通过后台搜索设置页切换引擎。
  - SQL LIKE 自动回退：Whoosh 故障时自动降级为 SQL LIKE，搜索不中断。
  - 后台新增「搜索设置」页面（系统设置子菜单）：引擎选择、Meilisearch 配置、健康检查、一键重建索引。
  - 6 套主题搜索模板更新：支持分页、关键词高亮（`|highlight(keyword)` 过滤器）。
- **Docker 容器化**：
  - 多阶段构建 `Dockerfile`（builder + runtime），基于 `python:3.12-slim`，非 root 用户运行，gunicorn WSGI 服务。
  - `docker-compose.yml` 提供 `--profile mysql` 和 `--profile postgres` 两个数据库选项，可选 `--profile search` 挂载 Meilisearch。
  - `docker/entrypoint.sh` 自动执行数据库迁移、恢复演示图片（volume 挂载遮盖时）、启动 gunicorn。
  - 新增 `/healthz` 健康检查端点（DB ping + JSON 响应），豁免初始化拦截。
  - `wsgi.py` 生产入口，`requirements-prod.txt` 含 gunicorn + gevent。
  - `docker/.env.example` 环境变量模板。
- **对象存储 OSS 插件 `oss_storage`（官方内置）**：
  - 核心新增存储抽象层 `app/utils/storage.py`（`StorageDriver` 协议 + 本地驱动 + 驱动注册表 + 三类显式异常），上传唯一入口 `save_upload_file()` 改为先本地处理（校验/压缩/缩略图）再发布到当前驱动；**默认本地存储，行为与旧版完全一致**。
  - 插件内置三家云驱动：**阿里云 OSS**（oss2）、**腾讯云 COS**（cos-python-sdk-v5）、**七牛云 Kodo**（qiniu）；云 SDK 可选依赖懒加载，未安装时配置页给出 `pip install` 安装指引；新插件钩子 `PluginBase.get_storage_drivers()` 注册驱动、`on_disabled()` 禁用回调。
  - `uploaded_files` 表新增 `storage` 列（迁移 `0004`，默认 local）记录每个文件的存储归属，切换驱动/换厂商后旧文件 URL 不失效。
  - 后台「对象存储」配置页（系统设置子菜单，权限 `oss_storage:manage`）：驱动切换（切换前自动连接测试，失败回退本地）、凭证管理（密钥留空不修改）、连接测试、SDK 安装状态检测。
  - **一键迁移工具**：本地历史文件批量上传云端（dry-run 预览 + 幂等可重入，已传文件自动跳过），并把文章正文/封面、碎片、自定义字段、站点 Logo 等内容中的 `/static/uploads/` 链接自动改写为云域名；本地文件保留不删，演示图片不迁移。
  - 安全：云驱动上传失败显式报错不静默回退本地；禁用插件自动重置为本地驱动；备份恢复文件强制留本地磁盘；凭证建议使用云厂商 RAM 子账号最小权限；插件中英文双语（独立翻译域）。

### Changed

- `clear_content_cache` 扩展：文章保存/删除时触发搜索索引更新（独立于缓存开关，缓存关闭时索引仍正常更新）。
- 前台 `/search` 路由改用 `search_articles()` 替代 SQL LIKE，返回分页结果集 `(items, total)`。
- 上传入口 `save_upload_file()` 新增 `storage_scope` 参数（`auto`/`local`），备份恢复路由强制 `local`。
- `Setting.DEFAULTS` 新增 6 个搜索设置键 + 15 个对象存储配置键；`Setting.CMS_VERSION` 更新为 `2.4.0`。

### Fixed

- 无。

## [2.3.0] - 2026-09-02

**国际化 + 统计插件 + 表单插件化 + 英文主题**版本。**无数据库结构变更，v2.2.x 直接覆盖代码即可升级**；自定义表单由核心转为内置插件（表名/路由/设置键/审计模块代码不变，老站数据无缝保留），国际化默认关闭、不改变现有站点行为。

### Added

- **国际化（i18n，Flask-Babel）**：
  - 中英文自由切换，前台 + 后台全站生效；新增语种仅需追加翻译目录并编译（`pybabel init/update/compile`），无需改代码。
  - Locale 选择优先级：URL `?lang=xx`（一次性，写回 session）→ session → cookie → `Accept-Language` 自动匹配 → 默认语种 `zh` 兜底。
  - 后台「系统设置 → 国际化」可视化配置页（权限 `system:settings`）：总开关、默认语种、可用语种清单，改动写入审计。
  - 后台顶栏与前台主题 `base.html` 语言切换器（`available_locales()` / `current_locale()` 全局函数）；未启用时切换器自动隐藏。
  - 切换路由 `/admin/set-locale`（归属核心）；核心模板（后台 base 与全部主题 base 等界面文案）已标记 `_()` 并提供英文翻译（`app/translations/en/LC_MESSAGES/messages.po`）。
  - 默认关闭（`i18n_enable=0`）：关闭时全站按中文渲染，与 v2.2.0 行为完全一致；内容数据（栏目名/文章标题等动态数据）不在翻译范围，仅界面文案国际化。
  - **插件独立翻译域**：每个插件可在 `plugins/<slug>/translations/<lang>/LC_MESSAGES/messages.po` 自带译文；模板使用 `{{ _p('<slug>', '原文') }}`，Python 层使用 `self._('原文')`；启停不影响核心译文，独立打包上传插件时译文随目录携带。
  - **英文主题模板**（v2.3 新增 2 套官方内置主题）：`default_en`（经典默认英文版）与 `manufacturing_en`（制造业英文版），全部模板文件（base/index/list/article/page/404/500/form/search 等）硬编码文案已英文化，`<html lang="en">`；初始化向导新增 `manufacturing_en` 和 `default_en` 两个演示数据选项，选择英文制造业演示数据时自动启用 banner + product + friend_link + form 插件并生成全英文演示数据（栏目、文章、产品、轮播图、友情链接、表单均为英文内容）；同时自动配置 i18n（`i18n_enable=1`、`i18n_default_locale=en`、`i18n_available_locales=zh,en`），确保前台 locale 为英文、插件翻译域生效。
  - 全部官方插件（banner / product / friend_link / form）的演示数据钩子均已支持 `manufacturing_en` 参数，生成对应英文内容；产品插件 `.po` 翻译文件已全量补全（85 条），含 `Previous product` / `Next product` / `Latest products` 等前台界面文案。
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
- `.gitignore` 修复：`app/static/uploads/` 整体忽略导致 `demo/` 演示图片无法入库（安装后图片 404）；改为 `uploads/*` + `!uploads/demo/`，15 张演示图片随仓库分发。
- 产品插件 `messages.po` 英文翻译全量补全（85 条），修复 `上一个产品` / `下一个产品` / `最新产品` / `暂无其他产品` 等前台界面文案在英文 locale 下仍显示中文的问题。
- 后台多个路由名修正：`monitor_page` → `monitor_index`、`backup_create` → `backup_manual`、backup 按钮参数 `name` → `bid`；setup 页面静态资源恢复 CDN 引用；setup 模板变量引用与 input name 修正。
- `CMS_VERSION` 改用 `Setting.CMS_VERSION` 类属性访问，避免实例化查询；`monitor_index` 视图传齐模板所需变量。
- `i18n` 关闭时不支持语言切换（恢复原始行为），避免关闭态下切换器误触发。

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
