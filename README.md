# ZhyCMS

一个基于 Flask 的轻量级企业内容管理系统，内置多主题模板引擎、栏目级模板选择、自定义字段、表单收集、SEO 优化、全文搜索、对象存储等能力，适合搭建企业官网、资讯门户、产品展示站等。

<p>
  <img alt="Version" src="https://img.shields.io/badge/version-3.3.4-2e6df6?style=flat-square">
  <img alt="License" src="https://img.shields.io/badge/license-MulanPSL--2.0-blue?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white">
  <img alt="Tests" src="https://img.shields.io/badge/tests-839%20passed-brightgreen?style=flat-square">
  <a href="https://github.com/pollybird/zhycms/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/pollybird/zhycms?style=flat-square&logo=github&label=star"></a>
</p>

**当前版本：v3.3.4**（缺陷修复与站群增强：修复文章保存时全量清缓存导致的 120s 超时、子域标签重复误报；新增 **单站点多独立域名**（如 example.com + example.com.cn）。数据库迁移 `0021`，无新增 Python 依赖，详见 [CHANGELOG](CHANGELOG.md)、[UPGRADE](UPGRADE.md)、[站群设计](docs/SITE_GROUP.md) 与 [多站点部署](docs/DEPLOY_MULTI_SITE.md)）

> **授权声明（人大金仓 KingbaseES / 达梦 DM8）**：本项目**仅实现对上述数据库的适配支持**。
> KingbaseES 与达梦 DM8 均为商业软件，其安装包、客户端工具与授权文件（license）
> **需用户自行到官方下载并获取官方授权**（KingbaseES：
> <https://www.kingbase.com.cn/download.html>；达梦：<https://www.dameng.com/>）。
> 本仓库不提供、不分发上述产品的二进制或许可证。

