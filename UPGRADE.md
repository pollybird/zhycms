# zhycms 升级迁移指南

本文件包含各版本升级迁移指引。**v2.5.2 → v2.6.0 无破坏性变更，覆盖代码重启即可**；**v2.5.x → v2.5.2 自动迁移 `0007`**；**v2.4.x → v2.5.0 执行 Alembic 迁移 0005+0006 建翻译表，覆盖代码 + 装依赖即可**；运行 v1.1（及更早 1.x）版本的站点升级到 v2.0 涉及大量结构变更，请完整阅读本文后半部分后再操作。

---

## v2.5.2 → v2.6.0 升级（2026-09-10）

v2.6.0 是**工程化完善**版本：新增发布 Checklist、pytest 测试脚手架 + GitHub Actions CI、统一异常处理、常量治理。**无数据库结构变更**，覆盖代码重启即可。

### 一、升级步骤

```bash
# 0. 备份站点目录与数据库（常规操作，建议保留）
# 1. 停服并更新代码到 v2.6.0
git pull    # 或下载 v2.6.0 发布包覆盖

# 2. 无新增 Python 依赖，启动服务即可
python run.py
# 或 gunicorn -w 4 -b 0.0.0.0:5000 "wsgi:app"
```

### 二、行为变化与兼容性

| 项目 | v2.5.2 | v2.6.0 | 升级影响 |
| --- | --- | --- | --- |
| 数据库结构 | 0007 | 无迁移（0007） | **无变化** |
| 统一异常处理 | 前台 404/500 + Werkzeug 默认 | `app/errors.py` 三协议分发（403/404/500 + JSON/后台/主题） | 后台 403/404 不再显示 Werkzeug 默认英文页 |
| 常量治理 | 散落字面量 | `app/constants.py` 统一命名空间 + CI 门禁 | 代码引用不变（向后兼容重导出） |
| 测试 | 无 | `tests/` + pytest + GitHub Actions CI | 开发流程可选 `pytest` |
| `CMS_VERSION` | `2.5.2` | `2.6.0` | 后台页脚版本号自动更新 |
| 新增依赖 | — | 无（开发依赖 `requirements-dev.txt` 仅本地/CI 用） | — |

### 三、升级后验证

- [ ] 应用启动无异常，后台页脚显示版本号 `2.6.0`
- [ ] 后台 `/admin` 下 403/404 页面为后台风格（不再 Werkzeug 默认英文页）
- [ ] 前台不存在路径 → 主题 404 页；CSRF 拒绝 → 主题 403 页（新增）
- [ ] `/api/v1/` 错误返回 JSON 格式
- [ ] （可选）`pip install -r requirements-dev.txt && pytest` 本地测试全绿
- [ ] （可选）`python scripts/check_constants.py` 零违规

---

## v2.5.x → v2.5.2 升级（2026-09-09）

v2.5.2 新增 **一键翻译插件**、**全站搜索插件内容接入（SearchProvider）**，并将 **插件结构化内容扩展为多语言**（产品规格参数、岗位部门/工作地点/薪资待遇）。**无破坏性变更**——仅执行迁移 `0007` 为两张既有翻译表补列（`product_translations.specs`、`recruit_job_translations.department/location/salary`），不修改任何既有数据；不使用相关功能的站点行为与 v2.5.1 完全一致。

### 一、升级步骤

```bash
# 0. 备份站点目录与数据库（常规操作，建议保留）
# 1. 停服并更新代码到 v2.5.2
git pull    # 或下载 v2.5.2 发布包覆盖

# 2. 无新增 Python 依赖，启动服务即可（首次启动自动完成迁移 0007）
python run.py
# 或 gunicorn -w 4 -b 0.0.0.0:5000 "wsgi:app"
```

> 首次启动会自动编译核心翻译 `.mo`（修复英文界面文案缺失）并自动执行 Alembic 迁移 `0007`，无需手动运行任何命令。

### 二、行为变化与兼容性

| 项目 | v2.5.x | v2.5.2 | 升级影响 |
| --- | --- | --- | --- |
| 数据库结构 | 0006 | 0007（两张翻译表补列） | **自动迁移**，不动既有数据 |
| 界面翻译 `.mo` | 需手工 `pybabel compile` | 首次启动自动编译缺失/过期的 `.mo` | 英文界面立即生效 |
| 全站搜索 | 仅文章 | 新增插件内容（产品、招聘岗位） | 需点一次「重建索引」纳入存量内容 |
| 插件多语言 | 标题/简介/正文/SEO | 新增产品规格参数、岗位部门/地点/薪资 | 翻译留空回退默认语言 |
| `CMS_VERSION` | `2.5.1` | `2.5.2` | 后台页脚版本号自动更新 |
| 官方插件版本 | product/recruit `1.0.0` | `1.1.0` | 随核心升级，历史数据无缝保留 |
| 新增依赖 | — | 无 | — |

