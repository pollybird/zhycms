# 更新日志（Changelog）

本项目的所有显著变更都记录在本文件中。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。

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

[Unreleased]: https://gitee.com/pollybird/zhycms/compare/v2.1.1...HEAD
[2.1.1]: https://gitee.com/pollybird/zhycms/compare/v2.1.0...v2.1.1
[2.1.0]: https://gitee.com/pollybird/zhycms/compare/v2.0...v2.1.0
[2.0.0]: https://gitee.com/pollybird/zhycms/compare/a717ad4...v2.0
[1.1.0]: https://gitee.com/pollybird/zhycms/compare/v1.0...a717ad4
[1.0.0]: https://gitee.com/pollybird/zhycms/releases/tag/v1.0