**项目官网：[https://zhycms.tzzhy.cn/](https://zhycms.tzzhy.cn/)**（官网与使用文档）

**在线演示**

- 前台：[https://demo.zhycms.tzzhy.cn/](https://demo.zhycms.tzzhy.cn/)
- 后台：[https://demo.zhycms.tzzhy.cn/admin/login?next=/admin/](https://demo.zhycms.tzzhy.cn/admin/login?next=/admin/)
- 后台演示账号：`admin` / `demo1234`
- 会员演示账号：`demo` / `demo1234`

> 如果这个项目对你有帮助，欢迎点个 **Star** 支持一下；也欢迎在 Gitee / GitHub 提 Issue、发 PR 一起共建。

---

## 目录

- [简介](#简介)
- [界面预览](#界面预览)
- [核心特性](#核心特性)
- [版本速览](#版本速览)
- [快速开始](#快速开始)
  - [环境要求](#环境要求)
  - [本地开发](#本地开发)
  - [Docker 部署](#docker-部署)
  - [生产部署](#生产部署)
- [目录结构](#目录结构)
- [核心功能详解](#核心功能详解)
  - [主题系统](#主题系统)
  - [页面构建器](#页面构建器)
  - [插件机制](#插件机制)
  - [国际化](#国际化)
  - [数据库迁移](#数据库迁移)
  - [全文搜索](#全文搜索)
  - [对象存储](#对象存储)
  - [安全体系](#安全体系)
  - [SEO 与性能](#seo-与性能)
  - [内容工作流](#内容工作流)
  - [审计日志](#审计日志)
- [开发者文档](#开发者文档)
- [升级指南](#升级指南)
- [Star 支持](#star-支持)
- [参与贡献](#参与贡献)
- [许可证](#许可证)

---

## 简介

ZhyCMS 采用 **Flask + SQLAlchemy + Jinja2** 技术栈，以「插件优先、主题驱动」为架构理念，在保持轻量的同时覆盖企业建站的核心需求：

- 前台：多主题切换、栏目级模板选择、伪静态、全文搜索、多语言
- 后台：RBAC 权限、内容工作流、审计日志、备份恢复、表单收集
- 扩展：插件零侵入扩展、REST API、对象存储、统计代码

---

## 界面预览

以下截图取自内置演示数据（制造业主题），完整功能可在 [在线演示](https://demo.zhycms.tzzhy.cn/) 体验（后台演示账号 `admin` / `demo1234`）。

### 前台

| 首页（轮播 + 产品展示） |
| :---: |
| ![前台首页](docs/screenshots/home.png) |

### 后台

| 仪表盘 | 文章管理（工作流状态与批量操作） |
| :---: | :---: |
| ![后台仪表盘](docs/screenshots/admin-dashboard.png) | ![文章管理](docs/screenshots/admin-articles.png) |
| **文章编辑（富文本 / Markdown 双模式）** | **可视化页面构建器** |
| ![文章编辑](docs/screenshots/admin-editor.png) | ![页面构建器](docs/screenshots/admin-builder.png) |
| **插件管理（启用 / 禁用 / 上传安装）** | **主题管理（内置 8 套主题）** |
| ![插件管理](docs/screenshots/admin-plugins.png) | ![主题管理](docs/screenshots/admin-themes.png) |

---

## 核心特性

| 特性 | 说明 | 版本 |
|------|------|------|
| **多主题模板系统** | 前台模板按主题组织，后台一键切换；内置 8 套主题（含 2 套英文主题） | v1.0 |
| **主题管理** | 上传/启用/删除/打包下载主题压缩包，缺失模板自动兜底 | v2.2 |
| **插件机制** | `plugins/<slug>/` 零侵入扩展，启停即时生效、无需重启 | v2.2 |
| **国际化（i18n）** | Flask-Babel 界面文案 + 内容级多语言翻译表（文章/栏目/碎片/产品/表单/岗位/友情链接，v2.5.2 起含产品规格参数与岗位部门/地点/薪资） | v2.3/v2.5 |
| **Redis 缓存** | 环境变量自动检测，RedisCache + 服务端 Session，支撑多实例负载均衡 | v2.5 |
| **数据库迁移** | Flask-Migrate（Alembic）管理 schema 版本，支持回滚 | v2.4 |
| **全文搜索** | 默认 Tantivy（Rust 内核）+ pkuseg 中文分词，可选 Meilisearch；多语言检索、插件内容接入、SQL 兜底 | v2.4 |
| **对象存储 OSS** | 阿里云 OSS / 腾讯云 COS / 七牛云 Kodo，一键迁移本地文件上云 | v2.4 |
| **Docker 部署** | 官方镜像 `pollybird/zhycms` 已发布，MySQL/PostgreSQL 一键启动，支持本地构建 | v2.4 |
| **REST API** | `/api/v1/` 只读端点，Token 鉴权 + CORS，适合小程序/Headless | v2.2 |
| **RBAC 权限** | 角色/权限点两级模型，菜单与按钮级授权，栏目级内容粒度 | v2.0 |
| **内容工作流** | 草稿 → 待审核 → 已发布/已驳回，版本快照与对比还原 | v2.0 |
| **审计日志** | 登录、配置变更、内容 CRUD 等全量留痕，支持多维度检索 | v2.0 |
| **SEO 优化** | 伪静态、sitemap、robots.txt、页面缓存、图片默认 ALT | v2.0 |
| **表单收集** | 可视化表单设计，提交后邮件/企业微信实时通知 | v2.0 |
| **备份恢复** | MySQL/PostgreSQL/JSON 三种方式，一键备份与恢复 | v2.0 |
| **前台会员体系** | 社区插件 `member`：注册/登录/资料/改密/找回密码、微信/QQ 一键登录、短信验证码登录、注册协议、栏目会员可见性 | v2.6.4 |
| **插件依赖治理** | `manifest.json` 支持 `requires`/`extends`/`min_core_version`，启用强校验 + 禁用反向依赖校验 | v2.6.4 |
| **可视化页面构建器** | 自研轻量拖拽构建器：24 个 Bootstrap4 组件、四页面类型（首页/单页/列表/文章详情）、草稿/发布/修订回滚、中英双语与会员可见性、iframe 内服务端真实渲染；插件可注册自有组件并贡献默认布局片段（启用即开箱即用） | v3.0.0 |
| **站群模式（多站点）** | 一个后端实例 + 一个库按站点切分内容：独立域名 / 泛解析子域解析、后台站点 CRUD 与切换、站点级配置/主题/SEO、搜索与缓存按站隔离、会员共享或独立、插件站群 SDK；默认站点 0 单站点部署零感知 | v3.2.0 |
| **数据库迁移插件** | 内置插件 `db_migrator`（默认不启用）：后台一键把 SQLite 开发库迁移到 MySQL/PostgreSQL，建表+数据复制+序列重置，目标库非空保护，支持迁移后免重启热切换 | v3.1.0 |
| **信创适配** | 数据库新增 **openGauss 7.0**（内置方言、向导可选、备份恢复适配），缓存新增 **openAMDC 1.0.0**（协议零改动、运行态自动识别），提供信创镜像与 Compose 编排 | v3.3.0 |
| **信创适配（增量）** | 数据库新增 **人大金仓 KingbaseES V9**（pg 兼容模式，内置方言、复用 `psycopg2-binary`、向导可选、备份恢复适配 `sys_dump`/`ksql`），新增 `docker-compose.kingbase.yml` 与部署文档；无迁移、无新增依赖 | v3.3.1 |
| **信创适配（达梦）** | 数据库新增 **达梦 DM8**（`dmpython` + `dmSQLAlchemy`，内置方言补齐整数主键 `IDENTITY`、向导可选、备份恢复适配 `dexp`/`dimp`），新增 `requirements-dm.txt` 与部署文档；无数据库迁移、`requirements.txt` 不变 | v3.3.2 |
| **信创适配（PolarDB）** | 数据库新增 **PolarDB for PostgreSQL 15**（Apache 2.0 开源，内置 `polardb_pg` 方言、复用 `psycopg2-binary`、向导可选、备份恢复适配 `pg_dump`/`psql`），新增 `docker-compose.polardb.yml` 与部署文档；无数据库迁移、无新增 Python 依赖 | v3.3.3 |

---

## 版本速览

### v3.3.4（2026-11-28）

- **修复：文章保存超时（504 / upstream prematurely closed）**：`flask-caching 2.5` 无 `delete_pattern`，文章保存后的 `cache.clear()` 在 Redis 下退化为 `KEYS <prefix>*` + 单条大 `DEL`，缓存键多时会阻塞 Redis 并占用大量内存，超过 gunicorn 超时后 worker 被杀。改为 `purge_cache_prefix()`：`SCAN` + 每 500 个键批量 `DEL`，仅清理当前站点前缀；同时为缓存客户端加 5s 超时，前端缓存键只保留 `page` 白名单参数，避免爬虫随机参数制造海量键；保存链路增加分段耗时日志与慢请求日志。
- **修复：子域标签重复误报**：`sites.subdomain` 不再全局唯一，改为按“所属域名作用域”校验与解析——站点 A(a.com, www) 与站点 B(b.com, www) 可同时存在，分别由 `www.a.com` / `www.b.com` 访问；解析优先级为「精确域名 → 域名作用域子域 → 唯一子域回落」。
- **新增：单站点多独立域名**：新增 `site_domains` 表保存附加域名（主域名仍为 `sites.domain`），后台站点表单支持每行一个附加域名；精确匹配、`site_hostnames`/nginx `server_name`、站点备份导入与 API 均支持多域名。
- **迁移与文档**：新增迁移 `0021`（`site_domains` 表 + 子域索引改为普通索引），更新 [站群设计](docs/SITE_GROUP.md)、[多站点部署](docs/DEPLOY_MULTI_SITE.md) 与 [运维 FAQ](docs/OPERATIONS_FAQ.md)。

### v3.3.3（2026-11-28）

- **PolarDB for PostgreSQL 支持**：新增内置方言 [app/utils/dialects/polardb.py](app/utils/dialects/polardb.py)，`PolarDBPGDialect` 继承 PostgreSQL 方言并注册 `polardb_pg` / `polardb_pg.psycopg2`；复用标准 `psycopg2-binary`（`requirements.txt` 不变），URI 形如 `polardb_pg+psycopg2://user:pwd@host:5432/zhycms`。父类版本解析失败时回退 `SHOW server_version`，并注册 `PolarDBPGImpl` 供 Alembic 查表。
- **向导 / 健康检查 / 备份恢复**：初始化向导新增「PolarDB for PostgreSQL」选项（默认端口 `5432`）；`/healthz?detail=1` 返回 `db_dialect=polardb_pg`；备份用 `pg_dump`、恢复用 `psql`，工具路径支持 `ZHYCMS_POLARDB_BIN`。
- **镜像与编排**：新增 `docker-compose.polardb.yml`（官方多架构镜像 `polardb/polardb_pg_binary:15`）与 `docker/polardb/init.sh`（幂等 initdb / 建账号建库 / 优雅启停）；新增应用镜像 `pollybird/zhycms:polardb`（`INSTALL_PG_CLIENT=1` 内置 `postgresql-client`）。
- **文档与测试**：新增 [PolarDB 部署指南](docs/DEPLOY_POLARDB.md)，更新 [信创适配专题](docs/XINCHUANG_ADAPTATION.md) 与 README；新增 `tests/test_polardb.py`（离线 + `ZHYCMS_TEST_POLARDB_URL` 门控 live），CI 增加 x86_64 / aarch64 迁移与备份恢复冒烟。

### v3.3.2（2026-11-27）

- **达梦 DM8 支持**：新增内置方言 `app/utils/dialects/dm.py`，基于 PyPI `dmpython` + `dmSQLAlchemy` 注册 `dm` / `dm.dmPython`，并注册 `DMImpl` 供 Alembic 查表；上游方言只在 `autoincrement=True` 时生成 `IDENTITY`，本方言为 `Column(Integer, primary_key=True)`（默认 `'auto'`）补齐 `IDENTITY(1, 1)`。URI 形如 `dm+dmPython://user:pwd@host:5236/SCHEMA`（database 段即 Schema）。无数据库迁移（仍为 `0020`），`requirements.txt` 无新增必需依赖。
- **向导 / 健康检查 / 备份恢复**：初始化向导新增「达梦 DM8」选项（默认端口 `5236`，「数据库名」对应 Schema）；`/healthz?detail=1` 返回 `db_dialect=dm`；备份用 `dexp` 导出二进制 DMP 并 gzip 为 `.dmp.gz`，恢复用 `dimp`，工具路径支持 `ZHYCMS_DM_BIN`。
- **文档与测试**：新增 [达梦 DM8 部署指南](docs/DEPLOY_DM.md) 与 `requirements-dm.txt`，更新 [信创适配专题](docs/XINCHUANG_ADAPTATION.md) 与 README；新增 `tests/test_dm.py`（离线 + `ZHYCMS_TEST_DM_URL` 门控 live）。x86_64 与华为云鲲鹏 ARM（aarch64，EulerOS 3.0）均完成端到端验证，详见 [达梦 DM8 ARM 实测报告](docs/DM8_ARM_TEST_REPORT.md)。
- **DM8 兼容性修复**：`dm.py` 内置 `_patch_sqlalchemy_compat()`，在导入 `dmSQLAlchemy` 前补齐 SQLAlchemy 2.1 移除的 API；新装改为直接 stamp 最新迁移版本 `0020`（不执行增量迁移），并在启动期幂等确保默认站点（id=0）存在，避免新装触发增量迁移时产生「列已存在」冲突。
- **授权声明**：本项目仅实现对达梦 DM8 的适配支持；达梦 DM8 为商业软件，安装包与授权文件需用户自行到 <https://www.dameng.com/> 下载并获取官方授权。

### v3.3.1（2026-11-26）

- **人大金仓 KingbaseES V9 支持（pg 兼容模式）**：新增内置轻量方言 `kingbase`——KingbaseES 的 `select version()` 返回 `KingbaseES V009R001C010` 会导致标准 PostgreSQL 方言版本解析失败，本方言改用 `SHOW server_version`（实测 `12.1`）解析为 `(12, 1)` 并注册 `KingbaseImpl`；连接与迁移复用标准 `psycopg2-binary`，URI 形如 `kingbase+psycopg2://system:pwd@host:54321/db`。无数据库迁移（仍为 `0020`），`requirements.txt` 无新增必需依赖。
- **向导 / 健康检查 / 备份恢复**：初始化向导新增「KingbaseES（信创推荐）」选项（默认端口 `54321`、账号 `system`）；`/healthz?detail=1` 返回 `db_dialect=kingbase`；备份用 `sys_dump`、恢复用 `ksql`，**密码通过 `KINGBASE_PASSWORD` 环境变量注入**（ksql / sys_dump 不识别 `PGPASSWORD`），工具路径支持 `ZHYCMS_KINGBASE_BIN`。
- **镜像与编排**：新增 `docker-compose.kingbase.yml`；默认 `pollybird/zhycms:latest` 镜像已含 `psycopg2-binary`，**无需新增驱动构建参数或镜像变体**；备份/恢复所需客户端工具（ksql / sys_dump）由用户自行提供（见 [KingbaseES 部署](docs/DEPLOY_KINGBASE.md)）。
- **文档**：新增 [KingbaseES 部署指南](docs/DEPLOY_KINGBASE.md)，更新 [信创适配专题](docs/XINCHUANG_ADAPTATION.md) 将 KingbaseES 从「规划中」改为「已实现（pg 模式）」；V9R1C10 x86_64 + aarch64（鲲鹏）双架构端到端实测通过（迁移 `0020` 建表、向导、业务读写、备份恢复、健康检查、Compose 编排）。
- **授权声明**：本项目仅实现对 KingbaseES 的适配支持；KingbaseES 为商业软件，镜像与授权文件需用户自行到 <https://www.kingbase.com.cn/download.html> 下载并获取官方授权。

### v3.3.0（2026-11-22）

- **openGauss 支持**：`opengauss+psycopg2://` 连接 openGauss 7.0，内置轻量方言（版本解析 + Alembic DDL 注册，零新增依赖），初始化向导新增 openGauss 选项，健康检查输出 `db_dialect`，备份/恢复适配 `gs_dump` / `gsql`。无数据库迁移（仍为 `0020`）。
- **openAMDC 支持**：Redis 兼容缓存后端，缓存 / 会话 / 限流 / JWT 吊销零代码改动；启动时按 `INFO server` 自动识别后端类型并在后台与 `/healthz?detail=1` 展示 `redis_flavor`。
- **镜像与编排**：新增 `pollybird/zhycms:opengauss`（x86_64 / aarch64 多架构）、`pollybird/openamdc:1.0.0`（x86_64 / aarch64 多架构）、`pollybird/opengauss:7.0.0`（x86_64 / aarch64 多架构）；新增 `docker-compose.opengauss.yml`，通用编排增加 `openamdc` profile。
- **文档与测试**：新增 [openGauss 部署](docs/DEPLOY_OPENGAUSS.md)、[openAMDC 部署](docs/DEPLOY_OPENAMDC.md) 与 [信创数据库适配专题](docs/XINCHUANG_ADAPTATION.md)（达梦/金仓/GBase/PolarDB 适配思路与贡献指南）；新增 54 项测试与兼容性 CI 工作流。openGauss 7.0 已在 x86_64 与 aarch64（鲲鹏）双架构端到端实测通过（26 项：方言注册、建表、CRUD、备份恢复、健康检查、Alembic DDL）。openAMDC 1.0.0 已在 x86_64 与 aarch64（鲲鹏）双架构端到端实测通过（79 项：后端识别、缓存、会话、限流、JWT 吊销、Lua 脚本、分布式锁、Pipeline、事务、Hash/List/ZSet 操作）。

### v3.2.12（2026-11-21）

- **Webhook 事件订阅**：`article.published` / `article.archived` / `form.submitted` / `backup.completed` / `site.status_changed` / `ssl.expiring` / `webhook.test` 七类事件，业务事务提交后落库、10 秒调度异步外送。
- **安全投递**：HMAC-SHA256 签名（`X-ZhyCMS-Signature: t=...,v1=...`）、`X-ZhyCMS-Delivery` 幂等标识、1s/10s 重试后终态失败并写审计、每订阅每秒 5 次限速、禁跟随重定向、SSRF 防护（默认仅 HTTPS 公网，`webhook_allow_http` / `webhook_allow_private` 默认关闭）。
- **后台管理**：全局设置 → Webhook 集成（`site:manage`），订阅增删改、密钥仅显示一次与轮换、测试发送、投递记录筛选与失败重试，全程审计。
- **数据与运维**：迁移 `0020` 新增 `webhook_subscriptions` / `webhook_events` 两表；密钥 Fernet 加密存储；支持 `python -m app.services.webhook --once` 外部 cron；新增 [Webhook 文档](docs/WEBHOOK.md)，15 项回归测试。

### v3.2.11（2026-11-21）

OpenAPI 公开版。内容 API 新增 OpenAPI 3.0 契约注册表与 `GET /api/v1/openapi.json`，`scripts/generate_openapi.py` 生成 `docs/openapi.yaml`，`scripts/check_openapi.py` 校验路由覆盖率。新增默认关闭的内容写端点（文章、栏目、碎片），开启后仅接受 Bearer JWT 并复用后台服务层的版本快照、审计日志与自定义字段；补充表单提交分页、站点列表与站点计量只读端点。提供仓库内 Python SDK（`sdk/zhycms_sdk`），支持登录、401 自动刷新重放与统一异常。无数据库迁移、无新增 Python 依赖。

### v3.2.10（2026-11-21）

多进程 / 多实例扩展。配置 `REDIS_URL` 后，限流、缓存、会话与调度器领导者锁共享同一 Redis，多 worker 下定时任务只执行一次；`ZHYCMS_SCHEDULER_ENABLED` 可关闭内置调度交由外部 cron，`ZHYCMS_REQUIRE_REDIS=1` 可拒绝在无 Redis 时启动。`generate_nginx_sites.py --upstreams` 生成多实例 upstream 与 keepalive；`/healthz?detail=1` 输出数据库、Redis、缓存、限流、调度器角色与站点解析结果；新增 `scripts/bench_http.py` 压测脚本。无数据库迁移、无新增依赖。

### v3.2.9（2026-11-20）

安全修复版。API 登录排除已删除、禁用与锁定账号，密码错误接入失败计数和临时锁定；访问令牌与刷新令牌每次使用都会复核账号状态。内容 API 不再输出会员专属栏目及文章。短信验证码改用服务端密钥 HMAC，连续输错默认 5 次后作废，短信登录、找回密码和发送验证码接口按手机号与 IP 限流。SVG 上传改为元素/属性白名单净化，找回密码与短信登录（关闭自动注册时）统一模糊提示、不再暴露手机号注册状态，后台退出登录仅接受带 CSRF 的 POST。含迁移 `0019`，无新增 Python 依赖。

### v3.2.8（2026-11-18）

站点平台化运维。新增站点克隆：栏目、字段、文章、碎片、页面构建与插件内容可复制到新站点，目标站默认关闭，上传资产与日志不复制；内容量大时转异步任务并写入 `site_jobs`，重启后自动清理半成品站点。新增站点级备份：单站导出 ZIP（manifest + 各表 JSONL + 上传目录），导入支持新建/覆盖/改名，自动重映射主键、重写上传 URL 并重建文件索引，下载链接限时签名。新增证书到期巡检：每日 08:00 检查，默认提前 10 天告警，支持邮件与企业微信提醒，`scripts/check_ssl_expiry.py` 可接入外部监控。站点列表支持批量启用/禁用、批量删除与批量分配角色；删除改为移入回收站，到期先备份再彻底删除。Docker 内置 Redis 升级为 `redis:8-alpine`。含迁移 `0018`，无新增 Python 依赖。

### v3.2.7（2026-11-18）

站群部署与可观测。新增 `scripts/generate_nginx_sites.py`：读取站点表生成可 `nginx -t` 通过的 vhost，覆盖精确域名、泛解析子域、默认站点 `_` 兜底、SSL 跳转与非法域名跳过；后台站点列表新增「部署指南」，只读展示与脚本逐字一致的配置片段和 Let's Encrypt 证书剩余天数。新增 `/admin/sites/metrics` 资源面板与 4 个全局阈值（磁盘/文章/缓存/硬上限），每日 00:30 写入 `site_metric_snapshots`（迁移 `0017`）。新增插件站点作用域 AST 审计脚本与未适配标签，日志统一附加 `[site=N]` 标签；审计导出文件名带站点标识。单站点部署无需改动 nginx。无新增依赖。

### v3.2.6（2026-11-17）

站点级配置与日志可见性。消息通知、编辑设置、内容 API 从全局配置改为按站点配置：不同站点可分别设置表单通知收件人、默认编辑器，以及内容 API 的开关、鉴权方式与密钥（新增 `app/utils/api_jwt.py` 按站点密钥签发/校验 JWT）。审计日志与登录日志仅超级管理员、站点管理员可见，站点管理员仅能看到自己授权站点的日志（列表、筛选、导出、清理与仪表盘同步过滤），内容审核员与只读查看员不再可见；`LoginLog` 新增 `site_id`（迁移 `0016`）。Redis 缓存页仅超级管理员可见。站点级设置未配置时回退默认站点 0 的存量值，单站点部署行为不变。无新增依赖。

### v3.2.5（2026-11-17）

后台菜单分类重排。原「系统设置」把站点级与全局级配置混在一起，现拆分为两组：**站点设置（当前站点）** 收纳网站设置、SEO 默认配置、SEO 高级、主题管理；**全局设置（全站共用）** 收纳站点管理、插件管理、上传配置、上传安全、消息通知、后台安全、登录日志、内容 API、国际化、搜索设置、编辑设置、Redis 缓存。站点管理员仍可访问全局配置项，但看不到平台级的「站点管理」「插件管理」入口；各设置页面面包屑同步更新。无数据库迁移、无新增依赖。

### v3.2.4（2026-11-17）

密码策略可配置。后台管理员的密码复杂度不再写死：超级管理员可在「全局设置 → 后台安全」调整最低位数（6-64）以及大写字母/小写字母/数字/特殊字符四个必含项；默认仍为 12 位 + 四类字符的严格策略。最低位数低于 8 位时保存前弹出确认框提示安全风险，保存后返回 warning。初始化向导、个人改密、账号新建/重置密码的表单 `minlength` 与提示文案随策略动态渲染；`password_` 为全局设置前缀，站点切换不改变策略。无数据库迁移、无新增依赖。

### v3.2.3（2026-11-17）

角色体系站点化。新增「站点管理员」预设角色：拥有指定站点的全部后台管理权限（站点设置、用户、审计、栏目、内容、页面构建、表单），不含站点增删改与备份运维等平台级功能；内容审核员/内容编辑/只读查看员同样绑定到具体站点。`user_roles` 新增 `site_id` 并改为 `(user_id, role_id, site_id)` 唯一（迁移 `0015`），支持一人多站多角色；账号表单为每个站点提供角色下拉。超级管理员可为任意站点分配角色，站点管理员只能在自己有权限的站点内添加/管理账号，角色配置页仅平台管理员可访问。存量 `site_id IS NULL` 的全局角色保持全站语义。无新增依赖。

### v3.2.2（2026-11-17）

站群内容隔离补全。闭环潜在威胁报告 11 项：教程/页面构建/上传索引/第三方绑定新增 `site_id` 并改为站点级唯一（迁移 `0014`），前台、后台、模板函数与构建器组件全部按站过滤；跨站页面 404、去重与物理路径按站隔离、删站检查补齐、会员删除与 OAuth 绑定站点化、备份/监控收敛为平台级运维、缓存按 `frontend/site{N}/*` 失效、浏览量按站分键、插件 `sql_search` 支持 `site_id`、平台级后台入口豁免。无新增依赖。

### v3.2.1（2026-11-16）

站群缺陷修复。闭环第三方测试报告的 P0/P1/P2 共 5 项：站点权限 `?site=` 越权（解析层校验 + 后台统一守卫）、`status=closed` 未覆盖 API 与插件前台蓝本（提升为 app 级校验，API 返回 503 JSON、healthz 固定 200）、独立会员会话跨站有效（`current_member()` 校验站点）、站点 SEO 字段不生效（前台与 API 接入站点 SEO 回退链）、`0012` 降级半回滚（DDL 前预检跨站重复）；另加固子域唯一约束、域名校验、删站内容检查、`accessible_sites` N+1、JWT 首启告警等边界项。新增迁移 `0013`，无新增依赖。

### v3.2.0（2026-11-15）

站群版。新增站点注册表 `sites` 与 `site_id` 内容维度：请求按「后台切换 → 精确域名 → 子域标签 → 默认站点 0」解析站点，栏目/文章/碎片/配置/会员/内置插件内容全部按站隔离；后台新增站点管理（CRUD + 切换器）与站点级权限 `site:manage` / `UserSitePermission`；站点化配置、主题、sitemap、全站搜索与缓存命名空间；会员支持共享（默认，与现网一致）或独立；插件 SDK 提供 `SiteScopedMixin` / `current_site_id()` / `site_filter()`。默认站点 `site_id=0` 恒等变换，单站点部署 URL 与行为完全不变。数据库迁移 `0012`，无新增依赖。

### v3.1.10（2026-11-09）

纵深防御与合规加固。闭环 GitCode Issue #14 残留 Low/Info 项与 SAST P3 共 9 项：主题模板静态审计新增下标内字符串拼接检测、加密密钥不可用时后台全页红色横幅 + error 日志高可见度告警（fail-open 语义不变）、CORS 新值拒 `*` 与非法来源格式（存量不清空仅 UI 告警）、后台管理员新密码统一 12 位四类字符（存量与会员端不受影响）、CI 工作流 10 处 Actions pin 完整 commit SHA、新增 dependabot 周更、TestingConfig 固定密钥误用于生产时启动直接拒绝；SSRF DNS TOCTOU 与 Markdown 内联 HTML 维持文档披露不新增代码。无数据库结构变更、无新增依赖。

### v3.1.9（2026-11-08）

安全修复。完成 v3.1.8 顺延的 6 个 Medium 并闭环 GitCode Issue #14：插件 AST 审计支持 import 别名/赋值传播/危险 getattr（间接引用绕过全部拦截）、JWT 登出后 jti 进入 Redis 黑名单即时失效、登录前清空 Session（会话固定）、SQL LIKE 通配符统一转义、Meilisearch 地址保存与使用前校验（允许内网）、生产环境 DEBUG 强制阻断、数据库连接错误对外脱敏；另修复验证码随机源与 fragment 操作审计日志。无数据库结构变更、无新增依赖。

### v3.1.8（2026-11-06）

安全加固专项（GitCode issue #12，SAST 深度审计）。修复 P0+P1 共 7 个漏洞：主题模板 SSTI（构建器渲染强制 Jinja 沙箱 + 上传静态审计）、插件包 RCE（上传静态审计 + 直传开关默认关闭）、敏感凭证明文入库（Fernet 加密 + 惰性迁移）、企业微信/短信 Webhook SSRF（域名白名单 + 内网 IP 拒绝）、JWT 密钥与 SECRET_KEY 隔离（未配置自动生成持久化）；新增 CSP 第三方资源白名单（后台「后台安全」页可配 script/style/img/font/connect/media/frame-src 7 个指令来源）。无数据库结构变更、无新增依赖。

### v3.1.7（2026-11-03）

稳定性修复。修复文章/栏目批量删除、归档、发布、移动等操作因 CSRF Token 缺失导致的 403，并消除批量表单与行内表单的非法嵌套；全站索引重建改为后台异步任务 + 页面轮询进度，重建期间增量变更自动补索引；数据库迁移插件新增源库外键孤儿预检与可空列自动置空，迁移失败时给出表名/行数定位。无数据库结构变更、无新增依赖。

### v3.1.6（2026-11-01）

异常吞噬专项治理。全库通用异常捕获统一中文 warning 留痕、可判定场景收窄为具体异常类型、插件隔离处保留宽捕获并注释；文章五状态流转收敛为 `app/services/workflow_service.py` 状态机并改为单事务提交（状态与版本快照原子生效）；新增 CI 门禁 `scripts/check_excepts.py`（配套白名单）。无数据库结构变更、无新增依赖。

### v3.1.5（2026-11-01）

后台富文本双模式编辑。文章正文、单页栏目内容与富文本碎片新增 Markdown 模式（表单内一键切换 + 实时预览，系统设置可改默认模式），Markdown 原文双写存储、`content` 始终为 HTML，前台主题 / 搜索 / API 零改动。数据库迁移 `0011`，新增依赖 `markdown`。

### v3.1.0（2026-10-10）

数据库迁移插件。新增官方内置插件 `db_migrator`（默认不启用）：后台一键把 SQLite 开发库迁移到 MySQL/PostgreSQL——目标库建表 → 按外键依赖逐表复制（单事务失败整体回滚）→ PostgreSQL 自动重置自增序列 → 同步 Alembic 版本号；连接测试、目标库非空保护（需显式勾选覆盖）、迁移后立即热切换引擎免重启（失败自动回滚配置）。修复文章批量操作（发布/撤回/删除/归档/移动/提交审核）不更新搜索索引的问题；修复后台用户管理表单与业务层脱节导致的多项账号管理异常（两次密码一致却提示不一致、新增账号默认禁用、角色未绑定、重置密码校验失败等）。无数据库结构变更、无新增依赖。

### v3.0.0（2026-09-15）

可视化页面构建器。原生 HTML5 拖拽 + JSON Schema 组件注册 + iframe 服务端真实渲染，覆盖首页/单页/列表页/文章详情页；24 个内置组件、草稿/发布/修订回滚、中英双语文案、语言与会员可见性、三端预览与全屏预览、全局页面样式设置。**默认布局三层合并**：新建构建页按「当前启用主题 fixture → 核心回退」解析基础布局（第三方主题上传时校验自带 builder JSON，8 套官方主题必备首页 fixture），再叠加已启用插件贡献的布局片段（`get_builder_layouts()` + `builder/<scope>.json`，启用强校验、撞 id 自动重写、卸载清理）；轮播图/产品/招聘/教程四个内容型插件启用后新首页开箱即用。插件通过 `get_builder_widgets()` 钩子扩展，禁用/卸载安全降级与引用拦截。「构建器为主、手写模板永久兜底」双轨策略，老站升级零行为变化。数据库迁移 `0009`，无新增依赖。详见 [docs/PAGE_BUILDER.md](docs/PAGE_BUILDER.md)。

### v2.6.4（2026-09-12）

前台会员体系 + 插件依赖治理。新增社区插件 `member`（注册/登录/微信QQ一键登录/短信登录/找回密码/栏目会员可见性）；核心新增 `Column.member_only` 字段与前台访问守卫；插件系统新增 `requires`/`extends`/`min_core_version` 启用强校验与禁用反向依赖校验。数据库迁移 `0008`，无新增依赖。

### v2.6.0（2026-09-10）

- 工程化完善：发布 Checklist（`RELEASE.md` + `scripts/check_release.py`）
- pytest 测试脚手架 + GitHub Actions CI（34 项测试，3 Python 矩阵）
- 统一异常处理（`app/errors.py`，403/404/500 三协议分发：前台主题 / 后台模板 / API JSON）
- 常量治理（`app/constants.py` 零依赖统一命名空间 + `scripts/check_constants.py` CI 门禁）

### v2.5.2（2026-09-09）
- **新增**：一键翻译插件——编辑页多语言 Tab 一键调用百度/有道/Google/DeepSeek 翻译回填
- **新增**：全站搜索纳入插件内容（SearchProvider 提供者机制）——产品、招聘岗位进入搜索，保存/删除/上下架实时同步
- **新增**：插件结构化内容多语言——产品「规格参数」、岗位「部门/工作地点/薪资待遇」按语言维护（迁移 `0007`）
- **修复**：英文搜索页文案、核心翻译 `.mo` 启动自动编译
- **改进**：「产品展示」「招聘管理」插件升级至 1.1.0

### v2.5.1（2026-09-08）
- **新增**：全文检索国际化——Whoosh/Meili/SQL 三后端按语言分索引，搜索随当前语言返回对应内容

### v2.5.0（2026-09-07）
- **新增**：内容级多语言（i18n 2.0）——文章/栏目/碎片/产品/表单/岗位/友情链接多语言翻译表，前台 `t(obj, field)` 全局函数，后台「多语言版本」Tab
- **新增**：Redis 缓存后端 + 服务端 Session——环境变量自动检测，多实例负载均衡
- **改进**：移除后台左侧菜单冗余项、富文本翻译字段使用 CKEditor5

### v2.4.2（2026-09-06）
- **安全**：CSRF 同源校验 + 纯文本字段 XSS 防御
- **修复**：Docker 部署 worker 启动失败、CSP 拦截 CDN、初始化向导 localhost 问题

### v2.4.0（2026-09-04）
- **新增**：Alembic 数据库迁移、Whoosh 全文搜索、Docker 容器化、对象存储 OSS 插件
- **改进**：存储抽象层、搜索索引自动更新、健康检查端点 `/healthz`

### v2.3.0（2026-09-02）
- **新增**：国际化（Flask-Babel）、统计代码插件、英文主题模板
- **改进**：自定义表单插件化、插件独立翻译域

### v2.2.0（2026-08-31）
- **新增**：插件优先架构、主题管理机制、轮播图/产品展示/友情链接插件、REST API

### v2.1.x（2026-08-30）
- **改进**：环境变量前缀统一、项目治理文件、审计日志人性化、伪静态分页

### v2.0（2026-08-29）
- **新增**：RBAC 权限、审计日志、内容工作流、备份恢复、登录安全加固、上传安全、表单通知、SEO 高级设置

> 完整变更历史见 [CHANGELOG.md](./CHANGELOG.md)。

---

## 快速开始

### 环境要求

- Python 3.10+（CI 覆盖 3.10 / 3.11 / 3.12 / 3.13，3.14 实验性）
- 数据库：**MySQL 5.7+** / **PostgreSQL 12+** / **openGauss 7.0**（v3.3.0 起）/ **人大金仓 KingbaseES V9**（v3.3.1 起，pg 兼容模式）/ **达梦 DM8**（v3.3.2 起；生产推荐其一）
- 缓存（可选）：**Redis 6.2+** 或 **openAMDC 1.0.0**（v3.3.0 起，Redis 协议兼容）
- SQLite 仅用于开发/测试（不支持并发写入）

| 后端 | 版本 | 状态 | 说明 |
| --- | --- | --- | --- |
| MySQL / MariaDB | 5.7+ / 11.4 | 完整支持 | 默认生产方案 |
| PostgreSQL | 12+ | 完整支持 | 默认生产方案 |
| openGauss | 7.0.0（实测 7.0.0-RC3） | 已验证（x86_64 + aarch64/鲲鹏） | 需 openGauss 官方 psycopg2 驱动，见 [部署文档](docs/DEPLOY_OPENGAUSS.md) |
| 人大金仓 KingbaseES | V9（实测 V9R1C10） | 已验证（pg 兼容模式，x86_64 + aarch64/鲲鹏） | 复用标准 `psycopg2-binary`，无需专用驱动；备份/恢复需客户端工具，见 [部署文档](docs/DEPLOY_KINGBASE.md) |
| 达梦 DM8 | DM8（x86_64） | 已验证（x86_64 本地验证） | 需安装 `dmpython` + `dmSQLAlchemy`；备份/恢复需 `dexp`/`dimp`，见 [部署文档](docs/DEPLOY_DM.md) |
| PolarDB for PostgreSQL | 15（实测 15.20.5.0） | 已验证（x86_64；aarch64 由 CI 覆盖） | Apache 2.0 开源，复用标准 `psycopg2-binary`；备份/恢复用 `pg_dump`/`psql`，见 [部署文档](docs/DEPLOY_POLARDB.md) |
| SQLite | 3.x | 仅开发/测试 | 不支持并发写入 |
| Redis | 6.2+ | 完整支持 | 配置 `REDIS_URL` 启用 |
| openAMDC | 1.0.0 | 已验证（x86_64 + aarch64/鲲鹏） | 协议兼容，见 [部署文档](docs/DEPLOY_OPENAMDC.md) |
| GBase | 8a / 8c / 8s | 官方不再计划适配 | 不提供官方支持；如需使用，可参照 KingbaseES / 达梦 / PolarDB 文档自行适配，见 [信创适配专题](docs/XINCHUANG_ADAPTATION.md) |

> **授权声明（人大金仓 KingbaseES / 达梦 DM8）**：本项目**仅实现对上述数据库的适配支持**。
> KingbaseES 与达梦 DM8 均为商业软件，其安装包、客户端工具与授权文件（license）
> **需用户自行到官方下载并获取官方授权**（KingbaseES：
> <https://www.kingbase.com.cn/download.html>；达梦：<https://www.dameng.com/>）。
> 本仓库不提供、不分发上述产品的二进制或许可证。

### 信创适配专题

官方在信创数据库方面**已实现并验证 openGauss 7.0**（v3.3.0，x86_64 + aarch64/鲲鹏）、
**人大金仓 KingbaseES V9**（v3.3.1，pg 兼容模式，x86_64 + aarch64/鲲鹏）与
**达梦 DM8**（v3.3.2，x86_64 本地验证），并为 openGauss 与 openAMDC
场景提供 x86_64 / aarch64 多架构镜像；openAMDC 1.0.0 已在双架构完成端到端实测。
南大通用 GBase（8a / 8c / 8s）**官方不再计划适配**，PolarDB-X（MySQL 协议）尚未适配。
至此 v3.3.3 信创数据库适配阶段性收尾；如需自行适配 GBase，可参照已验证后端
（openGauss / KingbaseES / 达梦 DM8 / PolarDB）的代码与部署文档，
[信创适配专题](docs/XINCHUANG_ADAPTATION.md)
提供了按「方言 / 驱动 / URI / 备份工具」分层的参考思路与提交要求。

欢迎所有人提交适配代码、测试、部署文档或实测报告：可先开 Issue 说明数据库产品、
版本、架构与已验证项，再按专题中的接入点提交 PR。未经实测的能力不会被声明为支持。

### 本地开发

```bash
# 克隆代码（三平台镜像同步，任选其一）
git clone https://gitee.com/pollybird/zhycms          # Gitee（国内推荐）
# git clone https://gitcode.com/pollybird/ZhyCMS       # GitCode
# git clone https://github.com/pollybird/zhycms        # GitHub
cd zhycms

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖（国内建议用镜像源）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 启动开发服务器
python run.py
```

浏览器访问 http://127.0.0.1:5000，首次访问自动跳转到 `/admin/setup` 初始化向导。

### Docker 部署

官方镜像已发布到 **Docker Hub**（`pollybird/zhycms`）、**GitHub Container Registry**（`ghcr.io/pollybird/zhycms`）和 **阿里云 ACR**（`crpi-9u7ztjb0thx22k1a.cn-hangzhou.personal.cr.aliyuncs.com/pollybird/zhycms`），当前版本 **v3.3.4**，全部提供 x86_64 / aarch64 多架构，开箱即用，无需本地构建：

```bash
# 1. 配置环境变量
cp docker/.env.example .env
# 编辑 .env 修改 SECRET_KEY 和数据库密码

# 2. 启动（MySQL 8.4，镜像 pollybird/zhycms:mysql）
docker compose -f docker-compose.mysql.yml up -d

# 或启动（PostgreSQL 16，镜像 pollybird/zhycms:postgresql）
docker compose -f docker-compose.postgresql.yml up -d

# 3. 访问 http://localhost:5000 完成初始化
```

> 也可直接拉取镜像：
> - Docker Hub：`docker pull pollybird/zhycms:mysql`（或 `:postgresql` / `:latest` / `:v3.3.4` / `:opengauss` / `:polardb`）
> - GitHub GHCR：`docker pull ghcr.io/pollybird/zhycms:mysql`（或 `:postgresql` / `:latest` / `:v3.3.4` / `:opengauss` / `:polardb`）
> - 阿里云 ACR（国内推荐，速度快）：`docker pull crpi-9u7ztjb0thx22k1a.cn-hangzhou.personal.cr.aliyuncs.com/pollybird/zhycms:mysql`（或 `:postgresql` / `:latest` / `:v3.3.4` / `:opengauss` / `:polardb`）
>
> 四个 tag（`mysql` / `postgresql` / `latest` / `v3.3.4`）指向同一多架构镜像（x86_64 / aarch64），内置 MySQL / PostgreSQL 驱动，通过 `ZHYCMS_DB_URI` 切换数据库。GHCR 镜像默认与 GitHub 账号关联，如需匿名拉取请到 GitHub Packages 页面将可见性改为 Public。

#### 信创部署（openGauss + openAMDC）

```bash
# 1. 配置环境变量（OPENGAUSS_PASSWORD 需含大小写、数字与特殊字符）
cp docker/.env.example .env

# 2. 启动 openGauss 编排（默认启用 openAMDC 缓存，镜像 pollybird/zhycms:opengauss）
docker compose -f docker-compose.opengauss.yml up -d

# 3. 如需改用 Redis（默认使用 openAMDC）
docker compose -f docker-compose.opengauss.yml --profile redis up -d
# 并在 .env 设置 REDIS_URL=redis://redis:6379/0
```

> - openGauss 镜像：`pollybird/opengauss:7.0.0`（x86_64 / aarch64 多架构，内置 openblas 与 libatomic）
> - 应用镜像：`pollybird/zhycms:opengauss`（x86_64 / aarch64 多架构，内置对应架构的 openGauss 驱动）
> - openAMDC 镜像：`pollybird/openamdc:1.0.0`（x86_64 / aarch64 多架构，源码固定 commit 构建，信创专用编排默认启动）
> - 详细步骤与故障速查见 [openGauss 部署](docs/DEPLOY_OPENGAUSS.md)、[openAMDC 部署](docs/DEPLOY_OPENAMDC.md)
> - 验证范围：openGauss 7.0 x86_64 + aarch64（鲲鹏）；openAMDC 1.0.0 x86_64 + aarch64（鲲鹏）；zhycms 应用镜像已完成双架构构建与初始化验证；openAMDC Sentinel 自动切换与 TLS 未经验证

#### 信创部署（人大金仓 KingbaseES）

> **授权声明**：本项目**仅实现对 KingbaseES 的适配支持**。KingbaseES 为商业软件，其 Docker 镜像、客户端工具与授权文件（license）需用户自行到 <https://www.kingbase.com.cn/download.html> 下载并获取官方授权；本仓库不分发其二进制或许可证。

```bash
# 0. 先加载官方 KingbaseES 镜像（镜像与授权请自行从官方获取）
docker load -i KingbaseES_V009R001C010B0004_x86_64_Docker.tar

# 1. 配置环境变量（修改 SECRET_KEY 与 KINGBASE_PASSWORD）
cp docker/.env.example .env

# 2. 启动 KingbaseES 编排（默认启用 openAMDC 缓存；应用镜像复用默认 pollybird/zhycms:latest）
docker compose -f docker-compose.kingbase.yml up -d

# 3. 可选搜索；如需改用 Redis（默认使用 openAMDC）
docker compose -f docker-compose.kingbase.yml --profile meilisearch up -d
docker compose -f docker-compose.kingbase.yml --profile redis up -d
# 并在 .env 设置 REDIS_URL=redis://redis:6379/0
```

> - 应用镜像：`pollybird/zhycms:latest`（默认镜像已含 `psycopg2-binary`；KingbaseES 为 PG 协议兼容，连接与迁移无需专用驱动或新镜像变体）
> - KingbaseES 镜像：需用户自行 `docker load` 官方镜像（默认镜像名 `kingbase_v009r001c010b0004_single_x86:v1`，可用 `.env` 中 `KINGBASE_IMAGE` 覆盖）
> - 仅支持 `DB_MODE=pg`；默认端口 `54321`、管理账号 `system`；编排会自动创建应用库 `zhycms`，并把客户端工具（`sys_dump` / `ksql`）挂载给应用
> - 备份/恢复密码经 `KINGBASE_PASSWORD` 环境变量注入（ksql / sys_dump 不识别 `PGPASSWORD`）；裸机部署需自行配置 `ZHYCMS_KINGBASE_BIN` 与 `LD_LIBRARY_PATH`
> - 详细步骤、连接参数、备份恢复与故障速查见 [KingbaseES 部署](docs/DEPLOY_KINGBASE.md)
> - 验证范围：KingbaseES V9R1C10 x86_64 + aarch64（鲲鹏，pg 模式）；oracle / mysql / sqlserver 兼容模式未验证

如需本地构建或使用 MariaDB 方案，仍可用通用编排文件：

```bash
docker compose --profile mysql up -d      # 本地构建 + MySQL
docker compose --profile mariadb up -d    # 本地构建 + MariaDB 11.4
docker compose --profile postgres up -d   # 本地构建 + PostgreSQL
```

容器启动时自动执行数据库迁移、编译 i18n 翻译并启动 gunicorn。`instance/` 和上传目录通过 volume 持久化。

### 生产部署

```bash
# 方式一：直接运行
ZHYCMS_ENV=production ZHYCMS_SECRET_KEY=your-secret python run.py

# 方式二：gunicorn（推荐）
gunicorn -w 4 -b 0.0.0.0:5000 "run:app"

# 方式三：Docker（见上文）
```

> 生产环境请务必使用 MySQL/PostgreSQL，并设置强密钥。

---

## 目录结构

```
zhycms/
├── app/
│   ├── admin/              # 后台模块（栏目、文章、用户、角色、审计、备份、设置等）
│   ├── frontend/           # 前台模块
│   │   └── templates/
│   │       └── themes/     # 前台主题目录（含 css/js/images/fonts）
│   ├── models/             # 数据模型（用户、RBAC、审计、工作流、备份、上传等）
│   ├── translations/       # 国际化翻译文件
│   ├── utils/              # 工具模块（上传、通知、备份、存储、主题等）
│   ├── static/             # 静态资源
│   ├── __init__.py         # 应用工厂
│   ├── config.py           # 配置
│   ├── builder/            # 页面构建器（组件注册表/Schema/渲染器/默认布局/插件片段合并）
│   ├── plugin_system.py    # 插件运行时
│   ├── plugin_api.py       # PluginBase 基类
│   └── extensions.py       # 扩展初始化
├── plugins/                # 插件目录
│   ├── banner/             # 轮播图插件
│   ├── product/            # 产品展示插件
│   ├── recruit/            # 招聘管理插件
│   ├── tutorial/           # 教程中心插件
│   ├── friend_link/        # 友情链接插件
│   ├── form/               # 自定义表单插件
│   ├── analytics/          # 统计代码插件
│   ├── oss_storage/        # 对象存储插件
│   ├── auto_translate/     # 一键翻译插件
│   ├── db_migrator/        # 数据库迁移插件（默认不启用）
│   └── member/             # 前台用户中心插件（社区插件）
├── migrations/             # Alembic 数据库迁移脚本
├── docker/                 # Docker 部署辅助文件（含 openamdc/、opengauss/ 镜像构建）
├── instance/               # 实例数据（数据库、配置、备份、索引等）
├── requirements.txt        # 核心依赖
├── requirements-prod.txt   # 生产依赖（gunicorn + gevent）
├── requirements-opengauss.txt  # 可选：openGauss 官方 SQLAlchemy 方言
├── Dockerfile              # 多阶段构建镜像（可选打入 openGauss 驱动）
├── docker-compose.yml      # 通用编排文件（--profile mysql/mariadb/postgres/openamdc，本地构建）
├── docker-compose.mysql.yml      # MySQL 独立编排（拉取 pollybird/zhycms:mysql）
├── docker-compose.postgresql.yml # PostgreSQL 独立编排（拉取 pollybird/zhycms:postgresql）
├── docker-compose.opengauss.yml  # openGauss 独立编排（拉取 pollybird/zhycms:opengauss）
├── wsgi.py                 # 生产 WSGI 入口
├── run.py                  # 开发启动入口
└── babel.cfg               # pybabel 提取配置
```

---

## 核心功能详解

### 主题系统

- **多主题组织**：前台模板按主题目录存放，后台一键切换，即时生效
- **主题管理**：支持上传 `.zip/.tar.gz/.tgz` 压缩包，8 步安全校验后解压；支持打包下载跨站复用
- **栏目级模板**：每个栏目可独立指定列表页/内容页/单页模板
- **安全兜底**：启用主题缺失必备模板时自动回退 `default` 主题，杜绝白屏
- **静态资源隔离**：每套主题独立拥有 `css/js/images/fonts` 子目录

### 页面构建器

- **拖拽建页（v3.0.0）**：原生 HTML5 拖拽编辑器 + iframe 内服务端真实渲染，覆盖首页/单页/列表页/文章详情页四作用域，无 Node 构建链
- **24 个内置组件**：布局（section/grid 等）、基础（标题/文本/富文本/图片/按钮等）、数据（文章列表/轮播/友情链接/联系卡等）三组；草稿/发布/修订回滚，匿名访客只见已发布版
- **默认布局三层合并**：当前主题 fixture → 核心回退 → 已启用插件贡献片段；8 套官方主题必备首页布局，第三方主题上传时校验自带 builder JSON
- **双语与可见性**：文案中英 Tab、节点语言白名单与会员限定；桌面/平板/手机三端预览与全屏预览
- **插件扩展**：`get_builder_widgets()` 注册组件、`get_builder_layouts()` 贡献默认布局片段（启用强校验、卸载引用拦截）；轮播图/产品/招聘/教程启用即开箱即用
- **双轨兜底**：「构建器为主、手写模板永久兜底」，只有已发布布局的页面才走构建器，老站升级零行为变化

### 插件机制

- **零侵入扩展**：`plugins/<slug>/` 目录 + `manifest.json` + `PluginBase` 基类
- **运行时门控**：以 `site_settings.enabled_plugins` 控制启停，禁用即隐身、不删数据
- **能力扩展**：可扩展后台页面、前台路由/模板函数、数据表、REST API、sitemap、全站搜索内容贡献（SearchProvider）、审计模块、演示数据钩子、页面构建器组件（`get_builder_widgets()`）与默认布局片段（`get_builder_layouts()`）
- **依赖/继承/最低版本校验（v2.6.4）**：`manifest.json` 支持 `requires` / `extends` / `min_core_version`，启用时强校验、禁用时反向依赖校验，详见 [PLUGIN_DEPENDENCIES.md](PLUGIN_DEPENDENCIES.md)
- **官方内置插件**：轮播图、产品展示、友情链接、自定义表单、统计代码、对象存储、一键翻译、数据库迁移（8 个，不可卸载；数据库迁移默认不启用）
- **社区插件**：前台用户中心（member）、招聘管理（recruit）、教程中心（tutorial），随包分发、可卸载
- **构建器开箱即用（v3.0.0）**：轮播图/产品/招聘/教程四个内容型插件启用后，向页面构建器贡献组件与首页默认布局片段，新建首页自动带上对应区块

### 国际化

- **界面文案国际化（v2.3）**：Flask-Babel 全站覆盖，前台 + 后台界面文案支持中英文切换
- **内容级多语言（v2.5）**：文章/栏目/碎片/产品/表单/岗位/友情链接支持多语言翻译表，前台 Jinja 全局 `t(obj, field)` 按当前 locale 取翻译，无翻译 fallback 默认语言
- **结构化字段多语言（v2.5.2）**：产品「规格参数」（JSON）与岗位「部门/工作地点/薪资待遇」支持按语言维护，翻译留空回退默认语言
- **多级 Locale 选择**：URL 参数 → Session → Cookie → Accept-Language → 默认语种
- **插件独立翻译域**：每个插件可在 `plugins/<slug>/translations/` 自带译文；启动时缺失/过期的核心 `.mo` 自动编译
- **默认关闭**：不影响现有站点，开启后即时生效
- **英文主题**：内置 `default_en`、`manufacturing_en` 两套英文主题模板

### 数据库迁移

- **Flask-Migrate（Alembic）**：统一管理 schema 版本，支持 `upgrade/downgrade`
- **旧站自动升级**：v2.3.x 及更早站点覆盖代码后首次启动自动 stamp baseline，仅执行增量迁移
- **插件迁移支持**：插件可通过 `get_migration_files()` 自带迁移脚本，纳入 Alembic 统一管理
- **SQLite 兼容**：`render_as_batch=True` 绕过 SQLite ALTER TABLE 限制
- **数据库类型一键迁移（v3.1.0）**：内置插件 `db_migrator`（默认不启用），后台把 SQLite 开发库整体迁移到 MySQL/PostgreSQL——目标库建表、按外键依赖逐表复制（单事务失败整体回滚）、PostgreSQL 自动重置自增序列、同步 Alembic 版本号；目标库非空保护、连接测试、支持迁移后免重启热切换引擎

### 全文搜索

- **默认引擎**：Tantivy（Rust 内核，tantivy-py 绑定，v3.1.4 起）+ pkuseg 中文分词（spacy-pkuseg）
- **可选后端**：Meilisearch（大型站点推荐）
- **索引范围**：文章（标题 + 正文去 HTML + 摘要 + 栏目名）+ 插件内容（产品、招聘岗位）
- **多语言检索（v2.5.1）**：按当前语言分索引检索，未翻译内容回退默认语言
- **插件内容接入（v2.5.2）**：插件通过 `get_search_provider()`（SearchProvider 协议）接入全站搜索，产品规格参数、岗位部门/地点/薪资均可检索
- **自动更新**：文章与插件内容保存/删除时通过钩子自动更新索引，文章批量操作（发布/撤回/删除/归档/移动/提交审核）逐篇同步更新
- **故障回退**：索引异常或零命中时自动降级为 SQL LIKE 查询（同步覆盖插件内容），搜索不中断
- **高亮与分页**：6 套主题搜索模板均支持关键词高亮和分页

### 对象存储

- **存储抽象层**：`app/utils/storage.py` 统一驱动协议，所有上传走同一入口
- **支持厂商**：阿里云 OSS、腾讯云 COS、七牛云 Kodo（SDK 可选安装、懒加载）
- **默认本地**：未配置时行为与旧版完全一致，零侵入
- **一键迁移**：本地历史文件批量上传云端，自动改写文章正文/封面等链接为云域名
- **安全设计**：上传失败显式报错、禁用插件自动回退本地、备份文件强制留本地

### 安全体系

| 层面 | 措施 |
|------|------|
| **访问控制** | 自定义后台路由前缀（即时生效）、RBAC 权限、栏目级内容授权 |
| **登录安全** | 连续失败锁定、图形验证码、异地 IP 登录提醒 |
| **上传安全** | 后缀白名单 + MIME 双重校验、SHA-256 内容去重、图片自动压缩 |
| **输入安全** | 路径穿越拦截、审计日志详情 HTML 转义防 XSS |
| **运维安全** | 审计日志全量留痕、备份恢复前自动释放连接池 |

### SEO 与性能

- **伪静态**：`/{slug}.html`、`/{slug}-{page}.html`、`/article-{id}.html`
- **Sitemap**：栏目与文章独立配置更新频率/优先级，插件 URL 自动聚合
- **Robots.txt**：后台可视化编辑，支持追加自定义规则
- **页面缓存**：Flask-Caching，首页/栏目/文章独立 TTL，内容变更自动清理；配置 `REDIS_URL` 后自动切 RedisCache，支撑多实例
- **Redis 缓存后端（v2.5）**：设置环境变量 `REDIS_URL` 后，Flask-Caching 切 RedisCache、Flask-Session 存 Redis，多实例共享缓存与 Session；后台「系统设置 → Redis 缓存」展示运行状态
- **图片优化**：自动压缩、缩略图生成、默认 ALT 注入

### 内容工作流

- **状态流转**：草稿 → 待审核 → 已发布 / 已驳回
- **版本管理**：每次保存自动生成快照，支持对比差异与一键还原
- **权限分离**：无发布权限的作者提交后进入审核队列，编辑审核后发布

### 审计日志

- **覆盖范围**：登录/登出、配置变更、内容 CRUD、备份恢复、权限调整、插件/主题操作
- **检索维度**：按模块、操作类型、操作人、时间范围筛选
- **详情人性化**：键名/配置项中文翻译、状态语义化、变更对照（旧值 → 新值）、ID 自动显示名称

---

## 开发者文档

深入开发与运维排障请阅读仓库 `docs/` 目录下的权威文档：

| 文档 | 内容 |
| --- | --- |
| [docs/PAGE_BUILDER.md](docs/PAGE_BUILDER.md) | 页面构建器手册：用户指南、组件开发 API、默认布局三层解析与插件贡献片段约定 |
| [docs/PLUGIN_DEV.md](docs/PLUGIN_DEV.md) | 插件开发手册：目录结构、manifest.json 字段、PluginBase API、钩子与数据模型规范，含可直接复制的最小示例插件 |
| [docs/THEME_TEMPLATE_API.md](docs/THEME_TEMPLATE_API.md) | 主题模板开发 API：模板继承链、全局变量、Jinja 过滤器与函数、页面上下文 |
| [docs/OPERATIONS_FAQ.md](docs/OPERATIONS_FAQ.md) | 运维故障排查 FAQ：常见报错、数据库迁移失败处理、缓存/主题/插件/伪静态/Docker 排障速查 |
| [docs/DEPLOY_OPENGAUSS.md](docs/DEPLOY_OPENGAUSS.md) | openGauss 部署：两种拓扑、建库建号、pg_hba、驱动安装、备份工具与故障速查 |
| [docs/DEPLOY_KINGBASE.md](docs/DEPLOY_KINGBASE.md) | KingbaseES（人大金仓）部署：镜像加载、Compose 编排、连接参数、备份恢复（KINGBASE_PASSWORD）、限制与授权声明 |
| [docs/DEPLOY_DM.md](docs/DEPLOY_DM.md) | 达梦 DM8 部署：驱动安装、实例与 Schema 准备、向导填写、dexp/dimp 备份恢复、限制与授权声明 |
| [docs/DEPLOY_OPENAMDC.md](docs/DEPLOY_OPENAMDC.md) | openAMDC 部署：镜像构建、Compose 用法、配置项、与 Redis 差异、哨兵与 TLS 说明 |
| [docs/XINCHUANG_ADAPTATION.md](docs/XINCHUANG_ADAPTATION.md) | 信创数据库适配专题：openGauss、KingbaseES、达梦 DM8 与 PolarDB for PostgreSQL 已实现；GBase 官方不再计划适配（仅作自行适配参考） |
| [docs/DEPLOY_POLARDB.md](docs/DEPLOY_POLARDB.md) | PolarDB for PostgreSQL 15 部署指南（Docker Compose / 外部实例、备份恢复、故障速查） |
| [PLUGIN_DEPENDENCIES.md](PLUGIN_DEPENDENCIES.md) | 插件依赖 / 继承 / 最低核心版本校验详解 |

在线 Wiki 见 Gitee / GitCode / GitHub 仓库 Wiki 页（三平台镜像同步）。

---

## 升级指南

### v3.3.0 → v3.3.1

覆盖代码 + 重启应用即可，**无数据库迁移、无新增必需依赖**（迁移仍为 `0020`，`requirements.txt` 不变）。MySQL / PostgreSQL / openGauss / Redis 部署行为不变。

- 切换 KingbaseES：先 `docker load` 官方 KingbaseES 镜像，再 `docker compose -f docker-compose.kingbase.yml up -d`（或把 `ZHYCMS_DB_URI` 改为 `kingbase+psycopg2://system:密码@主机:54321/库名`，在初始化向导中选择「KingbaseES（信创推荐）」）；首次启动自动迁移至 `0020`，`/healthz?detail=1` 返回 `db_dialect=kingbase`
- 备份/恢复：KingbaseES 客户端工具（`ksql` / `sys_dump`）需配置 `ZHYCMS_KINGBASE_BIN` 与 `LD_LIBRARY_PATH`（compose 已自动挂载），密码经 `KINGBASE_PASSWORD` 注入
- 回退：改回原数据库 URI 后重启即可，无结构变更
- 详见 [UPGRADE.md](./UPGRADE.md)、[KingbaseES 部署](docs/DEPLOY_KINGBASE.md)
- 授权声明：KingbaseES 为商业软件，镜像与授权文件需用户自行到 <https://www.kingbase.com.cn/download.html> 下载并获取官方授权

### v3.2.12 → v3.3.0

覆盖代码 + 重启应用即可，**无数据库迁移、无新增必需依赖**（迁移仍为 `0020`）。MySQL/PostgreSQL/Redis 部署行为不变。

- 切换 openGauss：安装 openGauss 官方 psycopg2 驱动，将 `ZHYCMS_DB_URI` 改为 `opengauss+psycopg2://...`，或使用 `docker compose -f docker-compose.opengauss.yml up -d`
- 切换 openAMDC：启动 openAMDC 并把 `REDIS_URL` 指向它，应用自动识别后端类型
- 回退：改回原数据库 URI / `REDIS_URL` 后重启即可，无结构变更
- 详见 [UPGRADE.md](./UPGRADE.md)、[openGauss 部署](docs/DEPLOY_OPENGAUSS.md)、[openAMDC 部署](docs/DEPLOY_OPENAMDC.md)

### v2.6.x → v3.0.0

覆盖代码 + `pip install -r requirements.txt` + 重启应用即可。首次启动自动执行 Alembic 迁移 `0009`（新增 `builder_pages` / `builder_revisions` 两张表），无新增 Python 依赖。

- 升级后所有页面默认仍走手写模板，行为与 v2.6.4 完全一致；到后台「页面构建」创建并**发布**布局后对应页面才切换为构建器渲染
- 启用轮播图/产品/招聘/教程插件的站点，新建首页时默认布局会自动增补对应区块（已有草稿与已发布页不受影响）
- 详见 [UPGRADE.md](./UPGRADE.md) 与 [docs/PAGE_BUILDER.md](docs/PAGE_BUILDER.md)

### v2.5.x → v2.5.2

覆盖代码 + `pip install -r requirements.txt` + 重启应用即可。

- 首次启动自动编译核心翻译 `.mo`（英文界面立即生效）并自动执行 Alembic 迁移 `0007`（产品规格参数/岗位结构化字段多语言列）
- 后台「插件管理」启用「一键翻译」并配置服务商密钥即可使用
- 全站搜索已包含产品/岗位：升级后到「系统设置 → 搜索设置」点一次「重建索引」立即将存量产品/岗位纳入检索（新保存内容会自动同步）
- 启用「产品展示」「招聘管理」的站点，插件随核心升级至 1.1.0，历史数据与翻译无缝保留

### v2.4.x → v2.5.0

覆盖代码 + `pip install -r requirements.txt` + `flask db upgrade` 即可。新增 7 张翻译表（迁移 `0005` + `0006`），无破坏性变更。

- 启用多语言：后台「系统设置 → 国际化」开启，配置默认语言与可用语种
- 启用 Redis：设置环境变量 `REDIS_URL=redis://127.0.0.1:6379/0` 后重启应用
- 未启用 i18n / Redis 的站点，行为与 v2.4.2 完全一致

### v2.3.x → v2.4.0

仅覆盖代码 + `pip install -r requirements.txt` 即可。首次启动自动 stamp Alembic baseline 并执行增量迁移，无需手动操作。

- 全文搜索默认 Tantivy，升级后首次启动自动后台重建索引（重建期间回退 SQL LIKE），无需手动操作
- 对象存储插件升级后自动启用，不配置凭证不产生云端调用

### v2.2.x → v2.3.0

仅覆盖代码即可。自定义表单已并入插件体系，升级后首次启动自动启用表单插件一次，旧数据与审计日志无缝保留。

### v1.1 → v2.0+

1. 备份站点目录与数据库（**必做**）
2. 停服并更新代码：`git fetch && git checkout v2.4.0`
3. 更新依赖：`pip install -r requirements.txt`
4. 执行迁移：`.venv/bin/python scripts/upgrade_v2.py`（v1.1 专用）
5. 启动服务，按 [UPGRADE.md](./UPGRADE.md) 逐项核对

> 升级涉及新建表、补列、数据回填，**仅启动程序无法完成迁移**。

---

## Star 支持

如果 ZhyCMS 帮你快速搭起了站点，欢迎在 [GitHub](https://github.com/pollybird/zhycms) / [Gitee](https://gitee.com/pollybird/zhycms) / [GitCode](https://gitcode.com/pollybird/ZhyCMS) 点个 **Star**，这是对项目最直接的鼓励；也欢迎提 Issue、发 PR 一起共建。

---

## 参与贡献

欢迎报告问题与提交 PR！

- 请先阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)（环境搭建/开发规范/提交规范）
- 变更历史见 [CHANGELOG.md](./CHANGELOG.md)
- 社区规范见 [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)
- 漏洞报告请勿使用公开 Issue，详见 [SECURITY.md](./SECURITY.md)

---

## 许可证

本项目自 **v3.2.7** 起基于 [木兰宽松许可证第2版（Mulan PSL v2）](http://license.coscl.org.cn/MulanPSL2) 开源，许可证全文见 [LICENSE](./LICENSE)；**v3.2.6 及之前版本**仍基于 Apache License 2.0 发布，全文见 [LICENSE-APACHE-2.0](./LICENSE-APACHE-2.0)。

随项目分发的前端第三方组件（CKEditor 5、Bootstrap、Font Awesome 等）仍受各自许可证约束，版权声明、许可证全文与署名要求见 [THIRD_PARTY_NOTICES](./THIRD_PARTY_NOTICES)。

Copyright 2026 泰州姜堰钟毓信息技术有限公司