### 三、升级后可选操作

1. **一键翻译**（新插件）：后台「插件管理」启用「一键翻译」→ 配置服务商与 API 密钥（百度/有道/Google/DeepSeek）→ 编辑内容时在多语言 Tab 点「一键翻译」。
2. **搜索纳入插件内容**：后台「系统设置 → 搜索设置」点一次「重建索引」，存量产品/岗位立即进入全文检索（之后保存/删除/上下架自动同步，不重建也可用，产品保存时会触发增量重建）。
3. **录入结构化字段翻译**：产品编辑页多语言 Tab 可直接编辑该语言规格参数；岗位编辑页可录入英文部门/地点/薪资，留空自动回退默认语言。

### 四、升级后验证清单

- [ ] 应用启动日志出现 Alembic 迁移信息（`0007`）与翻译 `.mo` 编译日志，无报错
- [ ] 后台页脚显示版本号 `2.5.2`
- [ ] 英文界面（`?lang=en`）核心文案正常翻译；前台 `/search?q=无结果&lang=en` 未命中提示为英文
- [ ] 英文状态下搜索产品英文名（如 `CNC`）能命中英文内容
- [ ] 后台插件管理可见「一键翻译」，配置服务商后测试可用
- [ ] 产品编辑页多语言 Tab 出现各语言规格参数编辑器，保存后前台按语言显示
- [ ] 岗位编辑页可录入英文部门/地点/薪资，前台与搜索按语言返回
- [ ] （可选）「重建索引」后索引统计含产品/岗位文档
- [ ] （可选）`flask db current` 显示当前版本为 `0007`

---

## v2.4.x → v2.5.0 升级（2026-09-07）

v2.5.0 引入 **内容级多语言（i18n 2.0）** 和 **Redis 缓存后端 + 服务端 Session** 两大能力。**无破坏性变更**——新增 7 张翻译关联表（迁移 `0005` + `0006`），主表字段不变；未启用 i18n / Redis 的站点行为与 v2.4.2 完全一致。

### 一、升级步骤

```bash
# 0. 备份站点目录与数据库（常规操作，建议保留）
# 1. 停服并更新代码到 v2.5.0
git pull    # 或下载 v2.5.0 发布包覆盖

# 2. 更新依赖（新增 redis、Flask-Session）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 执行数据库迁移（新建 7 张翻译表）
flask db upgrade
# 或直接启动应用，create_app 启动时自动执行增量迁移

# 4. 启动服务
python run.py
# 或 gunicorn -w 4 -b 0.0.0.0:5000 "wsgi:app"
```

### 二、行为变化与兼容性

| 项目 | v2.4.x | v2.5.0 | 升级影响 |
| --- | --- | --- | --- |
| 数据库结构 | 0004 | 0005 + 0006（7 张翻译表） | **自动迁移**，主表无变更 |
| 内容多语言 | 界面文案级（Flask-Babel） | 内容级（翻译表 + `t()` 全局函数） | 默认关闭，开启后编辑内容时录入翻译 |
| 缓存后端 | SimpleCache | SimpleCache 或 RedisCache（环境变量驱动） | 未设 `REDIS_URL` 时行为不变 |
| Session 存储 | Cookie | Cookie 或 Redis（环境变量驱动） | 未设 `REDIS_URL` 时行为不变 |
| `CMS_VERSION` | `2.4.2` | `2.5.0` | 后台页脚版本号自动更新 |
| 新增依赖 | — | `redis>=5.0,<6.0`、`Flask-Session>=0.8,<1.0` | `pip install -r requirements.txt` 即可 |

### 三、启用内容级多语言（可选）

1. 进入后台 **系统设置 → 国际化**（权限 `system:settings`）。
2. 开启 i18n 总开关，配置默认语种（如 `zh`）与可用语种清单（如 `zh,en,ja`）。
3. 编辑文章/栏目/碎片/产品/表单/岗位/友情链接时，在「多语言版本」Tab 切换语种录入翻译。
4. 前台模板使用 `{{ t(obj, field) }}` 按当前 locale 取翻译，无翻译时 fallback 默认语言。
5. `slug` 不随语言变化，URL 保持稳定。

> 翻译表设计：主表保留默认语言字段（冗余），翻译表仅存非默认语言。查不到翻译时 fallback 主表默认语言，不会出现空白内容。

