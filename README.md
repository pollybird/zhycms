# ZhyCMS

一个基于 Flask 的轻量级企业内容管理系统，内置多主题模板引擎、栏目级模板选择、自定义字段、表单收集、SEO 优化、全文搜索、对象存储等能力，适合搭建企业官网、资讯门户、产品展示站等。

**当前版本：v2.5.0**（内容级多语言 + Redis 缓存与 Session：详见 [CHANGELOG](CHANGELOG.md)）

---

## 目录

- [简介](#简介)
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
  - [插件机制](#插件机制)
  - [国际化](#国际化)
  - [数据库迁移](#数据库迁移)
  - [全文搜索](#全文搜索)
  - [对象存储](#对象存储)
  - [安全体系](#安全体系)
  - [SEO 与性能](#seo-与性能)
  - [内容工作流](#内容工作流)
  - [审计日志](#审计日志)
- [升级指南](#升级指南)
- [参与贡献](#参与贡献)
- [许可证](#许可证)

---

## 简介

ZhyCMS 采用 **Flask + SQLAlchemy + Jinja2** 技术栈，以「插件优先、主题驱动」为架构理念，在保持轻量的同时覆盖企业建站的核心需求：

- 前台：多主题切换、栏目级模板选择、伪静态、全文搜索、多语言
- 后台：RBAC 权限、内容工作流、审计日志、备份恢复、表单收集
- 扩展：插件零侵入扩展、REST API、对象存储、统计代码

---

## 核心特性

| 特性 | 说明 | 版本 |
|------|------|------|
| **多主题模板系统** | 前台模板按主题组织，后台一键切换；内置 6 套主题（含 2 套英文主题） | v1.0 |
| **主题管理** | 上传/启用/删除/打包下载主题压缩包，缺失模板自动兜底 | v2.2 |
| **插件机制** | `plugins/<slug>/` 零侵入扩展，启停即时生效、无需重启 | v2.2 |
| **国际化（i18n）** | Flask-Babel 界面文案 + 内容级多语言翻译表（文章/栏目/碎片/产品/表单/岗位/友情链接） | v2.3/v2.5 |
| **Redis 缓存** | 环境变量自动检测，RedisCache + 服务端 Session，支撑多实例负载均衡 | v2.5 |
| **数据库迁移** | Flask-Migrate（Alembic）管理 schema 版本，支持回滚 | v2.4 |
| **全文搜索** | 默认 Whoosh + jieba 中文分词，可选 Meilisearch | v2.4 |
| **对象存储 OSS** | 阿里云 OSS / 腾讯云 COS / 七牛云 Kodo，一键迁移本地文件上云 | v2.4 |
| **Docker 部署** | 多阶段构建 + docker-compose，MySQL/PostgreSQL 一键启动 | v2.4 |
| **REST API** | `/api/v1/` 只读端点，Token 鉴权 + CORS，适合小程序/Headless | v2.2 |
| **RBAC 权限** | 角色/权限点两级模型，菜单与按钮级授权，栏目级内容粒度 | v2.0 |
| **内容工作流** | 草稿 → 待审核 → 已发布/已驳回，版本快照与对比还原 | v2.0 |
| **审计日志** | 登录、配置变更、内容 CRUD 等全量留痕，支持多维度检索 | v2.0 |
| **SEO 优化** | 伪静态、sitemap、robots.txt、页面缓存、图片默认 ALT | v2.0 |
| **表单收集** | 可视化表单设计，提交后邮件/企业微信实时通知 | v2.0 |
| **备份恢复** | MySQL/PostgreSQL/JSON 三种方式，一键备份与恢复 | v2.0 |

---

## 版本速览

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

- Python 3.9+
- 数据库：**MySQL 5.7+** 或 **PostgreSQL 12+**（生产推荐）
- SQLite 仅用于开发/测试（不支持并发写入）

### 本地开发

```bash
# 克隆代码
git clone https://gitee.com/pollybird/zhycms
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

```bash
# 1. 配置环境变量
cp docker/.env.example .env
# 编辑 .env 修改密钥和数据库密码

# 2. 启动（MySQL）
docker compose --profile mysql up -d

# 或启动（PostgreSQL）
docker compose --profile postgres up -d

# 3. 访问 http://localhost:5000 完成初始化
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
│   ├── plugin_system.py    # 插件运行时
│   ├── plugin_api.py       # PluginBase 基类
│   └── extensions.py       # 扩展初始化
├── plugins/                # 插件目录
│   ├── banner/             # 轮播图插件
│   ├── product/            # 产品展示插件
│   ├── friend_link/        # 友情链接插件
│   ├── form/               # 自定义表单插件
│   ├── analytics/          # 统计代码插件
│   └── oss_storage/        # 对象存储插件
├── migrations/             # Alembic 数据库迁移脚本
├── docker/                 # Docker 部署辅助文件
├── instance/               # 实例数据（数据库、配置、备份、索引等）
├── requirements.txt        # 核心依赖
├── requirements-prod.txt   # 生产依赖（gunicorn + gevent）
├── Dockerfile              # 多阶段构建镜像
├── docker-compose.yml      # 编排文件
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

### 插件机制

- **零侵入扩展**：`plugins/<slug>/` 目录 + `manifest.json` + `PluginBase` 基类
- **运行时门控**：以 `site_settings.enabled_plugins` 控制启停，禁用即隐身、不删数据
- **能力扩展**：可扩展后台页面、前台路由/模板函数、数据表、REST API、sitemap、审计模块、演示数据钩子
- **官方内置插件**：轮播图、产品展示、友情链接、自定义表单、统计代码、对象存储

### 国际化

- **界面文案国际化（v2.3）**：Flask-Babel 全站覆盖，前台 + 后台界面文案支持中英文切换
- **内容级多语言（v2.5）**：文章/栏目/碎片/产品/表单/岗位/友情链接支持多语言翻译表，前台 Jinja 全局 `t(obj, field)` 按当前 locale 取翻译，无翻译 fallback 默认语言
- **多级 Locale 选择**：URL 参数 → Session → Cookie → Accept-Language → 默认语种
- **插件独立翻译域**：每个插件可在 `plugins/<slug>/translations/` 自带译文
- **默认关闭**：不影响现有站点，开启后即时生效
- **英文主题**：内置 `default_en`、`manufacturing_en` 两套英文主题模板

### 数据库迁移

- **Flask-Migrate（Alembic）**：统一管理 schema 版本，支持 `upgrade/downgrade`
- **旧站自动升级**：v2.3.x 及更早站点覆盖代码后首次启动自动 stamp baseline，仅执行增量迁移
- **插件迁移支持**：插件可通过 `get_migration_files()` 自带迁移脚本，纳入 Alembic 统一管理
- **SQLite 兼容**：`render_as_batch=True` 绕过 SQLite ALTER TABLE 限制

### 全文搜索

- **默认引擎**：Whoosh（纯 Python，零外部依赖）+ jieba 中文分词
- **可选后端**：Meilisearch（大型站点推荐）
- **索引范围**：标题 + 正文（去 HTML）+ 摘要 + 栏目名
- **自动更新**：文章保存/删除时通过钩子自动更新索引
- **故障回退**：Whoosh 异常时自动降级为 SQL LIKE 查询，搜索不中断
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

## 升级指南

### v2.4.x → v2.5.0

覆盖代码 + `pip install -r requirements.txt` + `flask db upgrade` 即可。新增 7 张翻译表（迁移 `0005` + `0006`），无破坏性变更。

- 启用多语言：后台「系统设置 → 国际化」开启，配置默认语言与可用语种
- 启用 Redis：设置环境变量 `REDIS_URL=redis://127.0.0.1:6379/0` 后重启应用
- 未启用 i18n / Redis 的站点，行为与 v2.4.2 完全一致

### v2.3.x → v2.4.0

仅覆盖代码 + `pip install -r requirements.txt` 即可。首次启动自动 stamp Alembic baseline 并执行增量迁移，无需手动操作。

- 全文搜索默认 Whoosh，首次使用需在后台「搜索设置」点击「重建索引」
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

## 参与贡献

欢迎报告问题与提交 PR！

- 请先阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)（环境搭建/开发规范/提交规范）
- 变更历史见 [CHANGELOG.md](./CHANGELOG.md)
- 社区规范见 [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)
- 漏洞报告请勿使用公开 Issue，详见 [SECURITY.md](./SECURITY.md)

---

## 许可证

本项目基于 [Apache License 2.0](http://www.apache.org/licenses/LICENSE-2.0) 开源。

Copyright 2026 泰州姜堰钟毓信息技术有限公司