### 四、启用 Redis 缓存（可选）

v2.5.0 支持 Redis 作为缓存后端与服务端 Session 存储，适合多实例负载均衡场景。**未启用 Redis 不影响站点正常运行，单机部署零依赖。**

启用方式：

```bash
# 方式一：环境变量（源码部署）
export REDIS_URL=redis://127.0.0.1:6379/0
python run.py

# 方式二：Docker 部署
bash docker/install.sh   # 交互选择启用 Redis，自动写入 .env
docker compose --profile mysql --profile redis up -d
```

应用启动时自动检测 `REDIS_URL`：有值且 Redis 可达 → 启用 RedisCache + 服务端 Session；否则回退 SimpleCache + Cookie Session。后台「系统设置 → Redis 缓存」展示当前运行状态（只读，不提供手动开关）。

> Redis 连接地址格式：`redis://[:password@]host:port/db`，如 `redis://:mypassword@127.0.0.1:6379/0`。

### 五、升级后验证清单

- [ ] 应用启动日志中出现 `Alembic` 迁移信息（`0005` / `0006`），无报错
- [ ] 后台页脚显示版本号 `2.5.0`
- [ ] 前台首页/栏目页/文章页正常访问，内容与升级前一致
- [ ] 后台文章/栏目/碎片编辑页可见「多语言版本」Tab（i18n 开启后）
- [ ] 前台 `?lang=en` 切换语言后内容正确切换（录入翻译后）
- [ ] 后台「系统设置 → Redis 缓存」页面可访问，状态展示正确
- [ ] （可选）设置 `REDIS_URL` 后重启，后台 Redis 状态页显示「已启用」
- [ ] （可选）`flask db current` 显示当前版本为最新 revision（`0006`）

---

## v2.3.x → v2.4.0 升级（2026-09-04）

v2.4.0 引入 **Alembic 数据库迁移框架**、**全文搜索引擎**、**Docker 容器化**、**对象存储 OSS 插件** 四大能力。**旧站覆盖代码后首次启动自动 stamp baseline 并执行增量迁移，无需手动运行任何脚本**；全文搜索默认 Whoosh（零外部依赖），首次使用前自动回退 SQL LIKE 保证可用性；**文件存储默认仍为本地磁盘，对象存储插件升级后自动启用但不配凭证不产生任何云端调用，零行为变化**。

### 一、升级步骤

```bash
# 0. 备份站点目录与数据库（常规操作，建议保留）
# 1. 停服并更新代码到 v2.4.0
git fetch && git checkout v2.4.0    # 或下载 v2.4.0 发布包覆盖

# 2. 更新依赖（新增 Flask-Migrate、Whoosh、jieba；生产环境另装 requirements-prod.txt）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
# 生产部署（Docker/gunicorn）还需：
pip install -r requirements-prod.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 启动服务（首次启动自动完成 Alembic 迁移，无需手动操作）
.venv/bin/python run.py
# 或 gunicorn -w 4 -b 0.0.0.0:5000 "wsgi:app"
```

> 若从 v1.1/v2.0/v2.1.x 升级到 v2.4.0：先按本文后半部分运行 `scripts/upgrade_v2.py` 完成 v2.0 结构迁移，再覆盖到 v2.4.0 代码；首次启动同样会自动 stamp Alembic baseline。

### 二、自动迁移说明

应用工厂 `create_app()` 启动时按以下顺序自动处理数据库 schema：

1. **检测旧库**：若数据库中存在核心表（`users`、`articles` 等）但**不存在 `alembic_version` 表**，判定为旧站升级，自动执行 `flask db stamp head`（标记 baseline 为 `0001`，对应 v2.3.0 完整 schema）。
2. **执行增量迁移**：`flask db upgrade` 依次执行 `0002`（新建 `search_index` 元数据表）、`0003`（幂等插入 6 个搜索设置默认值，已存在的键跳过，兼容 MySQL 不支持 `INSERT OR IGNORE` 语法）、`0004`（给 `uploaded_files` 增加 `storage` 列并幂等写入 `storage_driver=local` 设置，默认值 `local` 保证历史文件归属正确）。
3. **新装站点**：初始化向导完成后首次启动会执行 `flask db stamp head` + `flask db upgrade`，把 `db.create_all()` 建出的表纳入 Alembic 版本管理。

迁移日志会写入应用日志（`INFO` 级别），迁移失败时启动中止并打印详细错误。

### 三、行为变化与兼容性

| 项目 | v2.3.x | v2.4.0 | 升级影响 |
| --- | --- | --- | --- |
| 数据库结构 | 由 `db.create_all()` 建 | 由 Alembic 迁移管理 | **自动迁移**，无需手动操作 |
| 前台 `/search` 路由 | SQL LIKE 模糊查询 | 优先 Whoosh 索引，故障回退 SQL LIKE | 未建索引前自动回退，不影响可用性 |
| 文章保存/删除 | 仅清缓存 | 同时更新搜索索引 | 索引更新独立于缓存开关 |
| 文件上传存储 | 直接写本地磁盘 | 走存储抽象层，默认本地驱动 | **本地行为不变**；切云端才产生云调用 |
| 官方插件 | 5 个 | 6 个（新增 `oss_storage`，自动启用一次） | 仅增加后台菜单，不配置不产生云端调用 |
| `CMS_VERSION` | `2.3.0` | `2.4.0` | 后台页脚版本号自动更新 |
| 新增依赖 | — | `Flask-Migrate`、`Whoosh`、`jieba` | `pip install -r requirements.txt` 即可 |
| 云 SDK（可选） | — | `oss2` / `cos-python-sdk-v5` / `qiniu` | **仅使用对应云存储时才需安装**，不装不影响任何现有功能 |
| 生产部署 | gunicorn 可选 | gunicorn + gevent（`requirements-prod.txt`） | 仅 Docker/生产部署需要，开发环境可选 |

### 四、全文搜索初始化

升级后前台 `/search` 在未建索引前自动走 SQL LIKE，**不影响搜索可用性**。如需启用 Whoosh 全文索引获得更好性能与相关度排序：

1. 进入后台 **系统设置 → 搜索设置**（权限 `system:settings`）。
2. 确认引擎选择为 `whoosh`（默认），点击 **「重建索引」** 按钮，系统会遍历全部已发布文章写入 `instance/search_index/` 索引。
3. 重建完成后，前台搜索结果按相关度排序，并支持关键词高亮（6 套主题搜索模板已内置 `|highlight(keyword)` 过滤器）。

> 大型站点（文章数 > 10000）重建索引可能耗时较长，建议在低峰期执行；也可切换为 Meilisearch 后端获得更高性能。

### 五、对象存储（可选）

v2.4.0 新增官方内置插件 `oss_storage`，支持**阿里云 OSS / 腾讯云 COS / 七牛云 Kodo**。升级后插件自动启用一次，但存储驱动保持 `local`（本地磁盘），**不配凭证不会产生任何云端调用**，不上云的站点无需任何操作。

如需切换到云端对象存储：

```bash
# 1. 安装对应云厂商 SDK（按需安装，均为可选依赖）
pip install oss2 -i https://pypi.tuna.tsinghua.edu.cn/simple                          # 阿里云 OSS
pip install cos-python-sdk-v5 -i https://pypi.tuna.tsinghua.edu.cn/simple            # 腾讯云 COS
pip install qiniu -i https://pypi.tuna.tsinghua.edu.cn/simple                        # 七牛云 Kodo
```

2. 在云厂商控制台创建 Bucket（建议设为**私有读写 + CDN 回源**或公共读，地域就近选择），并在 **RAM / 访问管理**中创建**子账号**，仅授予目标 Bucket 的读写权限（不要使用主账号 AK）。
3. 进入后台 **系统设置 → 对象存储**（权限 `oss_storage:manage`），选择云厂商、填写 Endpoint / Region / Bucket / AK / SK（七牛还需绑定 CDN 域名），点击「连接测试」通过后保存。
4. 切换驱动后**新上传的文件**直接入云；历史本地文件可在同一页面点击「本地文件迁移到云端」：先预览（待传文件数、磁盘缺失数、内容引用链接数），再一键执行——文件逐个上传（已存在自动跳过，可中断重入），文章正文/封面、碎片、自定义字段、站点 Logo 等内容中的 `/static/uploads/` 链接自动改写为云域名。**本地原文件保留不删**，确认无问题后可自行清理。

注意事项：

- **禁用插件**会自动把存储驱动重置回本地（后续上传回到本地磁盘，历史云端文件 URL 不受影响）。
- **备份恢复**功能上传的备份包强制存本地磁盘，不进云端。
- Docker 部署如需云 SDK，可基于官方镜像自行构建：在 Dockerfile 中追加 `RUN pip install oss2`（或其他两家 SDK）。

### 六、Docker 部署（可选）

v2.4.0 新增 Docker 容器化部署方案，适合新站点或迁移到容器环境：

```bash
# 1. 配置环境变量
cp docker/.env.example .env
# 编辑 .env 修改 ZHYCMS_SECRET_KEY 和数据库密码

# 2. 启动（MySQL，推荐生产）
docker compose --profile mysql up -d

# 或启动（PostgreSQL）
docker compose --profile postgres up -d

# 3. 访问 http://localhost:5000 完成初始化向导
```

容器启动时 entrypoint.sh 自动执行：数据库迁移（`flask db upgrade`）→ 恢复演示图片 → 编译 i18n 翻译 → 启动 gunicorn。`/healthz` 端点供 docker compose healthcheck 与负载均衡探针使用。

> 现有裸机部署的站点无需迁移到 Docker，v2.4.0 代码在裸机环境同样正常运行。

### 七、升级后验证清单

- [ ] 应用启动日志中出现 `Alembic` 迁移信息（`stamp` 或 `upgrade`），无报错
- [ ] 后台页脚显示版本号 `2.4.0`
- [ ] 前台 `/search` 搜索功能正常（未建索引前走 SQL LIKE，建索引后走 Whoosh）
- [ ] 文章保存/删除后再次搜索能命中最新内容（索引自动更新）
- [ ] 后台「系统设置 → 搜索设置」页可访问，点击「重建索引」后索引统计正常
- [ ] 上传文章配图/附件正常、图片可访问（本地存储行为与升级前一致）
- [ ] 后台「系统设置 → 对象存储」页可访问，驱动显示为「本地存储」
- [ ] （可选）切换云端驱动：配置凭证 → 连接测试通过 → 保存 → 新上传文件 URL 为云域名
- [ ] （可选）Docker 部署：`docker compose --profile mysql up -d` 后 `curl http://localhost:5000/healthz` 返回 `{"status":"ok"}`
- [ ] （可选）`flask db current` 显示当前版本为最新 revision（`0004`）

---

## v2.2.x → v2.3.0 升级（2026-09-01）

v2.3.0 新增国际化（Flask-Babel）、第三方统计代码插件，并将**自定义表单由核心功能转为官方内置插件**。**无数据库结构变更，v2.2.x 直接覆盖代码即可升级**，无需运行迁移脚本。

### 一、升级步骤

```bash
# 0. 备份站点目录与数据库（常规操作，建议保留）
# 1. 停服并更新代码到 v2.3.0
git fetch && git checkout v2.3.0    # 或下载 v2.3.0 发布包覆盖

# 2. 更新依赖（新增 Flask-Babel）
pip install -r requirements.txt

# 3. 编译翻译文件（国际化英文界面需要；不编译也不影响中文默认行为）
pybabel compile -d app/translations

# 4. 启动服务
```

> `.mo` 编译产物不入版本库（已加入 `.gitignore`），部署时需执行一次 `pybabel compile -d app/translations`；若未安装 pybabel，`pip install Babel` 即可。

### 二、行为变化与兼容性

| 项目 | v2.2.x | v2.3.0 | 升级影响 |
| --- | --- | --- | --- |
| 数据库结构 | — | 无变更 | 无 |
| 表单后台管理 | 核心路由 `/<admin>/forms` | 插件路由，**路径不变** | 无（首次启动自动启用表单插件一次） |
| 表单前台提交 | `/form/<slug>` | **路径不变** | 无 |
| 表单数据表 | `forms` / `form_fields` / `form_submissions` / `form_submission_values` | **表名不变** | 旧表单数据、提交记录、历史审计日志无缝保留 |
| 表单通知配置 | `form_notify_*` / `notify_email_*` / `notify_wework_*` 设置键 | **设置键不变** | 邮件/企业微信通知配置无缝保留 |
| 国际化 | 不存在 | 默认**关闭**（`i18n_enable=0`） | 关闭时全站按中文渲染，与 v2.2.0 行为完全一致 |
| 新增依赖 | — | `Flask-Babel>=4.0,<5.0` | `pip install -r requirements.txt` 即可 |

### 三、自动迁移说明

- **老站升级**：v2.2.x 升级后**首次启动自动启用表单插件一次**（`form_plugin_migrated` Setting 标记门控），表单菜单、前台提交、通知立即恢复可用；之后可在「插件管理」随时禁用。
- **新装站点**：初始化向导写入迁移标记，表单插件按向导勾选状态启用。

### 四、升级后验证清单

- [ ] 后台侧边栏可见「自定义表单」菜单（插件注册，图标正常），进入 `/forms` 列表页正常
- [ ] 旧表单数据与提交记录完整保留，导出 Excel 正常
- [ ] 前台访问 `/form/<slug>` 提交一条测试表单，通知渠道（如已配置）正常推送
- [ ] 审计日志中历史表单操作记录正常显示（模块翻译无异常）
- [ ] 插件管理页可见 `form`、`analytics` 两个内置插件，状态正常无「加载失败」标红
- [ ] （可选）启用统计代码插件，粘贴百度统计/GA 代码，前台查看源码确认注入 `</head>` 前
- [ ] （可选）「系统设置 → 国际化」开启 i18n 并添加英文，验证后台顶栏与前台语言切换器；中文站点保持关闭即可

---

## zhycms v1.1 → v2.0 升级迁移指南

本指南帮助运行 v1.1（及更早 1.x）版本的站点安全升级到 **v2.0**。v2.0 新增了 RBAC 权限、审计日志、内容工作流、备份恢复、登录安全加固、上传安全、表单消息通知、SEO 与站点性能八大模块，涉及**新建 9 张数据表、旧表补 12 列、新增 4 个依赖与一批新配置项**，请完整阅读本文后再操作。

---

## 一、升级前必读：四个关键变化

### 1. 用户权限语义变化（最重要）

v1.1 中 `users.is_super` 默认为 `True`，**所有用户都是超级管理员**；v2.0 中默认改为 `False`，并引入角色权限体系（预设 4 个角色：超级管理员、内容审核员、内容编辑、只读查看员）。

- **升级不会改动任何用户的 `is_super` 值**：v1.1 已创建的用户升级后仍拥有全部权限。
- 升级完成、登录后台后，请立即进入 **用户权限 → 用户列表** 审查：非管理员账号应将「超级管理员」关闭，并为其分配合适角色（如「内容编辑」）。
- 升级后新建的用户默认无任何权限，必须显式绑定角色才能操作后台。

### 2. 文章状态从开关升级为工作流

v1.1 文章只有 `is_enabled` 启用/停用开关；v2.0 引入 `status` 工作流状态（草稿 draft → 待审核 pending → 已发布 published / 已驳回 rejected）。

- 迁移时自动回填：`is_enabled=1 → published`，`is_enabled=0 → draft`（前台展示效果与 v1.1 完全一致）。
- `is_enabled` 字段保留并与 status 同步维护，旧的自定义模板/查询不受影响。
- 升级后新建文章默认为**草稿**；无发布权限的用户提交后进入待审核。

### 3. 登录安全机制默认启用

- 连续失败 5 次（可配置）账号自动锁定 10 分钟（可配置）。
- 登录页增加图形验证码（所有版本用户均需输入）。
- 异地 IP 登录会展示一次性提醒横幅。
- 升级前若存在被暴力尝试的弱密码账号，建议升级时一并修改密码。

### 4. 上传行为变化（仅影响新上传）

后缀 + MIME 双重校验、SHA-256 去重、图片压缩与缩略图**默认开启**，已有文件不受影响；伪装成图片的脚本文件将无法再上传。

---

## 二、兼容性说明

| 项目 | v1.1 | v2.0 | 升级影响 |
| --- | --- | --- | --- |
| Python | 3.9+ | 3.9+ | 无 |
| SQLite / MySQL / PostgreSQL | 支持 | 支持 | 无（迁移脚本三种库通用） |
| Flask / Werkzeug | 3.0.3+ | 3.0.3+ | 无 |
| 已有主题模板 | — | 兼容 | 列表模板分页链接建议改用 `frontend_pager_url`（可选，见下文第五节） |
| 已有自定义字段/表单/碎片 | — | 兼容 | 无 |
| `instance/db_config.json` | — | 兼容 | 无需改动 |
| `instance/admin_config.json` | — | 兼容 | 无需改动（后台前缀修改 v2.0 起即时生效） |
| 环境变量前缀 | `ZHOCMS_*` | `ZHYCMS_*`（v2.1 起统一，与项目名一致） | 旧前缀仍被识别（自动回退），**建议将部署脚本/systemd 配置中的 `ZHOCMS_ENV`、`ZHOCMS_SECRET_KEY`、`ZHOCMS_DB_URI` 改为新前缀 `ZHYCMS_*`**，未来版本将移除旧前缀支持 |

**新增依赖 4 个**（`requirements.txt`）：`Flask-Caching`（页面缓存）、`APScheduler`（计划任务）、`requests`（企业微信通知）、`python-magic`（MIME 校验，Linux 需系统库 `libmagic`：Debian/Ubuntu `apt install libmagic1`，CentOS `yum install file-libs`；Windows 建议 `pip install python-magic-bin`）。

---

## 三、升级步骤（推荐：自动迁移脚本）

### 第 0 步：备份（必做）

- 备份整个站点目录与数据库（v1.1 可用 `mysqldump`，SQLite 直接复制 `instance/zhycms.db`）。
- v2.0 起可在后台「备份运维」中一键备份，但**本次升级的备份必须在升级前完成**。

### 第 1 步：停服并更新代码

```bash
# 停止运行中的服务（gunicorn/systemd 等）
cd /path/to/zhycms
git fetch && git checkout v2.0     # 或下载 v2.0 发布包覆盖
```

### 第 2 步：更新依赖

```bash
source .venv/bin/activate
pip install -r requirements.txt
# Debian/Ubuntu 需补系统库（python-magic 依赖）：
sudo apt install -y libmagic1
```

### 第 3 步：执行迁移脚本（幂等，可重复运行）

```bash
# 使用 instance/db_config.json 中配置的数据库
.venv/bin/python scripts/upgrade_v2.py

# 或显式指定数据库 URI（v2.1 起前缀统一为 ZHYCMS_，旧前缀 ZHOCMS_ 仍兼容）
ZHYCMS_DB_URI='mysql+pymysql://user:pass@127.0.0.1:3306/zhycms?charset=utf8mb4' \
    .venv/bin/python scripts/upgrade_v2.py
```

脚本会依次完成（全部幂等，中断后重跑安全）：

1. 创建 9 张新表（roles、permissions、role_permissions、user_roles、user_column_permissions、audit_logs、article_versions、backup_records、uploaded_files）；
2. 为旧表补列：`users` +4 列（is_active_flag、login_fail_count、locked_until、last_login_city）、`articles` +6 列（status、reject_reason、reviewed_by、reviewed_at、created_by、updated_by）、`login_logs` +2 列（user_id、city）；
3. **回填 `articles.status`**（按 is_enabled 映射，通过 `schema_migrations` 版本记录保证只执行一次，重跑不会覆盖运行期数据）；
4. 创建 `articles.status` 索引；
5. 初始化 RBAC 预设角色与权限点；
6. 输出自检报告（列/表/数据分布/角色数量）。

> **注意**：仅启动程序无法正确完成迁移——`db.create_all()` 只建新表、不会给旧表加列；而 `ALTER ADD COLUMN ... DEFAULT` 会把旧行全部填默认值，若不执行脚本的数据回填步骤，原本隐藏的文章会被错误公开。请务必运行本脚本。

### 第 4 步：启动服务并核对自检报告

```bash
.venv/bin/python run.py          # 开发模式
# 或 gunicorn -w 4 -b 0.0.0.0:5000 "run:app"
```

---

## 四、手工迁移（不使用脚本时）

若受环境限制无法运行脚本，可按顺序手工执行以下 SQL（**MySQL 示例**；SQLite 将 `TINYINT(1)` 换成 `INTEGER`、其余相同），然后启动一次服务让 `create_all` 建新表：

```sql
-- 1. 旧表补列（逐条执行，若列已存在会报 1060 错误，跳过即可）
ALTER TABLE users     ADD COLUMN is_active_flag   TINYINT(1)  NOT NULL DEFAULT 1;
ALTER TABLE users     ADD COLUMN login_fail_count INT         NOT NULL DEFAULT 0;
ALTER TABLE users     ADD COLUMN locked_until     DATETIME    NULL;
ALTER TABLE users     ADD COLUMN last_login_city  VARCHAR(64) NULL;

ALTER TABLE articles  ADD COLUMN status        VARCHAR(16) NOT NULL DEFAULT 'published';
ALTER TABLE articles  ADD COLUMN reject_reason VARCHAR(500) NULL;
ALTER TABLE articles  ADD COLUMN reviewed_by   INT NULL;
ALTER TABLE articles  ADD COLUMN reviewed_at   DATETIME NULL;
ALTER TABLE articles  ADD COLUMN created_by    INT NULL;
ALTER TABLE articles  ADD COLUMN updated_by    INT NULL;

ALTER TABLE login_logs ADD COLUMN user_id INT NULL;
ALTER TABLE login_logs ADD COLUMN city    VARCHAR(64) NULL;

-- 2. 数据回填（必须在补列后立即执行！）
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(32) PRIMARY KEY, applied_at DATETIME);
UPDATE articles SET status = CASE WHEN is_enabled = 1
    THEN 'published' ELSE 'draft' END;
INSERT INTO schema_migrations (version, applied_at) VALUES ('v2.0_articles_status', NOW());

-- 3. 状态索引
CREATE INDEX ix_articles_status ON articles(status);
-- 4. 新表由首次启动的 db.create_all() 自动创建，预设角色自动初始化
```

**警告**：第 2 步不可省略，也不可重复执行（重跑会把运行期已修改的文章状态覆盖回去）；脚本方式通过版本记录规避了该风险，推荐使用脚本。

---

## 五、升级后验证清单

- [ ] 访问首页/栏目页/文章页正常，原本隐藏的文章（is_enabled=0）**仍然不可见**
- [ ] 后台用原账号登录正常（需输入图形验证码）
- [ ] 连续输错 5 次密码后账号被锁定，10 分钟后自动解锁
- [ ] **用户权限 → 用户列表**：审查 is_super 用户，关闭非管理员的超管标志并分配角色
- [ ] 用户权限 → 角色与权限：可见 4 个预设角色与权限点
- [ ] 新建一篇文章：默认为草稿，能提交审核/发布
- [ ] 文章编辑页有「版本历史」；修改文章后前台刷新立即更新（缓存自动清理）
- [ ] 上传一张 JPG：生成缩略图且体积缩小；上传伪装 .jpg 的脚本文件被拒绝
- [ ] 系统设置 → 后台安全：修改后台前缀，**无需重启**新前缀立即生效
- [ ] 系统设置 → SEO 高级：开启伪静态后 `/栏目slug.html`、`/栏目slug-2.html`、`/文章id.html` 均可访问，分页链接自动变为伪静态格式
- [ ] 系统设置 → 消息通知：配置 SMTP 后提交一条测试表单可收到邮件
- [ ] 备份运维 → 备份列表：执行一次 MySQL 备份并下载验证
- [ ] 自定义主题的列表模板：分页链接建议替换为 `frontend_pager_url(column, page)`（不替换也可正常工作，但无法享受伪静态分页）：

```jinja
<a href="{{ frontend_pager_url(column, pagination.prev_num or 1) }}">&laquo; 上一页</a>
{% for p in pagination.iter_pages() %}
  <a href="{{ frontend_pager_url(column, p) }}">{{ p }}</a>
{% endfor %}
```

---

## 六、回滚方案

升级失败或需要回退时：

1. 停止服务；
2. 恢复第 0 步备份的代码目录与数据库（v2.0 新增的表/列留在库中不影响 v1.1 运行，v1.1 代码不感知这些结构；也可用备份直接还原）；
3. 重启服务，确认站点恢复 v1.1 行为。

> 由于迁移不删除任何既有数据、不修改任何业务数据（除 articles.status 回填外），且 v1.1 结构是 v2.0 的子集，多数情况下**直接用 v1.1 代码启动即可回滚**。

---

## 七、附录：v2.0 结构变更明细

**新增数据表（9）**：`roles`、`permissions`、`role_permissions`、`user_roles`、`user_column_permissions`、`audit_logs`、`article_versions`、`backup_records`、`uploaded_files`；另建迁移记录表 `schema_migrations`。

**旧表新增列（12）**：

| 表 | 列 | 类型 | 说明 |
| --- | --- | --- | --- |
| users | is_active_flag | BOOLEAN NOT NULL DEFAULT 1 | 账号启用/禁用 |
| users | login_fail_count | INTEGER NOT NULL DEFAULT 0 | 连续登录失败次数 |
| users | locked_until | DATETIME NULL | 锁定截止时间 |
| users | last_login_city | VARCHAR(64) NULL | 上次登录城市（异地提醒） |
| articles | status | VARCHAR(16) NOT NULL DEFAULT 'published' | 工作流状态 |
| articles | reject_reason | VARCHAR(500) NULL | 最近驳回原因 |
| articles | reviewed_by / reviewed_at | INT / DATETIME NULL | 最近审核人与时间 |
| articles | created_by / updated_by | INT NULL | 创建人/最近编辑人 |
| login_logs | user_id | INT NULL | 关联用户 |
| login_logs | city | VARCHAR(64) NULL | 登录 IP 归属地 |

**新增配置项**（存于 `Setting.DEFAULTS`，旧库无需插入数据，自动生效默认值）：登录安全（login_max_fail/login_lock_minutes/login_abnormal_city_alert）、上传安全（upload_enable_mime_check/upload_enable_dedup/upload_image_*）、消息通知（form_notify_enable/form_notify_channels/notify_email_*/notify_wework_*）、SEO（seo_rewrite_enable/seo_sitemap_*/seo_robots_custom/seo_image_alt_default）、页面缓存（cache_enable/cache_ttl_*）。

**新增依赖（4）**：Flask-Caching、APScheduler、requests、python-magic（系统依赖 libmagic）。

---

如遇问题，请优先运行 `scripts/upgrade_v2.py` 查看自检报告，或提交 Issue 附带脚本完整输出。
