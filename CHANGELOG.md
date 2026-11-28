# 更新日志（Changelog）

本项目的所有显著变更都记录在本文件中。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。

> **许可证说明**：自 v3.2.7 起，本项目许可证由 Apache License 2.0 变更为木兰宽松许可证第2版（Mulan PSL v2），全文见 [LICENSE](./LICENSE)；v3.2.6 及之前版本仍按 Apache License 2.0 提供，全文见 [LICENSE-APACHE-2.0](./LICENSE-APACHE-2.0)。

## [3.3.4] - 2026-11-28

**缺陷修复与站群增强版**：修复文章保存超时与子域标签重复误报，新增单站点多独立域名。数据库迁移 `0020 → 0021`，`requirements.txt` 无新增依赖。

### Fixed

- **文章保存超时（504 / upstream prematurely closed）**：`flask-caching 2.5` 没有 `delete_pattern`，`clear_content_cache()` 实际走 `cache.clear()`；cachelib 的 Redis 实现是 `KEYS <prefix>*` 取回全部键后再执行单条大 `DEL`，缓存键较多时会长时间阻塞 Redis 并把全部键加载进内存，超过 gunicorn `--timeout 120` 后 worker 被终止，nginx 记录 `upstream prematurely closed connection`。改为 `purge_cache_prefix()`：Redis 用 `SCAN MATCH` + 每 500 个键一批 `DEL`，只清理当前站点 `frontend/site<sid>/` 前缀，不再波及其它站点缓存；站点设置、主题切换、页面构建器的 `cache.clear()` 同步替换。缓存客户端增加 `socket_connect_timeout=3` / `socket_timeout=5`，前端缓存键只保留 `page` 白名单参数（随机 `utm_*` 不再制造海量唯一键）。保存链路新增 Markdown 渲染 / commit / 版本快照 / 清缓存+索引分段耗时日志，以及 ≥3s 的慢请求日志。
- **子域标签重复误报**：`sites.subdomain` 去掉全局唯一约束（迁移 `0021` 将唯一索引改为普通索引），改为按“所属域名作用域”校验与解析。站点 A(a.com, www) 与站点 B(b.com, www) 可同时存在，`www.a.com` / `www.b.com` 分别访问两个站点；解析优先级为「精确域名（主域/附加域）→ 域名作用域子域 → 全站唯一子域回落」，父域已归属站点时不再被其它站点的同名子域抢占。

### Added

- **单站点多独立域名**：新增 `site_domains` 表（`SiteDomain` 模型）保存附加域名，`sites.domain` 仍为主域名；后台站点表单新增“附加域名”多行输入（每行一个，最多 10 个），主域名与附加域名统一做格式/全局唯一/子域作用域校验。请求解析、`site_hostnames`（nginx `server_name`）、站点列表/部署页、站点备份导出导入、克隆冲突去重、`/api/v1/sites` 与回收站快照均支持多域名。

### 迁移与测试

- 迁移 `0021`：新建 `site_domains`（含 `domain` 唯一约束、`site_id` 索引、级联删除），`ix_sites_subdomain` 改为普通索引；降级前预检重复子域。
- 新增 `tests/test_cache_purge_v334.py`（SCAN 分批清理、不再全量清空、缓存键白名单）与 `tests/test_sites_v334.py`（子域作用域解析、多域名保存/解析/部署主机名、迁移往返）；更新 `test_sites_v321` / `test_sites_v322` 既有断言。

## [3.3.3] - 2026-11-28

**信创适配增量版**：新增 **PolarDB for PostgreSQL 15** 数据库支持。无数据库迁移（仍为 `0020`），`requirements.txt` 无新增依赖。

> **许可说明**：PolarDB for PostgreSQL 源码遵循 Apache License 2.0，官方提供可自由拉取与分发的 Docker 镜像；本仓库直接提供 `docker-compose.polardb.yml` 并引用 `polardb/polardb_pg_binary:15`。

### Added

- **PolarDB for PostgreSQL 支持**：新增 `app/utils/dialects/polardb.py`，`PolarDBPGDialect` 继承 `PGDialect_psycopg2`，注册 `polardb_pg` / `polardb_pg.psycopg2` 与 `PolarDBPGImpl`（Alembic）。PolarDB 的 `version()` 返回 `PostgreSQL 15.x (PolarDB ...)`，标准 PG 方言可解析；解析失败时回退 `SHOW server_version`。连接串形如 `polardb_pg+psycopg2://user:pwd@host:5432/zhycms`，复用 `psycopg2-binary`，无新增 Python 依赖。
- **连接与引擎参数**：`dbconfig.py` 增加默认端口 `5432` 与驱动 `polardb_pg+psycopg2`；驱动缺失 / 方言缺失 / 认证失败 / 连接拒绝分别给出中文提示；`build_engine_options()` 为其配置连接池与 `connect_args={'connect_timeout': 5, 'application_name': 'zhycms'}`。
- **初始化向导与显示**：向导新增「PolarDB for PostgreSQL」选项（默认端口 5432）；`_current_db_label()` 显示「PolarDB for PostgreSQL」，`/healthz?detail=1` 返回 `db_dialect=polardb_pg`。
- **备份与恢复**：`backup_utils` 增加 `polardb_pg` 分支——备份用 `pg_dump`（`PGPASSWORD` 环境变量传密码），恢复用 `psql`；工具路径支持 `ZHYCMS_POLARDB_BIN`（bin 目录或 `POLARDB_HOME`）与 `ZHYCMS_DB_DUMP_BIN_DIR`。
- **Docker 编排**：新增 `docker-compose.polardb.yml` 与 `docker/polardb/init.sh`（幂等 initdb、创建应用账号/数据库、`scram-sha-256` 认证、优雅启停）；`Dockerfile` 新增 `INSTALL_PG_CLIENT` 构建参数，`pollybird/zhycms:polardb` 内置 `postgresql-client` 以支持原生备份恢复。
- **信创编排默认缓存**：`docker-compose.opengauss.yml` / `docker-compose.kingbase.yml` / `docker-compose.polardb.yml` 默认启动并连接 **openAMDC**（`REDIS_URL=redis://openamdc:6379/0`），Redis 保留为 `--profile redis` 可选项；KingbaseES 编排补齐 openAMDC 服务。
- **测试与 CI**：新增 `tests/test_polardb.py`（离线覆盖方言注册 / 版本解析 / URI / 引擎参数 / 错误提示 / 备份恢复命令 / 向导；live 由 `ZHYCMS_TEST_POLARDB_URL` 门控，默认跳过）；`compat.yml` 新增 `polardb` job（x86_64 / aarch64 迁移、备份恢复冒烟）。
- **文档**：新增 [docs/DEPLOY_POLARDB.md](docs/DEPLOY_POLARDB.md)；更新 [docs/XINCHUANG_ADAPTATION.md](docs/XINCHUANG_ADAPTATION.md)、README 与 `UPGRADE.md`。

### Removed

- **移除 `wiki.html`**：早期项目提供的离线单页手册不再维护，从仓库删除；相关版本门禁、发布清单、CI 路径过滤与文档引用已同步清理，在线 Wiki 与 `docs/` 文档保持可用。

### Notes

- **信创适配阶段性收尾**：v3.3.3 后官方不再新增信创数据库适配计划；**GBase（8a / 8c / 8s）官方不再计划适配**，[信创适配专题](docs/XINCHUANG_ADAPTATION.md) 中相关章节仅作自行适配参考，可参照 openGauss / KingbaseES / 达梦 DM8 / PolarDB 的代码、测试与部署文档自行完成。
- 仅覆盖 **PolarDB for PostgreSQL**；PolarDB-X（MySQL 协议）与云上集群版管理接口不在本次范围。
- 目标主版本为 15；`pg_dump` / `psql` 需与服务端同主版本，其它主版本镜像未做端到端验证。

## [3.3.2] - 2026-11-27

**信创适配增量版**：新增 **达梦 DM8** 数据库支持。无数据库迁移（仍为 `0020`），`requirements.txt` 无新增必需依赖（达梦部署另装 `requirements-dm.txt`）。

> **授权声明**：本项目仅实现对达梦 DM8 的适配支持。达梦 DM8 为商业软件，其安装包、客户端工具与授权文件（license）需用户自行到 <https://www.dameng.com/> 下载并获取官方授权；本仓库不提供、不分发达梦的二进制或许可证。

### Added

- **达梦 DM8 数据库支持**：新增 `app/utils/dialects/dm.py`，基于 PyPI `dmpython 2.6.1` + `dmSQLAlchemy 2.0.17` 注册 `dm` / `dm.dmPython` 方言。上游方言只在 `autoincrement is True` 时生成 `IDENTITY`，本项目模型使用 `Column(Integer, primary_key=True)`（默认 `'auto'`），故方言层覆盖 `get_column_specification`，为单列整数主键补齐 `IDENTITY(1, 1)`（复合主键与显式 `autoincrement=False` 不补）；注册 `DMImpl` 供 Alembic 按 `dialect.name` 查表。连接串形如 `dm+dmPython://user:password@host:5236/SCHEMA`（database 段即 Schema）。
- **连接与引擎参数**：`dbconfig.py` 增加默认端口 `5236` 与驱动 `dm+dmPython`；驱动缺失 / 方言缺失 / 认证失败 / 连接拒绝分别给出中文提示；`build_engine_options()` 对 DM 使用连接池与 `connect_args={'connection_timeout': 5}`（dmPython 参数名，不使用 PostgreSQL 的 `connect_timeout` / `application_name`）。
- **初始化向导与显示**：向导新增「达梦 DM8（信创推荐）」选项，未填端口回退 `5236`，并提示「数据库名」对应 Schema；`_current_db_label()` 显示「达梦 DM8」，`/healthz?detail=1` 返回 `db_dialect=dm`。
- **备份与恢复**：`backup_utils` 增加 DM 分支——备份用 `dexp` 导出二进制 DMP 并 gzip 为 `zhycms_dm_<ts>.dmp.gz`，恢复用 `dimp`；密码经 `USERID=user/password@host:port` 传入（达梦工具不支持 `PGPASSWORD`），工具路径支持 `ZHYCMS_DM_BIN`（`bin` 目录或 `DM_HOME`）与 `ZHYCMS_DB_DUMP_BIN_DIR`。
- **依赖与文档**：新增 `requirements-dm.txt`（`dmpython`、`dmSQLAlchemy`）与 [docs/DEPLOY_DM.md](docs/DEPLOY_DM.md)（授权声明、实例与 Schema 准备、向导填写、备份恢复、限制）；新增 [docs/DM8_ARM_TEST_REPORT.md](docs/DM8_ARM_TEST_REPORT.md)（aarch64 实测报告）；更新 `docs/XINCHUANG_ADAPTATION.md` 与 README，将达梦 DM8 从「规划中」改为「已实现（v3.3.2，x86_64 + aarch64/鲲鹏）」。
- **DM 兼容修复**：关闭方言的批量 `INSERT ... RETURNING`（`use_insertmanyvalues` / `insert_executemany_returning*`），修复 RBAC 初始化时 dmPython 多行 RETURNING 行数不可靠导致的失败；迁移 `0010` 对 DM 的 `TEXT`（CLOB）比较显式 `CAST` 为 `VARCHAR`；迁移 `0012` / `0014` 的唯一索引存在性判断同时检查 `get_unique_constraints()`，兼容 DM 为唯一约束自动命名底层索引的行为。
- **测试**：新增 `tests/test_dm.py`（离线覆盖方言注册 / IDENTITY DDL / URI / 引擎参数 / 错误提示 / 备份恢复命令 / 向导；live 集成由 `ZHYCMS_TEST_DM_URL` 门控，默认跳过）。

### Fixed

- **KingbaseES DDL 约束修复**：在 `app/utils/dialects/kingbase.py` 新增 `KingbaseDDLCompiler`，覆盖 `get_column_specification`，为 `unique=True` 但缺表级 `UniqueConstraint` 的列补列级 `UNIQUE` 关键字。KingbaseES 比 PostgreSQL 更严格，FK 引用列必须有显式 `UNIQUE CONSTRAINT`，仅 `UNIQUE INDEX` 不够，否则 `db.create_all()` 时 FK 约束失败。受影响列：`Permission.code`、`Role.code`、`User.username`、`Site.slug`、`Site.subdomain`。该修复仅作用于 KingbaseES 方言层，不影响 PostgreSQL 及其他后端。
- **DM8 新装引导与默认站点**：`_alembic_bootstrap` 改为在 `db.create_all()` 之前检测核心表是否存在，全新库直接 stamp 最新迁移版本 `0020`（不执行增量迁移），避免在 DM8 上因 inspector 系统表权限不足导致「列已存在」冲突；同时在启动期（`Site.ensure_default()`）幂等确保默认站点（id=0）存在，补齐新装跳过增量迁移后不再由迁移 0012 创建默认站点的缺口（旧库已存在时为 no-op，不影响存量升级）。
- **DM8 SQLAlchemy 2.1 兼容**：`app/utils/dialects/dm.py` 新增 `_patch_sqlalchemy_compat()`，在导入 `dmSQLAlchemy` 前为其补齐 SQLAlchemy 2.1 移除的 `await_fallback` 与 `AsyncAdaptFallback_dbapi_connection` 符号；`register_dm_dialect()` 在应用启动时先于引擎创建执行，正常部署无需手动干预。
- **测试环境 sqlite3 回退**：`tests/conftest.py` 在导入顶部增加 `pysqlite3` 自动回退，兼容内置 `sqlite3` 因符号缺失无法导入的环境。

### 验证

- **达梦 DM8（x86_64）**：`db.create_all()` 与 Alembic `0001→0020` 全量迁移通过；初始化向导（建表、管理员与默认设置写入）、整数主键自增、`dexp`/`dimp` 备份恢复、`/healthz?detail=1`（`database=ok`、`db_dialect=dm`）均已完成端到端验证。
- **达梦 DM8（aarch64 / 鲲鹏）**：在华为云鲲鹏 ARM（Huawei Cloud EulerOS 3.0，aarch64）上对 DM8（`DM Database Server 64 V8`）完成端到端实测，**30 项测试全绿**（连接、自增、全量迁移、健康检查、备份恢复命令构造），并修复 3 个兼容性问题（SQLAlchemy 2.1 符号、新装引导误判、测试环境 sqlite3），详见 [docs/DM8_ARM_TEST_REPORT.md](docs/DM8_ARM_TEST_REPORT.md)。至此达梦 DM8 已在 **x86_64 + aarch64/鲲鹏** 双架构完成端到端验证。
- **KingbaseES aarch64 / 鲲鹏双架构验证**：在华为云鲲鹏 ARM（Huawei Cloud EulerOS 3.0，aarch64）上对 KingbaseES V9R1C10（V009R001C010B0004，`DB_MODE=pg`）完成端到端实测，**55 项全绿**（单元测试 30 passed / 0 failed + 集成 25 passed / 0 failed），详见 [docs/KINGBASE_ARM_TEST_REPORT.md](docs/KINGBASE_ARM_TEST_REPORT.md)。至此 KingbaseES pg 兼容模式已在 **x86_64 + aarch64/鲲鹏** 双架构完成端到端验证。

### 限制与注意

- 达梦 DM8 已在 x86_64 与 aarch64（鲲鹏）验证；旧库增量迁移若遇系统表（如 `SYSCOLUMNS`）无查询权限，请使用 SYSDBA 或授予系统表查询权限的账号执行。
- DM8 的「数据库名」即 Schema，向导与 URI 请填写 Schema（建议与用户名同名、大写）。
- 若未安装 `dexp` / `dimp`，连接、迁移与业务读写不受影响，仅后台备份/恢复不可用（页面给出中文提示）。
- 回退：改回原 `ZHYCMS_DB_URI` 后重启即可，无结构变更。

## [3.3.1] - 2026-11-26

**信创适配增量版**：新增人大金仓 **KingbaseES V9（pg 兼容模式）** 数据库支持。无数据库迁移（仍为 `0020`），`requirements.txt` 无新增必需依赖（复用标准 `psycopg2-binary`）。

> **授权声明**：本项目仅实现对 KingbaseES 的适配支持。KingbaseES 为商业软件，其 Docker 镜像、客户端工具与授权文件（license）需用户自行到 <https://www.kingbase.com.cn/download.html> 下载并获取官方授权；本仓库不提供、不分发 KingbaseES 二进制或许可证。

### Added

- **KingbaseES 数据库支持**：新增内置轻量方言 `app/utils/dialects/kingbase.py`——`KingbaseES` 为 PG 线协议兼容，直接使用标准 PyPI `psycopg2-binary` 驱动，无需专用驱动或 `LD_LIBRARY_PATH`；因 `select version()` 返回 `KingbaseES V009R001C010` 会导致标准 PostgreSQL 方言版本解析抛 `AssertionError`，本方言覆盖 `_get_server_version_info`，改用 `SHOW server_version`（实测 `12.1`）解析为 `(12, 1)`；注册 `KingbaseImpl` 供 Alembic 按 `dialect.name` 查表。连接串形如 `kingbase+psycopg2://system:pwd@host:54321/db`。
- **连接与引擎参数**：`build_engine_options()` 对 KingbaseES 复用 openGauss 的连接池、`connect_timeout` 与 `application_name`；`dbconfig.py` 增加默认端口 `54321`，支持 TCP 与 Unix socket URI，驱动缺失、认证失败、连接拒绝分别给出可操作中文提示。
- **初始化向导与显示**：向导新增「KingbaseES（信创推荐）」选项，未填端口时回退 `54321`；`_current_db_label()`、后台页脚与 `/healthz?detail=1` 的 `db_dialect` 显示 `kingbase`。
- **备份与恢复**：`backup_utils` 按方言适配 KingbaseES——备份用 `sys_dump`（stdout 为纯 SQL，直接管道 gzip），恢复用 `ksql -w -d <db> -f <sql>`；**密码通过 `KINGBASE_PASSWORD` 环境变量注入**（ksql / sys_dump / sys_restore 不识别 `PGPASSWORD`），不在命令行明文出现；工具路径支持 `ZHYCMS_KINGBASE_BIN` / `KINGBASE_BIN` / `ZHYCMS_DB_DUMP_BIN_DIR`。
- **镜像与编排**：新增 `docker-compose.kingbase.yml`；默认 `pollybird/zhycms` 镜像已含 `psycopg2-binary`，**无需新增驱动构建参数或镜像变体**；备份/恢复所需客户端工具（ksql / sys_dump）需用户自行提供（见 `docs/DEPLOY_KINGBASE.md`）。
- **文档**：新增 `docs/DEPLOY_KINGBASE.md`（镜像加载、compose 启动、连接参数、备份恢复、授权声明、限制）；更新 `docs/XINCHUANG_ADAPTATION.md` 将 KingbaseES 从「规划中」改为「已实现（pg 模式）」；README 支持矩阵补充 KingbaseES 与授权声明。
- **测试**：新增 `tests/test_kingbase.py`（离线覆盖方言注册/版本解析/Alembic impl/URI/错误提示/备份命令与 env 注入/向导；live 集成由 `ZHYCMS_TEST_KINGBASE_URL` 门控，默认跳过）。

### 限制与注意

- **仅支持 `DB_MODE=pg`**：oracle / mysql / sqlserver 兼容模式不在本轮目标范围内。
- 默认端口 `54321`、默认管理账号 `system`、默认库 `test`；应用目标数据库需提前创建。
- 客户端工具（`ksql` / `sys_dump`）需与应用进程同机可用（配置 `ZHYCMS_KINGBASE_BIN` 与 `LD_LIBRARY_PATH` 指向其 `lib`），否则应用内「备份/恢复」不可用（连接与迁移不受影响）。
- 回退：改回原 `ZHYCMS_DB_URI` 后重启即可，无结构变更。

## [3.3.0] - 2026-11-22

**信创适配版**：新增 openGauss 7.0 数据库与 openAMDC 1.0.0 缓存后端支持。无数据库迁移（仍为 `0020`），`requirements.txt` 无新增必需依赖。

### Added

- **openGauss 数据库支持**：新增内置轻量方言 `app/utils/dialects/opengauss.py`（兼容 `openGauss-lite` 版本串、注册 Alembic DDL 实现），`opengauss+psycopg2://` 可直接连接；官方 `opengauss-sqlalchemy` 已安装时优先使用（可选，`requirements-opengauss.txt`）。
- **连接与引擎参数**：`app/config.py::build_engine_options()` 为 openGauss 设置连接池、`connect_timeout` 与 `application_name`；`app/utils/dbconfig.py` 支持 openGauss 的 TCP 与 Unix socket URI，驱动缺失、sha256 认证失败、连接拒绝分别给出可操作中文提示。
- **初始化向导与显示**：向导新增「openGauss（信创推荐）」选项与 5432 端口联动；`_current_db_label()` 与后台页脚显示 openGauss。
- **备份与恢复**：`backup_utils` 按方言适配 openGauss——`gs_dump` 使用位置参数库名与 `-W` 密码、`gsql` 恢复、自动注入 `LD_LIBRARY_PATH`；工具路径支持 `ZHYCMS_DB_DUMP_BIN_DIR` / `OPENGAUSS_BIN` / `ZHYCMS_DB_DUMP_BIN`。
- **openAMDC 缓存后端**：新增 `app/services/redis_backend.py`，按 `INFO server` 的 `openamdc_version` / `redis_version` 识别后端；启动日志、后台 Redis 页与 `/healthz?detail=1` 展示 `redis_flavor` 与版本。
- **健康检查**：`/healthz?detail=1` 新增 `db_dialect` 与 `redis_flavor`；默认 `/healthz` 保持轻量。
- **镜像与编排**：新增 `pollybird/zhycms:opengauss`、`pollybird/openamdc:1.0.0`、`pollybird/opengauss:7.0.0`（均提供 x86_64 / aarch64 多架构）；新增 `docker-compose.opengauss.yml`，`docker-compose.yml` 增加 `openamdc` profile 与 `app-sqlite` profile；根 `Dockerfile` 新增可选构建参数 `INSTALL_OPENGAUSS_DRIVER` / `OPENGAUSS_PY_URL`；安装器支持数据库四选一、缓存三选一。
- **文档**：新增 `docs/DEPLOY_OPENGAUSS.md`、`docs/DEPLOY_OPENAMDC.md` 与 `docs/XINCHUANG_ADAPTATION.md`（信创数据库适配专题：官方仅实现 openGauss，附达梦 / 金仓 / GBase / PolarDB 适配思路、工作量评估与贡献指南）。
- **测试与 CI**：新增 `tests/test_opengauss_v330.py`、`tests/test_openamdc_v330.py`、`tests/test_redis_backend_v330.py`、`tests/test_compat_integration.py`（默认 skip），以及 `.github/workflows/compat.yml`（openAMDC 全量 + openGauss 冒烟）。

### Fixed

- **清缓存导致全员登出**：缓存键前缀 `zhycms:` 与会话前缀 `zhycms:sess:` 重叠，`clear()` 会连带删除会话；缓存前缀改为 `zhycms:cache:`。
- **站点缓存条目恒为 `--`**：cachelib `RedisCache` 无 `scan_iter` 也无 `_cache`，新增 `scan_iter(match=...)` 统计分支。

### 升级注意

- 无数据库迁移，覆盖代码 + 重启即可；MySQL / PostgreSQL / Redis 部署行为不变。
- 切换 openGauss 需额外安装 openGauss 官方 psycopg2 驱动并配置 `LD_LIBRARY_PATH`，或用 `:opengauss` 镜像（x86_64 / aarch64 多架构，内置对应架构驱动）；aarch64 驱动已完成实测。
- openAMDC 可直接作为 `REDIS_URL` 使用，应用自动识别；镜像默认关闭持久化，重启后会话失效属预期。
- 回退：改回原 `ZHYCMS_DB_URI` / `REDIS_URL` 后重启即可，无结构变更。

## [3.2.12] - 2026-11-21

**Webhook 事件订阅版**：业务事件可按站点订阅并异步外送到用户自定义接收地址，带签名、重试与安全防护。新增数据库迁移 `0020`，无新增 Python 依赖。

### Added

- **七类事件**：`article.published` / `article.archived`（工作流流转成功后）、`form.submitted`（仅字段名摘要，不含提交值）、`backup.completed`、`site.status_changed`（编辑与批量启停）、`ssl.expiring`（每日巡检随提醒去重）、`webhook.test`（后台测试）。
- **投递器**：`app/services/webhook.py`，10 秒 APScheduler 任务（受 v3.2.10 领导者锁约束）或 `python -m app.services.webhook --once` 外部 cron；`UPDATE ... WHERE status='pending'` 抢占避免多 worker 重复投递。
- **签名与幂等**：`X-ZhyCMS-Event`、`X-ZhyCMS-Delivery: <replay_id>`、`X-ZhyCMS-Signature: t=<unix>,v1=<hex>`（`hex(hmac_sha256(secret, "{t}." + body))`）；重试保持同一 replay_id，消费方可幂等去重。
- **重试与审计**：非 2xx / 超时 / 连接错误按 1s、10s 退避重试，第 3 次失败后终态 `failed` 并写审计日志；后台支持手动重试（重置 attempts）。
- **安全防护**：密钥 Fernet 加密存储、仅在创建/轮换时完整显示一次；投递不跟随重定向；发送前二次 SSRF 校验，默认仅 HTTPS 公网地址（`webhook_allow_http`、`webhook_allow_private` 默认 `off`）；每订阅每秒 5 次限速（Redis 计数，退化进程内滑窗）；错误响应体仅保留前 2KB。
- **后台管理**：「全局设置 → Webhook 集成」（`site:manage`），订阅增删改、启用开关、密钥轮换、测试发送、投递记录按状态/事件筛选与失败重试，所有变更写审计。
- **数据模型**：迁移 `0020` 新增 `webhook_subscriptions`（`site_id+url` 唯一）与 `webhook_events`（`(status,next_retry_at)`、`(site_id,created_at)` 索引，`replay_id` 唯一）；一行 = 一次事件对一个订阅的投递。
- **文档与测试**：新增 `docs/WEBHOOK.md`（含签名校验示例），15 项回归测试。

### 升级注意

- 启动自动执行迁移 `0020`（可降级）；不配置订阅时不产生任何外发请求，存量行为不变。
- 事件在业务事务提交后发射，发射/投递失败仅记录日志，不影响主业务。
- 回滚：停用全部订阅即可停止外送；回退代码后可执行降级删除两张 webhook 表，不影响既有内容。

## [3.2.11] - 2026-11-21

**OpenAPI 公开版**：为内容 API 建立可机器读取的 OpenAPI 3.0 契约，并新增默认关闭的内容写端点与官方 Python SDK。无数据库迁移、无新增 Python 依赖。

### Added

- **OpenAPI 3.0 契约**：新增 `app/api/openapi.py` 注册表与 `GET /api/v1/openapi.json`，覆盖站点、栏目、文章、鉴权、表单与插件贡献端点；`scripts/generate_openapi.py` 生成 `docs/openapi.yaml`，`scripts/check_openapi.py` 在 CI 中反向校验路由覆盖率与文件一致性。
- **内容写端点（默认关闭）**：`POST /api/v1/articles`、`PUT/DELETE /api/v1/articles/<id>`、栏目与碎片的创建/更新/删除。写入复用后台服务层（版本快照、审计日志、自定义字段），开启后仅接受 Bearer JWT，并按角色与栏目授权校验；发布操作额外校验栏目发布标志。
- **扩展只读端点**：`GET /api/v1/forms/<slug>/submissions`（JWT + `form:view`）、`GET /api/v1/sites` 与 `GET /api/v1/sites/<id>/metrics`（仅超级管理员）。
- **官方 Python SDK**：新增 `sdk/zhycms_sdk`（`Client`、`Page`、内容/表单/站点客户端），支持登录、401 自动刷新重放、GET 网络错误重试与统一异常。
- **后台开关**：内容 API 设置页新增「写端点开关」与写端点限流（`api_write_enable` 默认 `off`，`api_rate_limit_write` 默认 30 次/分钟）。

### Changed

- 全局 API 门控新增写端点分支：写开关关闭时返回 404；静态 `X-API-Token` 不能调用写接口。
- `api_err` 支持 409，用于栏目存在子栏目或文章时的删除冲突。

### 升级注意

- 无数据库迁移，覆盖代码 + 重启即可。
- 写端点默认关闭，存量只读 API 行为不变；需要写入时在「全局设置 → 内容 API」开启，并使用 JWT 登录后的 Bearer Token。
- SDK 位于仓库 `sdk/` 目录，可按需 `pip install ./sdk`，不影响主程序依赖。

## [3.2.10] - 2026-11-21

**多进程 / 多实例版**：支持同一实例安全运行多个 worker、多个容器共享数据库与 Redis。无数据库迁移、无新增 Python 依赖。

### Added

- **限流共享存储**：配置 `REDIS_URL` 时，API 与会员接口限流改用 Redis 存储，多 worker / 多实例计数一致；未配置时维持内存存储。
- **调度器单实例**：多 worker + Redis 时通过 Redis 领导者锁保证同一时刻只有一个进程执行备份、清理、指标快照、证书巡检与浏览量合并；锁丢失时自动停止本进程调度器。
- **调度外置**：`ZHYCMS_SCHEDULER_ENABLED=0` 可关闭内置调度，交由外部 cron；`=1` 可强制启动（专用调度进程）。
- **多实例 nginx 配置**：`generate_nginx_sites.py` 新增 `--upstreams`，生成独立 `00-zhycms-upstream.conf`（`upstream` 组 + keepalive），站点配置统一反代。
- **健康检查详情**：`GET /healthz?detail=1` 返回数据库、Redis、缓存、限流、调度器角色、worker 数与站点解析结果；默认 `/healthz` 保持轻量探测。
- **压测脚本**：新增 `scripts/bench_http.py`，输出 QPS、p50 / p95 / p99 与错误率，作为多实例发布验收依据。
- **运行形态自检**：多 worker 未启用 Redis 时记录 ERROR 并在后台显示红色横幅；`ZHYCMS_REQUIRE_REDIS=1` 时 Redis 不可用直接拒绝启动。

### Changed

- 浏览量周期合并增加缓存锁，避免多 worker 重复回写。
- 多实例部署文档补充 Redis 必需项、环境变量与健康检查说明。

### 升级注意

- 无数据库迁移，覆盖代码 + 重启即可。
- 单进程部署无需 Redis，行为与 v3.2.9 一致；多 worker / 多实例必须配置 `REDIS_URL`。
- 使用自定义进程管理器自行运行定时任务时，可设置 `ZHYCMS_SCHEDULER_ENABLED=0` 避免与内置调度重复。

## [3.2.9] - 2026-11-20

**安全修复版**：收紧内容 API 的账号状态与会员内容边界，增强短信验证码、SVG 上传和后台退出登录防护。新增数据库迁移 `0019`（会员短信验证码失败计数），无新增 Python 依赖。

### Security

- **API 登录与令牌状态复核**：登录排除已删除账号，拒绝禁用/锁定账号；密码错误接入与后台一致的失败计数和临时锁定策略。访问令牌与刷新令牌每次使用都会复核账号状态，账号被禁用、删除或锁定后立即不可用。
- **会员专属内容隔离**：内容 API 不再输出 `member_only` 栏目及其文章；栏目列表、站点导航、栏目详情、文章列表和文章详情统一按不存在处理，避免绕过前台会员校验读取正文。
- **短信验证码防爆破**：验证码哈希改为使用服务端密钥的 HMAC；同一验证码连续输错达到上限（默认 5 次）后主动作废，验证成功后同手机号同用途的历史验证码全部失效。短信登录、找回密码和发送验证码接口增加按手机号与 IP 组合的限流。
- **SVG 主动内容清除**：上传开关开启后，SVG 先经元素/属性白名单净化再保存；移除脚本、事件属性、外部链接、`foreignObject`、外部资源引用及 DTD/实体声明，保留常见静态绘图能力。
- **手机号注册状态防枚举**：找回密码与短信登录（关闭自动注册时）对未注册手机号均返回与验证码错误一致的提示，不再直接暴露手机号是否已注册。
- **后台退出登录**：仅接受带 CSRF 校验的 POST 请求，GET 链接退出已移除。

### Fixed

- **MySQL / PostgreSQL 迁移链中断**：`0003`、`0004`、`0010`、`0011`、`0012` 中直接拼写的原生 SQL 不再使用 MySQL 反引号或未加引号的 `key`（MySQL 保留字），改用 SQLAlchemy 表达式按方言引用标识符，避免迁移在 `0003`/`0012` 处报语法错误导致后续迁移（含 `0019`）全部跳过、登录日志因外键缺失写入失败。
- **旧文章状态回填的布尔比较**：`is_enabled = 1/0` 改为参数绑定布尔值，修复 PostgreSQL 报 `boolean = integer`；同步修正 `scripts/upgrade_v2.py`。
- **迁移失败不再静默跳过**：bootstrap 异常由 WARNING 提升为 ERROR 日志，并在后台所有页面渲染「数据库迁移未完成」红色横幅，提示执行 `flask db upgrade` 后重启。

### 升级注意

- 执行 `flask db upgrade` 应用迁移 `0019`；未安装会员插件时迁移自动跳过。新装库由模型直接建表，无需额外操作。
- 升级前已签发但仍有效的短信验证码会因哈希算法调整而失效，用户重新获取即可。
- 内容 API 客户端若依赖读取会员专属栏目，需要改为前台会员访问流程；后台退出登录按钮已改为表单提交，自定义后台模板需同步改为 POST。

## [3.2.8] - 2026-11-18

**站点平台化运维版**：新增站点克隆、站点级备份导出/导入、证书到期巡检、批量操作与站点回收站；Docker 内置 Redis 升级到 8。新增数据库迁移 `0018`（`site_jobs`、`site_recycle_bin`），无新增 Python 依赖。

### Added

- **站点克隆**：后台可把一个站点的栏目、字段、文章、碎片、页面构建与插件内容复制到新站点；目标站默认关闭，检查后再开放。上传资产、会员、提交记录、日志与版本历史不复制。内容量较大时转异步任务，进度写入 `site_jobs`，重启后超时任务自动标记失败并清理半成品站点。
- **站点级备份**：支持把单站导出为 ZIP（`manifest.json` + 各表 JSONL + 上传目录），导入时可选新建、覆盖或改名解决冲突；导入自动重映射主键、重写上传 URL 并重建文件索引。ZIP 校验包含路径穿越、符号链接、解压上限与压缩比检查；下载链接使用限时签名。
- **证书到期巡检**：每日 08:00 检查各站点证书，剩余天数可配置（默认 10 天），临期/过期写入审计并可按邮件、企业微信提醒；同站同日只提醒一次。`scripts/check_ssl_expiry.py` 支持 `--days`、`--json`、`--strict`、`--no-notify`，便于接入外部监控。
- **批量操作**：站点列表支持批量启用/禁用、批量删除与批量分配站点角色；默认站点不参与禁用与删除。
- **站点回收站**：删除站点改为移入回收站并保留内容，可在到期前恢复；到期任务先自动导出备份再彻底删除，备份失败则保留记录。新增 `scripts/site_backup.py` 供命令行导出与查看备份。
- **站点资源与部署入口**：站点列表集中提供克隆、备份、证书状态与回收站入口。

### Changed

- **Redis 8**：Docker Compose 与安装脚本内置的 Redis 镜像升级为 `redis:8-alpine`。
- **站点权限改为 fail-closed**：权限查询异常、账号无任何角色或站点绑定时不再默认全站可见，统一拒绝访问；禁用/已删除账号仍由登录装饰器登出。
- **JWT 回退密钥按站点派生**：非默认站点未单独配置 `jwt_secret_key` 时，以应用级密钥 + 站点 id 派生独立密钥，不再与默认站点共用；默认站点与已显式配置密钥的站点不受影响。

### Fixed

- 站点备份覆盖导入时，内容清空与恢复共用事务，恢复失败可回滚，避免目标站点被部分清空。
- 证书解析改用 `cryptography` 公开接口，移除对 CPython 内部 `ssl._ssl._test_decode_cert` 的依赖。
- 站点克隆入口校验 `target` 必须为字典，传错类型时抛出明确的 `TypeError`。
- 开发环境 SimpleCache 条目较多时，站点缓存指标不再固定返回空值。

### 升级注意

- **有数据库迁移 `0018`**（`site_jobs`、`site_recycle_bin` 及索引，幂等、可降级），启动自动执行。
- **删除站点行为变化**：删除改为移入回收站，内容保留 30 天；需要立即释放空间请使用回收站的彻底删除。
- **JWT 令牌失效**：非默认站点未配置 `jwt_secret_key` 时，升级后此前签发的 token 会失效，用户需重新登录；已显式配置密钥的站点不受影响。
- **Redis 升级**：使用内置 Redis 的部署重新拉取镜像即可，数据卷格式兼容；外部 Redis 需为 6.0 及以上版本。
- **测试**：全量 631 项通过（新增 42 项站点平台化与安全回归）；`check_excepts.py` / `check_constants.py` / `check_release.py --version 3.2.8` 三门禁全绿。

## [3.2.7] - 2026-11-18

**站群部署与可观测版**：新增 nginx 站点配置生成器与后台部署指南，把新增站点从手工配置压缩到十几分钟；新增站点资源面板、每日指标快照与磁盘/文章/缓存阈值告警；新增插件站点作用域审计与日志站点标签。新增数据库迁移 `0017`（`site_metric_snapshots`），无新增依赖。

### Added

- **nginx 配置生成器**：`scripts/generate_nginx_sites.py` 读取站点表生成 vhost，支持精确域名、子域 + 泛解析基础域名、默认站点 `_` 兜底、SSL 跳转、非法域名跳过与幂等覆盖；支持 `--stdout` 与 `--site-id` 单站输出。
- **后台部署指南**：站点列表新增「部署」入口，只读展示 `server_name`、完整 nginx 片段与 Let's Encrypt 证书剩余天数，支持一键复制；不修改服务器配置。
- **多站部署模板**：新增 `docker/compose.multi.example.yml` 与 `docker/env/*.env.example`，明确「单实例多站，站点在后台创建」；`docker/install.sh` 增加可选的多站配置骨架分支。
- **站点资源面板**：`/admin/sites/metrics` 展示各站点文章数、浏览量、缓存条目、磁盘占用与占比；新增 4 个全局阈值设置（磁盘/文章/缓存/硬上限），超阈值行黄色、超硬上限红色。
- **每日指标快照**：每日 00:30 写入 `site_metric_snapshots`（迁移 `0017`），按 `(site_id, date)` 唯一，重复执行只更新不新增。
- **插件站点作用域审计**：新增 `scripts/audit_plugins_site_scope.py`（AST 扫描，R1–R4 规则，含子表豁免清单），插件管理页对未适配插件显示橙色标签，多站点启动时输出一次告警。
- **日志站点标签**：统一日志格式增加 `[site=N]`，请求内取当前站点，CLI/迁移/定时任务输出 `[site=-]`。

### Changed

- **审计导出**：导出文件名带站点标识（`audit-site2-YYYYmmdd.csv` / `audit-all-YYYYmmdd.csv`），范围继续按可见站点收口。
- **站点资源入口**：侧边栏「全局设置」新增「站点资源」；站点管理员仅能看到自己授权站点，无权限账号访问返回 403。

### 升级注意

- **有数据库迁移 `0017`**（`site_metric_snapshots` + 索引，幂等、可降级），启动自动执行。
- 单站点部署无需任何 nginx 改动；新增第 2 个站点按 `docs/DEPLOY_MULTI_SITE.md` 操作。
- **测试**：全量 589 项通过（新增 20 项站群部署与可观测回归）；`check_excepts.py` / `check_constants.py` / `check_release.py --version 3.2.7` 三门禁全绿。

## [3.2.6] - 2026-11-17

**站点级配置与日志可见性版**：消息通知、编辑设置、内容 API 由全局配置改为按站点配置；审计/登录日志仅超级管理员与站点管理员可见，且站点管理员仅限授权站点；Redis 缓存页仅超级管理员可见。新增数据库迁移 `0016`（`login_logs.site_id`），无新增依赖。

### Added

- **站点级消息通知**：`notify_*` 与 `form_notify_*` 改为站点级设置，不同站点可分别配置收件人、SMTP 与企业微信 Webhook，前台表单通知按所属站点发送。
- **站点级编辑设置**：`editor_default_mode` 改为站点级，不同站点可使用不同的默认编辑器（CKEditor / Markdown）。
- **站点级内容 API**：`api_*` / `jwt_*` 改为站点级，各站点可独立设置开关、鉴权方式、静态令牌、JWT 密钥、缓存 TTL、CORS 与速率限制；新增 `app/utils/api_jwt.py` 按站点密钥签发/校验 JWT（兼容存量 token 与 Redis `jti` 黑名单）。
- **登录日志站点维度**：`LoginLog.site_id`（迁移 `0016`），登录时记录所属站点。

### Changed

- **日志可见性**：审计日志与登录日志仅超级管理员、站点管理员可见；站点管理员仅能看到自己 `site_admin` 授权站点的日志（列表、筛选、导出、清理、仪表盘均按范围过滤）；内容审核员、只读查看员预设角色移除 `system:audit_log`。
- **仪表盘**：无日志权限时不查询、不渲染「最近操作审计」「最近登录日志」；站点管理员的日志区块按授权站点过滤；未读表单计数改为当前站点。
- **菜单**：新增顶层「日志审计」树（操作审计 / 登录日志）；消息通知、编辑设置、内容 API 移入「站点设置」；Redis 缓存仅超级管理员可见。
- **Redis 设置页**：非超级管理员访问返回 403。

### 升级注意

- **有数据库迁移 `0016`**（`login_logs.site_id` + 索引，幂等、可降级），启动自动执行。
- 存量登录日志 `site_id` 为 NULL，仅超级管理员可见；新日志按登录站点记录。
- 站点级设置未配置时回退到默认站点 0 的存量值，单站点部署行为不变。
- **测试**：全量 569 项通过（新增 7 项站点级设置与日志可见性回归）；`check_excepts.py` / `check_constants.py` / `check_release.py --version 3.2.6` 三门禁全绿。

## [3.2.5] - 2026-11-17

**后台菜单分类版**：原「系统设置」将站点级与全局级配置混在一起，现拆分为「站点设置（当前站点）」与「全局设置（全站共用）」两组，按实际作用域归类。**无数据库结构变更、无新增依赖**，覆盖代码 + 重启即可。

### Changed

- **侧边栏分区**：原「系统设置」拆分为两组：
  - **站点设置（当前站点）**：网站设置、SEO 默认配置、SEO 高级、主题管理；
  - **全局设置（全站共用）**：站点管理、插件管理、上传配置、上传安全、消息通知、后台安全、登录日志、内容 API、国际化、搜索设置、编辑设置、Redis 缓存。
- **权限可见性**：站点管理员仍可访问全局配置项，但「站点管理」「插件管理」入口仅对超管/具备 `site:manage` 的账号展示，避免进入后 403。
- **面包屑同步**：各设置页面与站点设置页的主题入口提示更新为新的分组名称。

### 升级注意

- **无数据库迁移、无新增依赖**，覆盖代码重启即可。
- **测试**：全量 562 项通过（新增 2 项菜单分区回归）；`check_excepts.py` / `check_constants.py` / `check_release.py --version 3.2.5` 三门禁全绿。

## [3.2.4] - 2026-11-17

**密码策略可配置版**：将 v3.1.10 起写死的后台管理员密码复杂度（12 位 + 大小写 + 数字 + 特殊字符）改为可在「全局设置 → 后台安全」调整，仅超级管理员可见可改；默认仍为严格策略，升级后行为不变。**无数据库结构变更、无新增依赖**，覆盖代码 + 重启即可。

### Added

- **密码复杂度设置**：后台安全新增「管理员密码复杂度」卡片（仅超管可见）：密码最低位数（6-64）可调，大写字母/小写字母/数字/特殊字符四个复选框可分别开关，策略对全部后台账号生效。
- **弱策略确认**：最低位数低于 8 位时，保存前弹出确认框提示「复杂度过低可能导致安全隐患」，确认后保存并返回 warning 提示。
- **动态策略读取**：`get_password_policy()` 运行时读取 `password_*` 全局设置，`validate_password()` 按当前策略校验；`password_policy_hint()` 供模板生成提示文案。
- **表单联动**：初始化向导、个人改密、账号新建/重置密码的 `minlength` 与提示文案改为按当前策略渲染，不再写死 12 位。

### Changed

- **全局设置前缀**：`password_` 纳入 `Setting.GLOBAL_KEY_PREFIXES`，站点维度切换不影响密码策略。
- **默认值**：沿用 v3.1.10 严格策略（12 位 + 四类字符），存量部署无需调整。

### 升级注意

- **无数据库迁移、无新增依赖**，覆盖代码重启即可。
- **存量密码**：策略仅约束新设置/重置的后台密码，已有密码哈希不回溯校验。
- **测试**：全量 560 项通过（新增 7 项 v3.2.4 回归）；`check_excepts.py` / `check_constants.py` / `check_release.py --version 3.2.4` 三门禁全绿。

## [3.2.3] - 2026-11-17

**角色体系站点化版**：重新规划后台角色分组。新增「站点管理员」预设角色，拥有指定站点的全部后台管理权限；内容审核员/内容编辑/只读查看员同样绑定到具体站点。超级管理员可为任意账号分配多个站点角色，站点管理员只能在自己有权限的站点内添加/管理账号与角色。**新增迁移 `0015`、无新增依赖**，覆盖代码 + 重启即可。

### Added

- **站点管理员角色**：`roles.site_admin` 预设（`PRESET_ROLES` / `PRESET_ROLE_PERMISSIONS`），拥有站点内的设置、用户、审计、栏目、内容、页面构建与表单管理权限；明确不含 `site:manage`（站点增删改）与 `system:backup`（备份运维）等平台级功能。
- **用户角色支持站点维度**：`user_roles` 新增 `site_id`（NULL = 平台级/全局角色，非空 = 只在指定站点生效），唯一约束调整为 `(user_id, role_id, site_id)`（迁移 `0015`）；支持一人多站、多角色。
- **站点级权限求值**：`User.has_permission(perm_code, site_id=None)` 支持按站点判断；`User.site_role_ids()` / `has_site_role()` / `site_scoped_role_sites()` 提供角色归属查询。
- **账号表单按站授权**：站点表新增「站点角色」下拉（`site_role_<站点id>`），超级管理员可逐站分配站点管理员/审核员/编辑/只读查看员；全局角色卡仅平台管理员可见。

### Changed

- **站点可见范围**：`can_access_site()` / `accessible_sites()` 纳入站点级角色分配；拥有全局角色的存量账号仍全站可见，存在 `UserSitePermission` 显式绑定时以绑定为准（保持 v3.2.0 语义）。
- **内容审核员权限收敛**：移除预设中的全局 `site:manage`，审核员只能访问被分配的站点。
- **账号管理边界**：站点管理员仅能查看/编辑/启停/删除/重置自己站点范围内且没有全局角色的账号；角色权限页（`/admin/roles`）仅平台管理员可访问。

### 升级注意

- **新增迁移 `0015`**（`user_roles.site_id` + 唯一约束站点化，自动执行可降级）。
- **存量兼容**：升级后已有 `site_id IS NULL` 的角色保持原有全站语义，不会锁定现有账号；新分配建议按站点下拉授权。
- **降级**：恢复 `(user_id, role_id)` 全局唯一；若同一账号同一角色被分配到多个站点，会在任何 DDL 前预检中止（不会半降级）。
- **测试**：全量 553 项通过（新增 14 项 v3.2.3 回归）；`check_excepts.py` / `check_constants.py` / `check_release.py --version 3.2.3` 三门禁全绿。

## [3.2.2] - 2026-11-17

**站群内容隔离补全版**：闭环 v3.2.1 潜在威胁报告中的 11 项缺口。v3.2.1 修的是「查询带站点」，本版补齐「表结构与写入带站点」：教程、页面构建、上传索引、第三方绑定新增 `site_id` 并按站唯一；删除站点检查、缓存失效、浏览量合并、插件 SQL 搜索、平台级后台入口同步收敛。**新增迁移 `0014`、无新增依赖**，覆盖代码 + 重启即可。

### Fixed

- **教程插件跨站可见/可改（P0）**：`tutorial_categories` / `tutorials` 新增 `site_id`，`slug` 由全局唯一改为站内唯一（`uq_tutorial_category_site_slug` / `uq_tutorial_site_slug`）；前台列表/分类/详情、后台 CRUD、模板函数与构建器组件全部按当前站点过滤；演示数据只清理当前站点，不再清空他站教程。
- **页面构建跨站读写（P0）**：`builder_pages` 新增 `site_id`，唯一约束改为 `(site_id, scope, column_id)`；`get_page/get_or_create_page/list_pages_grouped` 按站查询，跨站页面在编辑器中一律 404；插件卸载检查仍有意跨站扫描，避免遗漏引用。
- **上传跨站复用（P0/P1）**：`uploaded_files` 新增 `site_id` 与 `(site_id, content_hash)` 索引，去重按站隔离；新上传物理路径改为 `uploads/site{N}/<sub_dir>/<date>/<uuid>`，旧文件路径保持不变（历史 URL 继续可用）。
- **删除站点检查遗漏（P1）**：删站内容检查补充教程分类/教程、页面构建、上传索引、第三方绑定，存在数据时阻止删除并返回条数。
- **会员删除缺少站点校验（P1）**：`member_delete` 与编辑一致校验会员所属站点，跨站删除返回 404。
- **OAuth 绑定跨站串号（P1）**：`member_oauths` 新增 `site_id`，唯一约束改为 `(site_id, provider, openid)`；回调按 `scope_site_id()` 查询与写入（`shared` 模式统一为 0，行为不变）。
- **备份/监控站点管理员可操作（P1）**：备份、恢复、备份计划、系统监控收敛为平台级运维（超管或 `site:manage`），并在后台站点守卫中豁免对应入口。
- **缓存失效键不匹配（P1）**：`clear_content_cache()` 改为按 `frontend/site{N}/*` 前缀失效；后端不支持模式删除时回退整体清空。
- **浏览量全局单键（P1）**：待合并浏览量键改为 `article:viewed:pending:site{N}`，合并时按站点过滤文章，避免多站点增量互相覆盖。
- **插件 SQL 搜索无站点条件（P1）**：`SearchProvider.sql_search` 增加可选 `site_id`；产品/招聘实现按站过滤，上层按签名探测调用并保留内存过滤兜底（旧插件无需改动）。
- **平台级后台入口被站点守卫误拦（P2）**：站点管理、插件管理、对象存储、数据库迁移、翻译、访问统计、备份/监控等入口加入豁免白名单（各自内部再做权限校验）。
- **后台域名登录不落对应站点（实测缺陷）**：此前域名匹配只在前台生效，用非默认站点域名登录后台总是落到默认站点。现在后台在未显式选择过站点时也按 Host 解析（精确 domain → 子域首标签），即默认管理当前域名对应站点；显式 `?site=` 切换仍以 session 为准（切换器不被域名覆盖），域名站点无权访问时回退到可访问站点。

### 升级注意

- **新增迁移 `0014`**（5 张表补 `site_id`、唯一约束站点化，自动执行；建唯一索引前预检站内重复，冲突时中止并提示清理）。
- 新上传文件路径增加 `uploads/site{N}/` 前缀；历史文件与 URL 不受影响。
- 降级会恢复全局唯一约束，存在跨站重复数据时预检中止（不会半降级）。
- **测试**：全量 539 项通过（新增 23 项 v3.2.2 回归）；`check_excepts.py` / `check_constants.py` / `check_release.py --version 3.2.2` 三门禁全绿。

## [3.2.1] - 2026-11-16

**站群缺陷修复版**：闭环 v3.2.0 第三方测试报告中的 3 个隔离/权限缺口（P0/P1）与 2 个中等问题（P2），并加固若干低风险边界项。**新增迁移 `0013`（子域唯一索引）、无新增依赖**，覆盖代码 + 重启即可。

### Fixed

- **站点权限可被 `?site=` 绕过（P0）**：`select_site()` 在写回 `session['admin_site_id']` 前校验 `can_access_site()`；显式访问无权站点由后台统一守卫返回 403；`admin_bp` 新增 `before_request` 统一站点授权（含插件后台路由），会话站点被回收时 GET 自动回退到首个可访问站点。
- **未绑定站点账号的兼容语义**：没有任何 `UserSitePermission` 行的存量账号保持全站可见（升级不锁定现有编辑），存在绑定行的账号仅限绑定站点。
- **`status=closed` 未覆盖 API/插件（P1）**：站点关闭校验由 `frontend` 蓝本钩子提升为 app 级 `before_request`，统一覆盖前台页面、内容 API 与插件前台蓝本；API 返回 503 JSON、`/healthz` 固定 200、后台与站点根文件/静态资源豁免。
- **独立会员会话跨站有效（P1）**：新增 `plugins/member/scope.py` 统一会员站点口径；`member_scope=isolated` 时 `current_member()` 校验会员 `site_id` 与当前站点一致，不一致清会话按未登录处理。
- **站点 SEO 不生效（P2）**：`_seo()` 基线改为「站点 `seo_*` 优先、空值回退全局设置」（文章/栏目自身 SEO 仍最优先）；内容 API `/api/v1/site` 增加 `site_id` 与站点 SEO 字段。
- **`0012` 降级不能对称回滚（P2）**：降级在任何 DDL 之前预检跨站重复的 `slug/key/username`，冲突时中止并输出清单（不再半降级）；`UPGRADE.md` 同步回滚口径。
- **低风险边界项（P3）**：`accessible_sites()` 批量化（消除 N+1，请求级缓存）；`sites.subdomain` 增加唯一约束（迁移 `0013`，空白转 NULL）；域名按 DNS label 规则校验并统一大小写/尾点规范化；`sort_order` 表单层整数校验；删除站点前检查栏目/文章/碎片/插件内容；`site_url()` 支持仅有子域的站点；开发环境支持 `b.localhost`；JWT 配置读取移至 Alembic bootstrap 之后，消除升级首启临时密钥告警。

### 升级注意

- **新增迁移 `0013`**（子域唯一索引，自动执行；存在重复子域时会预检中止并提示清理）。
- 单站点部署零感知；站点权限仅在账号做过站点绑定时生效。
- **测试**：全量 516 项通过（新增 18 项 v3.2.1 回归）；`check_excepts.py` / `check_constants.py` / `check_release.py --version 3.2.1` 三门禁全绿。

## [3.2.0] - 2026-11-15

**站群版**：一个后端实例 + 一个数据库，按「站点」维度切分内容，同一套 CMS 同时服务多个独立前台站点（独立域名或泛解析子域）。**默认站点 `site_id=0` 恒等变换，单站点部署零感知**（URL、行为、SEO 全部不变）。有数据库迁移 `0012`，无新增依赖。

### Added

- **站点注册表 `sites`**：`id`（默认站点固定 0）/ `name` / `slug` / `domain`（精确域名）/ `subdomain`（泛解析子域标签）/ `status`（open / closed）/ `theme` / 站点级 SEO / 排序 / 软删除；默认站点由迁移幂等插入。
- **站点解析器 `app/sites.py`**：`select_site()` 注册为全局 `before_request`，优先级为「后台 `?site=`（写回 `session['admin_site_id']`）→ Host 精确 `domain` → 子域首标签 `subdomain` → 默认站点 0」；请求级缓存，每请求最多一次站点查询。
- **后台站点管理**（`/admin/sites`）：列表 / 新建 / 编辑 / 软删除 / 切换当前站点；默认站点禁删、有栏目的站点禁删；`slug`/`domain`/`subdomain` 冲突校验；写操作落审计（模块 `site`）。
- **后台站点切换器**：顶部导航下拉按 `can_access_site` 过滤可见站点（仅站点数 > 1 时显示），切换写入会话。
- **站点 RBAC**：新增权限点 `site:manage`（审核员预设默认授予）；新增 `UserSitePermission(user_id, site_id, can_review, can_publish)` 把内容权限收窄到指定站点（镜像 `UserColumnPermission`）。
- **站点化配置**：`settings` 唯一键由 `key` 改为 `(key, site_id)`；读取按当前站点取值、缺失回退默认站点 `(key, 0)`；`upload_*`/`login_*`/`api_*`/`search_*`/`plugin_*` 等为全局键，恒取站点 0。
- **前台会员共享/独立**：新增全局设置 `member_scope`（`shared` 默认 / `isolated`，超管可在站点设置页切换）；`members` 加 `site_id`，`username` 改 `(site_id, username)` 唯一——共享模式恒为 0 与现网一致，独立模式各站独立。
- **插件站群 SDK**：`app.plugin_api` 新增 `current_site_id()`、`site_filter(query, model=None)` 并按需导出 `SiteScopedMixin` / `DEFAULT_SITE_ID`；`docs/PLUGIN_DEV.md` 新增站群章节。

### Changed

- **内容维度列**：`columns` / `articles`（冗余同步）/ `fragments` / `members` / `settings` / `audit_logs` 及内置插件内容表（`forms` / `friend_links` / `products` / `recruit_jobs` / `banner_groups` / `banners`）新增 `site_id`（`NOT NULL DEFAULT 0` + 索引）。
- **站点内唯一**：`columns.slug` / `fragments.slug` / `forms.slug` / `banner_groups.slug` / `settings.key` / `members.username` 由全局唯一改为站点内唯一（SQLite 用唯一索引、MySQL/PostgreSQL 用复合唯一约束），不同站点可复用 `about`、`news` 等 slug。
- **前台全链路按站过滤**：首页 / 栏目 / 文章 / 碎片 / 侧栏 / 上下篇 / 站内搜索 / sitemap / 内容 API 均按当前站点取数；站点 `status=closed` 时前台返回 503。
- **主题按站**：`get_active_theme()` 优先当前站点 `sites.theme`，为空回退全局 `site_theme`。
- **缓存命名空间**：页面缓存键 `frontend/site<sid>/...`、内容 API 缓存键追加 `|site=<sid>`、插件（轮播）缓存键 `plugin/banner/site<sid>/...`，杜绝串站渲染。
- **全站搜索按站**：Tantivy schema 新增 `site_id` 字段（schema 版本标记不符时自动重建索引），Meilisearch 新增 `site_id` filterable attribute，SQL 兜底与插件 Provider 结果同样按站过滤。
- **内置插件**：表单 / 友链 / 产品 / 招聘 / 轮播的后台列表、详情、唯一性校验、新建、批量操作与前台模板函数全部按当前站点过滤；产品与招聘搜索 Provider 输出 `site_id`；会员插件按 `member_scope` 共享或独立。

### 升级注意

- **有数据库迁移 `0012`**（自动执行，可降级回滚）；**无新增依赖**；覆盖代码 + 重启即可。
- **单站点部署零感知**：迁移把现有栏目/文章/碎片/配置/会员/插件内容全部归入默认站点 `site_id=0`，URL 与行为不变。
- **启用站群**：后台「站点管理」新建站点并绑定独立域名或子域标签后，用该域名/子域访问即进入对应站点；后台顶部切换器切换管理站点。
- **重要提醒**：`slug` 唯一性改为站点内唯一后，不同站点可同名；跨站点跳转需使用 `site_url()` 生成绝对地址。
- **会员模式**：默认 `shared` 与现网完全一致；切换 `isolated` 时存量会员保留 `site_id=0` 归默认站点，新注册按当前站点落库。
- **测试**：全量 498 项通过（新增 15 项站群隔离回归）；`check_excepts.py` / `check_constants.py` / `check_release.py --version 3.2.0` 三门禁全绿。

## [3.1.10] - 2026-11-09

**纵深防御与合规加固版本**：修复 SAST 审计遗留的 Low/Info 项与 P3 项共 9 项（7 项代码加固 + 2 项纯文档披露）。**无数据库结构变更、无新增依赖**，覆盖代码重启即可。

### Security

- **模板审计下标拼接检测（VULN-023，Low）**：`app/utils/template_safety.py` 新增「下标内字符串拼接」规则（正则识别 `['_'+'_class'+'__']`、`['__gl'~'obals__']` 等下标内 `+`/`~` 拼接），主题包上传期即拒传；运行期 Jinja 沙箱本已拦截此类绕过，本规则为审计层冗余防线。官方 8 套主题全量扫描零命中。
- **加密 fail-open 高可见度告警（VULN-025，Low）**：`ZHYCMS_ENC_KEY` 与 `instance/enc_key` 均不可用时，`encrypt_value`/`decrypt_value` 记 error 级日志（每进程一次，不刷屏）；后台所有页面顶部渲染红色常驻横幅，「系统设置 → 后台安全」页显示「敏感配置加密：未启用」状态行。**不拒绝启动、不改变加解密读写语义**（fail-open 行为与 v3.1.8/v3.1.9 一致，仅提升可见度）。
- **CORS 通配符收紧（VULN-014，Low）**：`api_cors_origins` 保存时逐项校验 `http(s)://host[:port]` 格式，新值拒绝 `*`、`null` 与非 http(s) 项；**存量已配 `*` 不清空、运行时行为不变**，API 设置页显示红色告警提示整改。
- **后台管理员密码策略（VULN-015，Low）**：新增 `app/utils/password_policy.py`，后台所有设置新密码入口（初始化向导、个人改密、用户管理新建/编辑/重置）统一要求 ≥12 位且同时包含大写字母、小写字母、数字、特殊字符。**存量密码哈希不受影响可正常登录；前台会员端维持 6 位策略不变**。
- **依赖治理（VULN-016，Info）**：评估 puremagic 替换 python-magic——实测 12 类文件样本 7 类 MIME 识别不一致（exe/elf/php/纯文本识别失败或误报），不满足上传恶意文件拦截需求，**保留 python-magic**（requirements.txt 附评估结论注释）；Flask-Session 0.8.0 已为最新版无需变更；新增 `.github/dependabot.yml`（pip + github-actions 双生态周更）。
- **CI Actions pin SHA（VULN-017，Info）**：CI 工作流 10 处 `actions/checkout`、`actions/setup-python` 浮动标签替换为完整 commit SHA（保留版本注释便于 dependabot 提升级 PR），消除第三方 Action 供应链劫持风险。
- **TestingConfig 密钥防护（VULN-018，Info）**：非 testing 配置下使用 TestingConfig 的固定 SECRET_KEY 时启动直接 `SystemExit`，杜绝测试密钥误带入生产部署。
- **LIKE 通配符转义补齐（VULN-010 续项，Medium）**：补齐 v3.1.9 遗漏的 6 文件模糊查询——审计日志列表与导出（keyword/username）、招聘插件岗位后台列表与 SQL 回退搜索（含翻译表）、产品插件后台列表/API 列表与 SQL 回退搜索（含翻译表），全部统一 `escape_like` + 显式 `escape`；全库扫描确认所有 `.like()` 均已带 `escape`。
- **SSRF DNS TOCTOU 与 Markdown 内联 HTML（VULN-024/019，Info，纯文档）**：维持 SECURITY.md 基线第 11/12 条既有披露与防护建议（出口防火墙清单、bleach 白名单过滤前置条件），应用层不新增代码。

### 升级注意

- 覆盖代码 + 重启即可，**无数据库迁移、无新增依赖**。
- **行为变化**：后台设置新密码统一要求 12 位四类字符（初始化向导、个人改密、用户管理新建/编辑/重置）；存量账号登录不受影响。
- **行为变化**：`api_cors_origins` 保存新值时拒绝 `*` 与非法来源格式；存量 `*` 配置运行行为不变，仅 UI 红色告警。
- **可见度变化**：加密密钥不可用时后台全页红色常驻横幅 + error 日志，请按提示配置 `ZHYCMS_ENC_KEY` 或检查 `instance/enc_key`。
- **建议**：部署方按 SECURITY.md 基线第 11 条配置出口防火墙（禁内网网段与云元数据地址），彻底兜底 SSRF DNS TOCTOU 残余风险。
- **测试**：全量 483 项通过（新增 16 项安全回归）；`check_excepts.py` / `check_constants.py` / `check_release.py` 三门禁全绿；覆盖率 54%（门禁阈值 50%）。

## [3.1.9] - 2026-11-08

**安全修复版本**：完成 v3.1.8 顺延的 P2-B 全部 6 个 Medium（含插件 AST 间接引用绕过），同时顺带修复 2 项零成本 Info 项。**无数据库结构变更、无新增依赖**，覆盖代码重启即可。

### Security

- **插件 AST 审计间接引用绕过（VULN-022，Medium）**：`app/utils/plugin_safety.py` 由单遍 AST 匹配升级为**两遍分析**——先收集 import 别名（`import os as x`、`from os import system as s`）与赋值传播（`x = os.system`、`y = x`，迭代至稳定），再按还原后的限定名做调用判定；`getattr(os, "system")` 类危险属性获取直接拦截。已知的 3 个绕过 Payload 全部拒传，`import os.path as p` / `from os import path as os_path` 等合法别名不误伤。
- **JWT 无服务端吊销（VULN-007，Medium）**：登出接口改为 `jwt_required(optional=True)`，配置 `REDIS_URL` 时将 `jti` 写入黑名单（`zhycms:jwt:blacklist:<jti>`，TTL 为剩余有效期），并注册 `token_in_blocklist_loader` 使已登出 token 立即 401；Redis 不可达/运行期故障时降级放行并告警，不返回 500。无 Redis 部署维持“客户端删除 + access token 15 分钟自然过期”语义。
- **会话固定攻击（VULN-008，Medium）**：后台登录与会员登录（密码 / 短信 / OAuth / 注册自动登录）在建立登录态前 `session.clear()`，丢弃攻击者预置的 Session 键；OAuth 回调的 `next` 目标改为局部变量传递，跳转行为不变。
- **SQL LIKE 通配符注入（VULN-010，Medium）**：新增 `app/utils/db_utils.py::escape_like`，文章标题、用户、会员、栏目文章 API、SQL 回退搜索共 5 处 `LIKE` 查询统一转义 `%`/`_`/`\` 并显式传入 `escape`，搜索 `%` 不再放大结果集。
- **Meilisearch 地址未校验（VULN-011，Medium）**：`url_safety.py` 新增 `assert_http_url()`（scheme 限 http/https、hostname 非空、拒绝 userinfo；**默认允许内网地址**，避免破坏常见的内网 Meilisearch 部署）；保存 `search_meili_url` 时校验并拒绝非法值，使用前再校验一次防存量脏数据，非法则回退默认地址并告警。
- **生产环境 DEBUG 未阻断（VULN-012，Medium）**：`create_app('production')` 且 `DEBUG=True` 时直接 `SystemExit` 拒绝启动，杜绝 Werkzeug 调试器暴露导致的 RCE；`default`（本地开发）仅告警，不误伤 `python run.py`。
- **数据库错误信息泄露（VULN-013，Medium）**：初始化向导连接测试的 `OperationalError`/`SQLAlchemyError`/兜底分支不再回显 `e.orig` 或异常文本（主机、端口、驱动、栈信息），对外只返回固定中文文案，详情写日志（含堆栈）。
- **验证码随机源（VULN-020，Info）**：验证码文本由 `random.choices` 改为 `secrets.choice`，消除 Mersenne Twister 可预测风险（图片噪点仍用 `random`，无安全语义）。
- **fragment 删除/启停缺审计日志（VULN-021，Info）**：碎片删除与启停补 `audit_log`，记录 `OP_DELETE` / `OP_UPDATE` 及启停状态。

### 升级注意

- 覆盖代码 + 重启即可，**无数据库迁移、无新增依赖**。
- **行为变化**：`ZHYCMS_ENV=production` 下若配置了 `DEBUG=True`，应用将拒绝启动，请改为 `DEBUG=False`。
- **行为变化**：后台/会员登录会清空登录前的 Session（含攻击者预置键）；正常登录与 OAuth 跳转不受影响。
- **JWT 登出**：配置 `REDIS_URL` 的部署在登出后 token 立即失效；未配置 Redis 的部署最长仍有 15 分钟残留（可在后台调整 access token 有效期）。
- **测试**：全量 467 项通过（新增 17 项安全回归，覆盖插件审计全部绕过 Payload）；`check_excepts.py` / `check_constants.py` / `check_release.py` 三门禁全绿；覆盖率 54%（门禁阈值 50%）。

## [3.1.8] - 2026-11-06

**安全加固专项**版本。修复 SAST 深度审计报告（按 OWASP Top 10 分类）中 P0+P1 共 7 个漏洞，并新增 CSP 第三方资源白名单功能。**无数据库结构变更、无新增依赖**（`cryptography>=42.0` 已在依赖中），覆盖代码重启即可；敏感凭证首次读取时自动加密回写（惰性迁移，无需迁移脚本）。

### Security

- **主题模板 SSTI → RCE（VULN-001，High）**：**全站模板环境统一沙箱化**（`_SandboxedFlaskEnvironment`，覆盖前台 `render_template` 链与构建器直渲链），阻断 `__class__`/`__mro__`/`__subclasses__`/`__globals__` 等属性内省及 `|attr` 拼接绕过；模板 globals 与渲染上下文不再暴露 `config` 对象（`config.SECRET_KEY` 不可经模板读取），`request` 以只读白名单代理注入（阻断 `request.application.config` 逃逸链）；主题包上传模板静态审计升级（`app/utils/template_safety.py`）：`|attr` 过滤器、`config` 引用、`request` 白名单外属性/下标访问、`cycler`/`joiner`/`namespace`/`lipsum` 环境内部对象一律拒传。官方 8 套主题经全量扫描零命中，前台渲染行为不变（`request.path` 等白名单属性正常可用）。
- **插件包上传 RCE（VULN-002/VULN-009，High）**：新增 `plugin_upload_enabled` 设置项，**默认关闭**后台插件包直传（`系统设置 → 插件管理`页可显式开启）；开启后上传包需通过**基于 AST 语法树的源码审计**（`app/utils/plugin_safety.py`）：禁止导入 `subprocess`/`importlib`/`sys`/`builtins`/`operator`/`ctypes` 等高危模块，禁止 `from os import system` 等具名导入、`os.system` 等限定名调用、`eval`/`exec`/`__import__`/`compile` 裸调用、危险 dunder 属性访问及动态属性名 `getattr`——`from os import system`、`importlib.import_module("os").system`、`sys.modules['os']`、`getattr(x,'__gl'+'obals__')` 等字符串黑名单变体全部无效。官方插件为预装不经过本审计。
- **敏感凭证明文存储（VULN-003，High，A02）**：`oss_*_secret`、`*_password`、`api_token`、`jwt_secret_key`、`search_meili_key` 等敏感配置改为 Fernet 加密入库（密文 `gAAAAA` 前缀）。加密密钥优先级：环境变量 `ZHYCMS_ENC_KEY` > `instance/enc_key` 持久化文件（权限 0600）> 首次启动自动生成落盘。历史明文敏感值首次读取时自动加密回写（惰性迁移）。密钥不可用时优雅降级并告警，不阻断启动。
- **企业微信 Webhook SSRF（VULN-004，High，A10）**：通知 Webhook 校验由子串匹配改为域名精确白名单 + 强制 HTTPS（`qyapi.weixin.qq.com`），杜绝 `evil.com?qyapi.weixin.qq.com` 等子串绕过。
- **短信 Webhook SSRF（VULN-005，High，A10）**：会员插件通用短信接口发送前对占位符替换后的最终 URL 做校验，后台保存配置时同样校验。公共工具 `app/utils/url_safety.py::assert_safe_external_url` 二次加固：覆盖十进制/十六进制/八进制/段数省略等非常规 IPv4 字面量（`2130706433`、`0x7f000001`、`0177.0.0.1`、`127.1`）、IPv4-mapped IPv6（`::ffff:127.0.0.1`）与 `0.0.0.0/8`；域名经 DNS 解析后逐条记录判定（防 DNS 重绑定，解析失败 fail closed）。
- **JWT 密钥复用 SECRET_KEY（VULN-006，Medium，A07）**：移除 `jwt_secret_key` 为空时回退复用 SECRET_KEY 的逻辑；未配置时启动自动生成随机密钥并加密持久化到 Setting，杜绝 SECRET_KEY 泄露即可伪造 API Token 的连锁风险。

### Added

- **CSP 第三方资源白名单（F-001）**：后台「系统设置 → 后台安全」新增 CSP 白名单配置区块，支持 `script-src`/`style-src`/`img-src`/`font-src`/`connect-src`/`media-src`/`frame-src` 7 个指令的第三方来源配置（换行分隔，支持 `https://cdn.example.com` 精确源与 `*.example.com` 子域通配）。保存时整体校验：拒绝裸 `*`、非 http/https 协议、userinfo、query/fragment 及含空格引号的非法值，失败提示行号不落库。空白名单时响应头与 v3.1.7 逐字节一致；SVG 沙箱策略与 `frame-ancestors` 永不读取白名单（安全兜底不松动）。

### 升级注意

- 覆盖代码 + 重启即可，**无数据库迁移、无新增依赖**。
- **破坏性变更**：插件包直传默认关闭。如确需后台上传插件 zip，请在「插件管理」页显式开启「允许直接上传插件包」。
- **加密密钥持久化**：使用 `instance/enc_key` 自动生成的部署，`instance` 目录需纳入备份；多实例/容器部署建议显式配置相同的环境变量 `ZHYCMS_ENC_KEY`，否则各实例加密数据互不通用。
- 已加密敏感配置在密钥变更后无法解密（返回空串并告警），轮换密钥前请在后台重新保存各敏感配置。
- **测试**：全量 450 项通过（新增 35 项安全回归，含全部已知绕过变体）；`check_excepts.py` / `check_constants.py` / `check_release.py` 三门禁全绿；覆盖率 53%（门禁阈值 50%）。

## [3.1.7] - 2026-11-03

**稳定性修复**版本（非破坏性）。修复三类线上问题：后台文章/栏目批量操作报 403、Tantivy 全站重建索引在 500 篇以上时请求超时、数据库迁移插件在源库存在 1000+ 行且含孤儿外键数据时迁移失败。**无数据库结构变更、无新增依赖**，覆盖代码重启即可。

### Fixed

- **批量操作 403**：批量删除/归档/发布/移动/提交审核使用 jQuery `.submit()` 提交，不会触发原生 submit 事件，绕过了 `csrf.js` 的捕获阶段 Token 注入，导致请求缺少 `_csrf_token` 被 403 拦截。批量表单改为直接渲染 `_csrf_token` 字段，并在 `csrf.js` 页面加载完成后为所有已存在表单预注入 Token。
- **批量勾选丢失**：批量表单原先包裹整张表格，行内单条操作表单构成 HTML 非法嵌套，浏览器会提前闭合外层表单导致仅提交部分勾选行。批量表单移至表格外，提交前由脚本收集勾选 id 后动态写入，行内单条表单恢复正常。
- **Tantivy 全站重建超时**：重建改为后台线程执行，请求立即返回并在「搜索设置」页轮询进度（状态文件跨 worker 共享，锁文件防止重复任务）；重建完成后按 `updated_at` 补索引重建期间变更的文章，避免增量写入被覆盖。
- **搜索设置页 TypeError**：从未执行过重建时，状态接口只返回 `state`，模板对缺失的 `message` 调用 `tojson` 得到 Jinja `Undefined`，打开「搜索设置」直接报 `TypeError: Object of type Undefined is not JSON serializable`。状态读取改为始终返回完整字段（缺失键用默认值补齐），并补充无状态文件时的页面渲染回归测试。
- **数据库迁移 1000+ 行失败**：迁移前预检源库外键孤儿数据并输出「表.列 → 孤儿行数」；非空列孤儿直接中止并给出清理建议，可空列支持勾选「自动置空孤儿外键」后继续迁移；逐表复制异常附带表名、已复制行数与当前批次行数，便于定位。

### 升级注意

- 覆盖代码 + 重启即可，**无数据库迁移、无新增依赖、无配置变更**。
- 批量操作与重建索引的接口路径、返回值不变；重建索引从前台同步等待改为后台执行，页面会自动刷新进度。
- 已确认新建、编辑、删除、发布/归档文章均会增量更新索引（依赖「保存时更新索引」开关，默认开启），无需额外重建。
- **CI 门禁**：新增工作流回归测试（状态机矩阵、审核权限、快照失败回滚、驳回原因、审计、批量发布/归档/删除、归档后前台不可见）；新增覆盖率门禁任务（固定 Python 3.12，`--no-cython` 用纯 Python 分词兜底规避 Cython/coverage 冲突，最低阈值 50%）。
- **测试**：全量 415 项通过；`check_excepts.py` / `check_constants.py` / `check_release.py` 三门禁全绿；覆盖率 52%（门禁阈值 50%）。

## [3.1.6] - 2026-11-01

**异常吞噬专项治理**版本（非破坏性）。对全库 `except Exception` / 裸 `except` 做统一梳理：可明确判定的场景收窄为具体异常类型，无法预判的保留宽捕获但补中文 `warning` 留痕（含模块/操作前缀与关键上下文），彻底消除静默吞噬；插件加载/钩子/菜单等必须隔离的失败点保留宽捕获并加 `# 插件隔离：...` 注释说明。**无功能变更、无数据库结构变更、无新增依赖**，升级覆盖代码重启即可。

### Changed

- **异常留痕统一**：`app/` 与 `plugins/` 下全部通用异常捕获点补充日志——请求上下文内用 `current_app.logger.warning(...)`，上下文外（`config.py`、`storage.py`、`ip_locator.py`、`models/`、`builder/`、`scripts/` 等）用 `logging.getLogger(__name__)`；消息统一中文并带模块/操作前缀，参数走 `%s` 惰性插值。
- **异常类型收窄**：可明确判定来源的捕获改为具体类型（`OSError`、`(TypeError, ValueError)`、`requests.RequestException`、`jinja2.TemplateNotFound` / `TemplateSyntaxError` 等），减少误吞无关异常；模板不存在的预期分支改为显式 `except TemplateNotFound: return False`。
- **备份/恢复、搜索索引、i18n 编译等排障困难链路**：失败时使用 `exc_info=True` 或 `logger.exception`，保留完整堆栈。
- **插件隔离显式化**：单个插件加载失败、钩子异常、菜单/审计模块注册失败等不影响宿主，保留宽捕获并加注释说明用途，同时写 warning 便于定位。
- **控制流显式处理保留**：通过返回值告知调用方失败（如插件启用返回错误、连接测试返回错误信息）、`flash` 提示、主动 `raise`/re-raise 的位置维持原状，行为零变更。
- **文章工作流状态机重构**：五个状态流转视图（提交审核 / 审核通过 / 审核驳回 / 发布 / 归档）中重复的「改字段 → commit → 快照 → commit」两段式提交收敛到新增 `app/services/workflow_service.py`，改为「改字段 → flush → 快照 → 单次 commit」，避免首次提交成功后快照失败导致状态已变更而版本记录缺失；「驳回原因必填」、待审核前置状态、栏目级 `can_review` / `can_publish` 校验等业务规则同步下沉到 service，视图仅保留取对象、flash 与重定向。

### Added

- **新增 CI 门禁 `scripts/check_excepts.py`**：扫描 `app/` 与 `plugins/` 下的通用异常捕获（含 `BaseException` 与裸 `except`），其后处理体内若无 `logger` / `logging` / `raise` / `flash` / `abort` / `jsonify` 等留痕或显式处理信号且不在白名单，则退出码 1；白名单 `scripts/excepts_whitelist.txt` 逐条记录 `文件:行号:理由`。
- **GitHub Actions 新增 `excepts-gate` 作业**：与 `constants-gate` 并列执行，防止新增静默吞噬。

### 升级注意

- 覆盖代码 + 重启即可，**无数据库迁移、无新增依赖**、无配置变更；返回值、状态码与页面输出均未改变。
- 治理后日志量略有增加，均为 `WARNING` 级别且仅在异常分支触发，正常路径无额外开销。
- **测试**：全量 395 项通过；`check_excepts.py` / `check_constants.py` / `check_release.py` 三门禁全绿。

## [3.1.5] - 2026-11-01

**编辑器能力扩展**版本（非破坏性）。后台富文本新增 Markdown 编辑模式：文章正文、单页栏目内容、富文本碎片（含各自多语言译文字段）均可在表单内一键切换「富文本 | Markdown」，Markdown 模式带实时预览；「系统设置 → 编辑设置」可将新建内容的默认模式改为 Markdown。升级后默认仍为 CKEditor，老内容仍按原格式打开，老用户操作习惯零变化。**有数据库结构变更**（5 张表各新增 `*_md` / `*_format` 两列，迁移 `0011` 自动执行），**新增 1 个 Python 依赖**（`markdown`）。

### Added

- **后台富文本双模式编辑（文章/单页栏目/碎片）**：编辑器标题行新增「富文本 | Markdown」分段切换。Markdown 模式为等宽字体编辑区 + 实时预览（marked.js，300ms 防抖），支持插入图片（复用既有上传接口）与全屏；切换由 turndown.js / marked.js 在客户端双向转换，切向 Markdown 且有内容时弹二次确认（表格样式、字体字号、对齐等 Markdown 无法表达的排版会丢失）。
- **双写存储 + 格式标记**：新增 `content_md` / `content_format` 等同名两列（`articles`、`article_translations`、`columns`、`column_translations`、`fragments`）。Markdown 模式保存时 `content` 列写渲染后的 HTML（python-markdown，`extra`/`sane_lists`/`nl2br` 扩展，与前端 `breaks:true` 对齐），原文存 `*_md` 供编辑回填；`content` 列始终是 HTML，前台 8 套主题、搜索、内容 API、RSS/Sitemap 零改动。
- **「系统设置 → 编辑设置」页**：`Setting.editor_default_mode`（`ckeditor` / `markdown`，默认 `ckeditor`）控制新建内容的默认编辑模式；页面只读展示 `markdown` 依赖可用性便于排障；变更写审计日志。
- **编辑页模式判定**：记录自身 `*_format='markdown'` → Markdown 打开，否则跟随全局默认；老数据 `*_format` 默认 `'html'` 永远以 CKEditor 打开（升级无感）。
- **共享前端组件 `app/static/js/rich-editor.js`**：三处表单统一接线（data-* 属性驱动批量初始化）；CKEditor 脚本按需加载（Markdown 模式首屏不加载约 1MB 的 ckeditor.js）；marked 12.0.2 / turndown 7.2.0 自托管于 `app/static/vendor/`，不引 CDN。

### Changed

- **CKEditor 初始化改造**：三个表单的内联初始化迁移至 `rich-editor.js`，CKEditor 工具栏配置原样透传（视觉与功能与旧版一致）；文章「从 Word 导入」改为经 RichEditor 跨模式写入（Markdown 模式下导入内容自动转为 Markdown）。
- **版本回滚**：回滚后强制 `content_format='html'` 并清空 `content_md`（快照只存 HTML，避免与 Markdown 原文不一致），回滚成功提示已注明。
- **新增依赖**：`markdown>=3.7,<4.0`（纯 Python，活跃维护）；依赖缺失时后台不 500，Markdown 内容降级为纯文本转义并告警（兜底分支，正常部署不触发）。
- **常量与门禁**：`constants.Editor`（模式/格式取值），`check_constants.py` 新增 `'ckeditor'` 裸字面量门禁（`'markdown'` 因通知模块 `msgtype` 等语义不同不入门禁）。

### 升级注意

- 覆盖代码 + `pip install -r requirements.txt` + 重启即可，Alembic 自动执行 `0011`（5 张表加列 + 幂等种子 `editor_default_mode='ckeditor'`）；新列均无索引，兼容 MySQL 5.6。
- 升级后无需任何配置：默认编辑模式仍为富文本，老内容打开方式不变；需要 Markdown 默认模式的站点到「系统设置 → 编辑设置」切换。
- **测试**：新增 `test_markdown_render.py`（渲染/双写契约 13 项）与 `test_markdown_editor.py`（三处保存链路、编辑页模式判定、设置页读写、版本回滚 11 项）；全量 395 项通过。

## [3.1.4] - 2026-10-24

**依赖腐化专项治理**版本。全文搜索引擎从停更的 Whoosh + jieba 切换为活跃维护的 Tantivy + pkuseg（spacy-pkuseg）；放宽 redis / pytest / pytest-cov 版本约束；CI 测试矩阵扩展至 Python 3.13 / 3.14。有数据迁移（搜索引擎标识切换），无数据库结构变更。

### Changed

- **全文搜索引擎切换：Whoosh → Tantivy（内置默认）**：Whoosh 上游已停止维护（whoosh-reloaded 分叉亦停更且转 GPL），切换为 Rust 内核、活跃维护的 tantivy-py（`tantivy>=0.26,<1.0`），索引性能与相关度显著优于纯 Python 实现。`Setting.search_engine` 取值由 `whoosh` 改为 `tantivy`（`constants.Search.ENGINE_TANTIVY`），Alembic 迁移 0010 自动改写存量配置；残留未知引擎值（含旧 `whoosh`）启动时告警并回退 SQL LIKE，不抛异常。
- **中文分词切换：jieba → pkuseg**：jieba 0.42.1（2020）长期停更，切换为 `spacy-pkuseg>=1.0,<2.0`（活跃维护的 fork，原 pkuseg 0.0.25 停更早于 jieba）。新增 `app/utils/tokenizer.py` 统一分词入口：双检锁单例、ASCII 小写化、标点剥离，输出空格连接的分词串供 Tantivy 索引与查询。
- **索引架构调整：只存 uid / 内容类型 / 记录 ID，展示字段实时回库「水合」**：标题、正文、摘要仅索引不存储（Tantivy stored 字段存输入原文，若存分词后文本会导致结果标题带空格）；搜索结果按 ID 回库取原文，顺带解决 Whoosh 时代「结果快照陈旧」问题，多语言 `t_field` 解析与前台完全一致。
- **升级无感：启动自检 + 后台自动重建索引**：`create_app` 启动时检测默认语言索引标志文件（`meta.json`），缺失则通过 `O_EXCL` 原子占位文件防多 worker 并发，由 daemon 线程后台全量重建，重建期间搜索自动回退 SQL LIKE；TESTING 环境跳过。升级覆盖代码后无需手动点击「重建索引」。
- **放宽 redis 约束**：`redis>=5.0,<6.0` → `>=5.0,<9.0`（redis-py 7.x/8.x 向后兼容 5.x API，调用面仅 `from_url`/`ping` 与 Flask-Caching/Session/Limiter 封装）。
- **放宽开发依赖约束**：`pytest` 升级到 `>=8.0,<10.0`、`pytest-cov` 升级到 `>=5.0,<8.0`（已在 pytest 9.1.1 + pytest-cov 7.1.0 下全量回归通过）。
- **CI 测试矩阵扩展**：新增 Python 3.13（必过）与 Python 3.14（实验性，`continue-on-error`，待 spacy-pkuseg 发布 cp314 wheel 后转正）；矩阵现为 3.10 / 3.11 / 3.12 / 3.13 / 3.14。Docker 镜像维持 Python 3.12-slim 不变。

### Removed

- **依赖移除**：`Whoosh>=2.7.4,<3.0`、`jieba>=0.42.1` 从 requirements.txt 移除。

### 升级注意

- **pkuseg 模型首次初始化需下载约 60MB 模型文件**（`spacy_ontonotes.zip`，官方地址：https://github.com/explosion/spacy-pkuseg/releases/download/v0.0.26/spacy_ontonotes.zip；国内可用 ghfast.top 镜像：`https://ghfast.top/https://github.com/explosion/spacy-pkuseg/releases/download/v0.0.26/spacy_ontonotes.zip`）到 `~/.pkuseg/`（可用环境变量 `PKUSEG_HOME` 改路径）。离线/内网部署：预先放置 `~/.pkuseg/spacy_ontonotes.zip` 并解压出 `~/.pkuseg/spacy_ontonotes/`（内含 `features.msgpack` 与 `weights.npz`）即可完全离线运行；Docker 官方镜像已内置预热，无需处理。
- 未下载模型时搜索功能仍可用：分词器初始化失败的请求路径会告警并回退，SQL LIKE 兜底不受影响（建议升级后尽快保证模型就位以获得索引检索能力）。
- 覆盖代码 + `pip install -r requirements.txt` + 重启即可，Alembic 自动执行 0010 数据迁移，首次启动自动后台重建索引。
- **测试**：搜索测试模块改写（保留 3 项 + 新增 Tantivy 引擎级 5 项：水合原文、uid 替换去重、移除索引、特殊字符不炸、未知引擎回退）+ 新增分词器契约测试 6 项；全量 371 项通过。

## [3.1.3] - 2026-10-15

**性能与并发健壮性**版本（四项中危 M7-M10）。设置读取请求级缓存、浏览量计数写放大收口、首页 N+1 查询治理、用户名唯一性竞态兜底。无数据库结构变更、无新增 Python 依赖。

### Fixed

- **Setting 逐键查询写放大（M7，中危）**：单页渲染链路 `Setting.get()` 调用 20+ 次，每次一条 `first()` SQL。现新增请求级整表缓存（`flask.g`，`app/models/setting.py::_request_cache_map`）：同请求首查整表建映射，后续读零 SQL；`set()` 写后失效当前请求，同请求内写后立即可见；`get_dict()` 复用同一映射；无应用上下文（CLI）回退逐键查询。多 worker 场景无跨进程一致性问题。
- **浏览量逐请求写事务（M8，中危）**：文章详情每次访问 `viewed + 1` 即 `db.session.commit()`，高并发下写库压力大；且整页缓存命中时视图体不执行，缓存 TTL 内（默认 900s）浏览量完全不增长。现改为**缓存累加 + 合并回库**：`_incr_view()` 把增量累加到缓存键 `article:viewed:pending`（缓存不可用回落旧行为），新增 `_flush_view_counts()` 以 `UPDATE ... SET viewed = viewed + n` 合并回库；APScheduler 新增 60s 周期任务 `zhycms_view_flush`，多 worker（不启内置调度器）时由请求内阈值（累计 200 次）兜底触发；整页缓存命中路径显式调用 `_incr_view()`，修复缓存窗口内计数不增长。合并失败增量放回缓存不丢数；兜底 TTL 24h 防调度器长期停止时内存累积。
- **首页 N+1 查询（M9，中危）**：首页对 9 个行业区块 slug 逐个 `_home_column_articles()`（栏目 + 子栏目 + 文章各一条 SQL），叠加最新文章循环与导航树，单页 20+ 条 SQL。现收口为 `_home_section_data()` 批量拉取（栏目一次 `IN`、子栏目一次、跨栏目文章一次，共 3 条 SQL，内存分组取前 N，排序语义与原实现一致）；`Column.get_tree_cached()` 请求级缓存栏目树（导航 + 上下文处理器叠加只查一次），`clear_content_cache()` 统一失效，内容 CRUD 后同请求立即读到新树。
- **用户名唯一性竞态（M10，中危）**：`create_user` 先查重后插入存在并发竞态，`users.username` 唯一索引兜底时 flush/commit 抛 `IntegrityError` 未捕获 → 500。现 `flush()` 与 `commit()` 均捕获 `IntegrityError` 回滚并 flash「用户名已存在」业务错误。

### Changed

- **升级注意**：无数据库结构变更、无新增依赖，覆盖代码重启即可。浏览量统计语义从「逐请求即时写库」变为「缓存累加 + 周期（约 60s）/阈值（200 次）合并」，计数为近似值（误差窗口 ≤ 60s 或 200 次）；依赖精确逐次计数的场景请自行评估。
- **测试**：新增 14 项性能与并发用例（`tests/test_performance_m.py`，覆盖 M7-M10：SQL 计数、缓存失效、浏览量合并、缓存页计数、竞态回退、端点无 500）；全量 360 项通过。



## [3.1.2] - 2026-10-13

**安全修复**版本（五项中危 M1-M5）。表单整数输入保护、上传子目录路径白名单、CKEditor 反射型 XSS 防护、SVG 上传管控、登录验证码一次性消费。无数据库结构变更、无新增 Python 依赖。

### Fixed

- **表单 int() 输入保护（M1，中危）**：文章/栏目/碎片管理视图对 `sort_order`、`page_size`、`parent_id`、`gid`、`page`、`limit` 等表单参数直接 `int(...)` 转换，非数字输入触发 `ValueError` 返回 500。现新增 `app/utils/helpers.py::safe_int(value, default=0)`（strip + try/except 回退默认值），替换 `article_service` / `column_service` / `fragment` / `article` / `frontend.views` / `builder/widgets/data` 全部裸 `int()` 调用点；`page`/`limit`/`per_page` 同步加 `max(1, safe_int(...))` 拒负数。
- **上传子目录路径穿越（M2，中危）**：通用上传接口 `app/admin/upload.py` 的 `type` 参数此前无白名单，`app/utils/uploads.py::save_upload_file` 内 `os.path.join(UPLOAD_FOLDER, sub_dir, date_dir)` 存在 `../` 穿越面。现新增 `ALLOWED_SUB_DIRS` 白名单 + `_safe_sub_dir()` 归一化（剥离两侧 `/` 与 `\\`、含 `..` 段直接回退、首段必须在白名单内、其余段匹配 `^[a-zA-Z0-9_-]{1,32}$`）；上传入口先归一化、`save_upload_file` 内二次校验，纵深防御。
- **CKEditorFuncNum 反射型 XSS（M3，中危）**：`app/admin/upload.py` 把用户输入的 `CKEditorFuncNum` 直接拼到 `<script>` 字符串里返回，可注入 `</script><script>alert(1)</script>`。现 `func_num` 仅接受 `^\d{1,6}$`，非法直接 400；`file_url` 与 `err` 经 `html.escape(..., quote=True)` 转义后再拼入 JS 字符串。
- **SVG 上传管控（M4，中危）**：LOGO 上传表单 `allowed_exts` 含 `svg`，全站 CSP 允许 `script-src 'unsafe-inline'`，构成存储型 XSS 向量。现默认 `upload_allow_svg=off`，开启后做内容嗅探（拒绝 `<script` / `onload=` / `onclick=` / `href="javascript:"` / `<foreignObject` / `onerror=` / `onmouseover=`）+ 512KB 大小上限；`.svg` 静态响应附加 `Content-Type: image/svg+xml` + `nosniff` + `CSP: sandbox; default-src 'none'`，兜底防护存量 SVG。后台「上传安全」页新增 SVG 开关。
- **登录验证码不随失败失效（M5，中危）**：`app/admin/auth.py` 在密码错误分支不 `session.pop('captcha')`，导致同一验证码可被反复复用，密码错误计数失效。现校验通过后**无论密码比对结果**先 `session.pop('captcha', None)` 一次性消费，再走后续锁定/比对流程。

### Changed

- **升级注意**：v3.1.2 不改业务行为，仅补安全修复。若曾依赖 SVG 上传（如 LOGO）需到后台「上传安全」打开「允许上传 SVG」开关，且 SVG 内容会做嗅探。
- **测试**：新增 26 项中危安全修复用例（`tests/test_security_m.py`，覆盖 M1-M5 各场景）；全量 346 项通过。

## [3.1.1] - 2026-10-11

**安全修复**版本（两项高危 H1 + H2）。API 鉴权改为默认拒绝（fail-closed），全站引入 CSRF 同步 Token 校验。无数据库结构变更、无新增 Python 依赖。

### Fixed

- **API 默认免鉴权（H1，高危）**：内容 API 静态令牌校验此前在「未配置令牌」时匿名放行，而默认安装 `api_token` 为空，导致 `/api/v1/*` 全部端点可被任意匿名读取。现改为 **fail-closed**：未配置令牌时一律返回 401（提示到后台「内容 API」生成），配置令牌后校验 `X-API-Token`（恒时比较）。`api_enable=off` 站点不受影响；JWT 鉴权路径行为不变。
- **全站缺失 CSRF Token（H2，高危）**：此前全站仅有 Origin/Referer 同源校验（且无头请求放行），无会话绑定 Token。现新增 CSRF 同步 Token 机制：
  - 新增 `app/utils/csrf.py`：Token 与用户 Session 绑定，`before_request` 对 POST/PUT/PATCH/DELETE 强制恒时比较校验，未携带/错误 → 403；
  - 前后台所有主题/后台模板统一注入 `<meta name="csrf-token">` 与自动提交捕获脚本（`app/static/js/csrf.js`）：普通表单提交自动附加 `_csrf_token` 隐藏字段，jQuery `$.post/$.ajax` 全局附加 `X-CSRF-Token` 请求头；
  - 手写 fetch/XHR 请求（文章 Word 导入、CKEditor 图片上传、页面构建器保存/发布/回滚/上传、一键翻译）逐处补齐 `X-CSRF-Token` 头；
  - 豁免范围：`/api/*`（以 `X-API-Token` / Bearer JWT 头鉴权，不依赖 Cookie，无 CSRF 风险）与 `/healthz`；Session 尚无 Token 的首个匿名 POST（如登录表单首次提交）放行并开始建立 Token；
  - 与既有 Origin/Referer 同源校验互为纵深，两者同时保留。

### Changed

- **升级注意**：升级到 v3.1.1 后，使用内容 API 的调用方必须在后台「内容 API」设置中生成令牌并以 `X-API-Token` 请求头携带，否则返回 401（详见 UPGRADE.md）。
- **测试**：新增 CSRF 防护 9 项、API fail-closed 5 项用例；测试脚手架 `client` fixture 统一自动携带 CSRF Token 与 API Token。全量 309 项通过。

## [3.1.0] - 2026-10-10

**数据库迁移插件**版本。新增官方内置插件 `db_migrator`（默认不启用）：在后台把 SQLite 开发库一键迁移到 MySQL / PostgreSQL——目标库建表 → 按外键依赖逐表复制数据（单事务失败整体回滚）→ PostgreSQL 自动重置自增序列 → 同步 Alembic 版本号（重启时不重复执行增量迁移）；支持连接测试、目标库非空保护（需显式勾选覆盖）、迁移后立即热切换引擎免重启。同时修复文章批量操作不更新搜索索引的问题，并修复后台用户管理表单字段与业务层脱节导致的多项账号管理异常。无数据库结构变更、无新增 Python 依赖。

### Added

- **数据库迁移插件（db_migrator，官方内置，默认不启用）**：
  - 后台「插件管理」启用后出现「数据库迁移」菜单（`db_migrator:manage` 权限门控，不向预设角色默认授权，仅超管或显式授权角色可用）。
  - 迁移流程：目标库建表（`db.Model.metadata.create_all`，覆盖模式先 `drop_all` 本系统已知表）→ 按 `sorted_tables` 拓扑序逐表复制行数据（每批 500 行，单事务失败整体回滚）→ PostgreSQL 目标库重置整型主键序列（`setval`）→ 同步源库 `alembic_version` 版本号（重启时识别为「已管理」，避免对已存在的表重复执行增量迁移）。
  - 安全机制：目标库与本系统同名表已有数据时拒绝迁移，勾选「覆盖目标库已有数据」才清空重迁；迁移前先测试目标库连通性；全流程高危警告与提交确认。
  - 生效方式：迁移完成自动落盘 `instance/db_config.json`（重启生效，删除该文件即可放弃切换）；勾选「迁移后立即切换」时复用安装向导同款 `switch_engine` 热切换引擎，免重启即时生效（切换失败自动回滚配置继续用旧库），并清空整站缓存。
- **测试**：本版本周期新增 16 个用例（数据库迁移插件核心逻辑与路由 8 项、文章批量操作索引同步 1 项、后台用户管理 7 项），全量 296 项通过。

### Fixed

- **文章批量操作搜索索引不同步**：批量发布/撤回/删除/归档/移动/提交审核此前只清栏目缓存、未逐篇更新索引，导致 Whoosh 等索引型后端与数据库状态不一致；现批量操作提交后逐篇触发索引更新（与单篇保存路径同一钩子链）。
- **后台用户管理表单与业务层脱节**：重写用户表单模板对齐 `user_service` 字段，修复「新增账号两次输入密码一致却提示不一致」、新增账号默认禁用、角色未绑定、昵称丢失、重置密码校验失败等问题；并增加非超管无法通过表单授予超管权限的防护逻辑。

### Notes

- `db_migrator` 插件默认不启用，现有站点升级后行为无任何变化；仅「本地 SQLite 开发 → 服务器 MySQL/PostgreSQL」场景启用使用。
- 典型用法：后台 **插件管理** → 启用「数据库迁移」→ **系统设置 → 数据库迁移** → 填写目标库连接信息 → 测试连接 → 开始迁移（可选「迁移后立即切换」免重启生效）。

## [3.0.0] - 2026-09-15

**可视化页面构建器**版本。新增自研轻量拖拽式页面构建器（原生 HTML5 拖拽 + JSON Schema 组件注册 + iframe 内服务端真实渲染），覆盖首页、单页、列表页、文章详情页四种全页面类型；内置 24 个 Bootstrap4 组件（布局 6 + 基础 8 + 数据 10），支持草稿/发布/修订回滚、中英双语文案、语言白名单与会员可见性、桌面/平板/手机三端预览、全局页面样式设置（背景/页脚/标题色/圆角/边框/阴影）。**默认布局三层合并**：新建构建页按「当前启用主题 fixture → 核心回退」解析基础布局，再叠加已启用插件贡献的布局片段（`get_builder_layouts()` + `builder/<scope>.json`，启用强校验、撞 id 自动重写、卸载清理）；轮播图/产品/招聘/教程四个内容型插件启用后新首页开箱即用。插件还可通过 `get_builder_widgets()` 钩子注册自有组件，插件禁用/卸载时前台静默降级、后台卸载前做布局引用拦截。采用「构建器为主、手写模板永久兜底」双轨策略：只有已发布布局的页面才走构建器，老站升级后零行为变化。**数据库结构变更**：新增迁移 `0009`（`builder_pages` / `builder_revisions` 两张表）。无 Node 构建链、无新增 Python 依赖（编辑器为原生 ES module）。

### Added

- **可视化页面构建器（核心）**：
  - 四作用域：网站首页 / 单页（page 栏目）/ 列表页（list 栏目）/ 文章详情页（支持栏目级布局 + 全局默认回退）。
  - 24 个内置组件：section/container/grid-row/grid-col/spacer/divider；heading/text/richtext/image/button/icon-box/alert/video-embed；article-list/article-detail/page-content/breadcrumb/fragment/carousel/contact-card/cta-banner/friend-links/stat-numbers。
  - 编辑器：组件库、iframe 真实主题画布（服务端渲染，非模拟）、属性面板（文本/多行/富文本/数字/下拉/开关/颜色/图片上传/图标预设/栏目选择/站内链接选择/碎片下拉/重复项）、图层树、拖拽排序与嵌套、复制/删除/上移下移、三端设备切换与全屏预览模态框（按真实设备宽度）、CKEditor5 富文本、800ms 防抖自动存草稿、未保存离开提示。
  - 发布工作流：草稿/已发布双版本隔离（匿名访客只见已发布版）、每次发布生成修订快照、一键回滚（回滚即发布并再记快照）、从默认布局初始化向导、页面管理四分组列表与未构建栏目快捷入口。
  - 预览：`/admin/builder/preview/<id>` 仅登录可访问，注入真实导航/SEO/栏目/文章/分页/上下篇数据，禁用组件显示黄色占位，单组件取数或渲染异常不拖垮整页。
  - 主题适配：8 套主题（default/blue/manufacturing/service/catering/education/default_en/manufacturing_en）全部验证可渲染；组件支持 `themes/<theme>/builder/widgets/*.html` 主题级覆写。
- **布局 JSON Schema v1**：服务端 allowlist 校验（组件类型/props 白名单/select 双向类型兼容/repeater 子字段/localized 语言键）、最大嵌套深度 8、单页节点上限 300、文档体积上限 256KB；非法草稿/发布返回 400。
- **全局页面样式**：`layout.styles` 页面级背景/页脚配色/标题色/圆角/边框/阴影，服务端白名单生成 CSS，预览与生产共用同一规则。
- **默认布局三层解析（v3.0.0 开发周期迭代）**：
  - 新建构建页与「默认布局」按**当前启用主题**解析：优先 `themes/<theme>/builder/<scope>.json`，主题未覆写回退核心 fixture，快照入草稿后切主题不回填。
  - **第三方上传主题**可自带 `builder/<scope>.json`，上传时按同一套 `validate_layout` 校验，非法整包拒绝；resolve 带 slug 正则 + realpath 纵深防护。
  - **8 套官方主题必备 `builder/home.json`** 成为官方主题规范（测试逐主题强制），default/blue 主题补齐首套首页 fixture。
- **插件贡献默认布局片段**：插件包内 `builder/<scope>.json`（scope 仅 home/page/list/article，`position` prepend/append + 可选 `after` 锚点），`PluginBase.get_builder_layouts()` 默认自动扫描；启用插件前对片段跑同一套 `validate_layout` 强校验（非法拒绝启用）；快照合并按 slug 升序、撞 id 自动加 owner 前缀重写、单片段失败隔离跳过、卸载同步清理；只做一次性快照，已有草稿/已发布页绝不被改写。
- **四内容型插件构建器开箱即用**：banner 新增 `banner-hero` 首屏轮播组件（home 片段 prepend）；product/recruit/tutorial 各新增 `product-list` / `job-list` / `tutorial-list` 数据组件与「标题 + 组件」首页区块（append），模板放插件 `templates/builder/widgets/`。
- **多语言与可见性**：文本类 props 支持 `{zh, en}` 多值并按当前语言回退；节点支持 `visibility.locales` 语言白名单与 `member_only` 会员限定。
- **插件联动**：`PluginBase.get_builder_widgets()` 注册钩子（owner=插件 slug，随插件启用状态门控）；插件卸载前若仍有页面引用其组件则拒绝卸载并列出引用页面；插件被禁用后生产渲染空、预览标黄占位、完全未知类型静默跳过。
- **权限与审计**：新增权限点 `builder:manage`（content_auditor/content_editor）与 `builder:publish`（仅 content_auditor）；创建/发布/回滚/删除写入审计日志（`audit` 模块新增 `builder` 分类）。
- **文档**：新增 [docs/PAGE_BUILDER.md](docs/PAGE_BUILDER.md)（用户手册 + 组件开发 API + 插件贡献片段约定）；[docs/PLUGIN_DEV.md](docs/PLUGIN_DEV.md) 补充 `get_builder_widgets` / `get_builder_layouts` 章节；wiki.html、SECURITY.md、UPGRADE.md 同步 v3.0.0。
- **测试**：v3.0.0 开发周期新增 139 个用例（组件注册表与插件门控、Schema 校验边界、四作用域双轨 HTTP、8 主题渲染矩阵、主题 fixture 解析与第三方主题校验、插件布局片段合并/启用拦截/四插件真实数据端到端、分页/伪静态/发布清缓存、i18n/会员可见性、后台 RBAC 角色矩阵与发布工作流），全量 280 项通过。

### Changed

- 前台 `index` / `column_detail`（page/list）/ `article_detail` 视图接入双轨：存在已发布构建布局时走构建器渲染（缓存键仍含分页/语言/主题），无布局时渲染既有手写模板，伪静态路由无需改动自动复用。
- 侧边栏新增「页面构建」一级菜单（受 `builder:manage` 权限门控）。

### Notes

- 升级后所有页面默认仍走手写模板；在「页面构建」中创建并**发布**布局后，对应页面才切换到构建器，删除构建记录即回退（首页记录不可删除，可清空后发布）。
- 不做 header/footer/导航可视化，不提供独立落地页；构建器只接管内容区。
- 富文本编辑器复用既有自托管 CKEditor5；图片上传复用 `/admin/upload`。

## [2.6.4] - 2026-09-12

**前台会员体系 + 插件依赖治理**版本。新增社区插件「前台用户中心」（member），提供用户注册/登录/资料编辑/修改密码/找回密码、微信与 QQ 一键登录、短信验证码登录、注册协议管理、栏目会员可见性控制；核心新增 `Column.member_only` 字段与前台访问守卫钩子；插件系统新增依赖（`requires`）、继承（`extends`）、最低核心版本（`min_core_version`）启用强校验与禁用反向依赖校验。**数据库结构变更**：新增迁移 `0008`（`columns.member_only` 列），member 插件首次启用时自动创建 `members` / `member_oauths` / `member_sms_codes` 三张表。无新增 Python 依赖（复用既有 `requests`）。

### Added

- **前台用户中心插件 `member`（社区插件，非内置）**：
  - 会员体系独立于后台管理员：`members` 表（用户名/密码哈希/昵称/头像/邮箱/手机/性别/签名/状态/登录锁定）、`member_oauths` 表（微信/QQ 第三方绑定）、`member_sms_codes` 表（短信验证码哈希存储），session 键 `member_id` 与后台 Flask-Login 完全隔离。
  - 前台功能页：注册（含协议弹窗）、登录（密码 + 短信验证码双 Tab）、找回密码（手机验证码重置）、会员中心、个人资料编辑（含头像上传）、修改密码、退出。
  - 短信验证码三通道：日志通道（默认，验证码写日志）、阿里云短信（免 SDK，RPC HMAC-SHA1）、通用 Webhook（`{phone}`/`{code}` 占位符）；60 秒间隔 + 每日 10 条频控，码值 SHA-256 哈希存储、一次性消费。
  - 微信/QQ 一键登录：`oauth/<provider>` 授权跳转，回调支持三种分支——已绑定直接登录、已登录则绑定、未绑定按配置自动建号；state 参数防 CSRF。
  - 后台管理：会员列表（关键词/状态搜索、分页）、会员编辑（资料/状态/重置密码）、软删除、插件设置页（4 分组：注册开关与富文本注册协议 / 短信通道 / 微信 / QQ）、栏目可见性树形批量勾选，统一权限 `member:manage`。
  - 右上角用户菜单：游客显示「登录/注册」按钮，已登录会员显示头像+昵称下拉菜单（会员中心/个人资料/修改密码/退出），不占用主导航位置。
  - 前台模板内置于插件 `templates/frontend/`，直接 `render_template` 渲染，8 套主题 navbar 自动注入用户菜单。
- **栏目会员可见性**（核心）：`Column` 模型新增 `member_only` 布尔字段（迁移 `0008`），栏目编辑页「仅会员可见」开关（仅 member 插件启用时显示）。前台未登录用户访问 `member_only` 栏目及其文章自动 302 跳登录页；主导航对游客隐藏会员栏目；已登录会员绕过整页缓存，避免缓存串页。
- **插件守卫钩子**（核心）：`PluginBase.get_frontend_guard()` 返回 `{'is_authenticated': callable, 'login_url': callable}` 或 `None`，核心通过该钩子解耦会员鉴权，无插件守卫时 `member_only` 不生效。
- **插件依赖 / 继承 / 最低版本强校验**（核心，详见 [PLUGIN_DEPENDENCIES.md](PLUGIN_DEPENDENCIES.md)）：
  - `manifest.json` 新增 `requires`（`string[]`，启用前必须已启用的依赖插件）、`extends`（`string`，父插件，须已安装且已启用）、`min_core_version`（`string`，最低核心版本）三个可选字段。
  - `enable_plugin()` 启用前按「最低核心版本 → requires → extends」顺序强校验，不满足拒绝启用并返回明确错误信息。
  - `disable_plugin()` 新增反向依赖校验：若有已启用插件依赖或继承该插件，拒绝禁用并提示需先禁用哪些。
  - `discover_and_load()` 启动期校验 `extends` 父插件是否已安装，缺失则标红。
  - 插件上传校验新增 `requires`/`extends`/`min_core_version` 字段类型校验。
  - 后台插件列表以徽章展示最低核心版本（蓝）、依赖插件（黄）、父插件（紫）。
  - `PluginBase` 新增 `requires` / `extends` / `min_core_version` 类属性（与 manifest 对应，类属性优先）。

### Changed

- 版本号 `CMS_VERSION` 由 `2.6.3` 升级为 `2.6.4`。
- 8 套主题 `base.html` 在 navbar 右侧 `locale_switcher` 前注入 `{{ member_user_menu() }}`（插件未启用时输出空字符串）。
- `app/plugin_system.py` 新增 `parse_version()` / `version_cmp()` / `current_core_version()` / `validate_enable()` / `reverse_dependents()` 函数。
- `app/frontend/views.py` 新增前台访问守卫：`_frontend_authenticated()`、`_member_only_redirect(column)`，`_try_cache` 对已登录会员绕过整页缓存，`_build_nav()` 对游客过滤 `member_only` 栏目，`column_detail()` / `article_detail()` 加会员访问守卫。

### Fixed

- member 插件 `_render()` 函数重复拼接 `.html` 后缀导致 `TemplateNotFound`。
- member 插件 `settings.py` 的 `cfg()` 默认值兜底失效（核心 `Setting.get` 对未知键返回 `''`，改用哨兵区分「无记录」与「显式关闭」）。
- 禁用 member 插件时前台缓存可能残留会员栏目 302，新增 `on_disabled` 清空缓存。

### Security

- 会员密码使用 werkzeug `generate_password_hash`（与后台一致），短信验证码 SHA-256 哈希存储且一次性消费。
- OAuth 回调使用 state 参数防 CSRF。
- 会员头像上传走核心统一上传校验（扩展名 + MIME + 去重），非法类型拒绝。
- 会员独立 session 键 `member_id`，与后台管理员会话互不干扰。

### Upgrade

- **数据库迁移**：执行 `flask db upgrade` 应用迁移 `0008`（给 `columns` 表补 `member_only` 列，默认 `FALSE`，存量栏目不受影响）。
- **启用会员插件**（可选）：后台「插件管理」启用 `member` → 首次启用自动建 `members` / `member_oauths` / `member_sms_codes` 表 → 进入「前台用户中心 → 插件设置」配置短信通道与微信/QQ 密钥 → 进入「前台用户中心 → 栏目可见性」勾选需会员登录才能访问的栏目。
- **短信通道**：默认日志通道（验证码写入应用日志），生产环境切换为阿里云或 Webhook 通道。
- **插件依赖校验**：现有插件无需改动；自定义插件如需声明依赖，在 manifest.json 中添加 `requires` / `extends` 字段即可。

## [2.6.3] - 2026-09-12

**API 鉴权升级 + 行业模板扩充**版本。REST API 鉴权从单一静态 Token 升级为 JWT（access/refresh 双 token），支持 token/jwt/both 三模式双轨兼容，引入 flask-limiter 速率限制；新增教育（亮色调）与餐饮（暖色调）两套行业主题及配套演示数据。**新增 7 项 Setting，无数据库结构变更**，覆盖代码重启即可升级。

### Added

- **JWT 鉴权体系**（`app/api/auth.py`）：`POST /api/v1/auth/login` 签发 access_token（15min）+ refresh_token（7d）；`POST /api/v1/auth/refresh` 用 refresh_token 换新 access_token；`POST /api/v1/auth/logout` 客户端删 token。identity 为 `str(user.id)`，额外信息放 `additional_claims`。
- **双轨鉴权模式**（`app/api/views.py` `_api_gate`）：`api_auth_mode` 支持 `token`（仅 X-API-Token）/ `jwt`（仅 Bearer JWT）/ `both`（默认，优先 JWT 回退 Token）。auth 端点免鉴权，refresh 由 `@jwt_required(refresh=True)` 自处理。
- **速率限制**（`flask-limiter`）：登录端点 5 次/分钟，只读 GET 端点 120 次/分钟，超限返回 429；可在后台 API 设置页开关与调整阈值。
- **后台 API 设置页**（`app/admin/templates/admin/setting/api.html`）：新增鉴权模式、JWT 密钥、access/refresh 过期时间、限流开关与阈值配置。
- **教育行业主题**（`themes/education/`）：天蓝 #42a5f5 + 活力橙 #ff9800 亮色调，背景 #f5fafd，展现青少年朝气。
- **餐饮行业主题**（`themes/catering/`）：暖红 #c0392b + 橙 #e67e22 暖色调，营造食欲氛围。
- **setup 向导行业联动**：新增「教育行业」「餐饮行业」演示数据选项，自动切换对应主题与站点信息。
- **行业演示数据**（`app/utils/bootstrap.py`）：`generate_demo_education`（启明教育培训学校：课程中心/师资力量/校园动态）、`generate_demo_catering`（鲜味居酒楼：招牌菜品/门店信息/美食资讯）。
- **新增测试**：`tests/test_api_auth.py`（9 项：JWT 登录/刷新/双轨兼容/速率限制）、`tests/test_themes.py`（6 项：education/catering 主题完整性）。

### Changed

- `requirements.txt` 新增 `Flask-JWT-Extended>=4.6.0,<5.0`、`Flask-Limiter>=3.5.0,<4.0`。
- CORS 响应头 `Access-Control-Allow-Headers` 增加 `Authorization`，Methods 增加 `POST`。
- `Setting.DEFAULTS` 新增 7 项：`api_auth_mode`、`jwt_secret_key`、`jwt_access_expires_minutes`、`jwt_refresh_expires_days`、`api_rate_limit_enable`、`api_rate_limit_login`、`api_rate_limit_read`。

### Fixed

- JWT `InvalidSubjectError`：identity 必须为字符串，改用 `str(user.id)`，额外信息放 `additional_claims`。
- 主题切换后各页面主题不一致：根因是后台 `theme_activate` 切换 `site_theme` 后未清空前台整页缓存，而缓存键不含主题标识，旧主题渲染的 HTML 在 TTL 内继续命中。修复为切换后无条件 `cache.clear()`，并在前台页面缓存键追加 `|theme=<slug>` 作为纵深防御（多 worker / 清理失败时仍不串页）。

## [2.6.2] - 2026-09-11

**质量加固**版本。补齐 5 大测试域（RBAC 权限边界 / 插件全生命周期 / Alembic 迁移 / API 契约 / 存储驱动抽象），测试规模 34 → 113 项；`oss_storage` 存储驱动抽象升级：驱动自动发现 + 字节流上传契约 + 归属插件门控。**无数据库结构变更**，覆盖代码重启即可升级。

### Added

- **RBAC 栏目级权限边界测试**（`tests/test_rbac_boundary.py`，17 项）：权限矩阵（无授权 / 单栏目授权 / 多栏目 / 全站授权）、路由与装饰器路径双覆盖、超管绕过、跨栏目数据隔离（授权编辑看不到未授权栏目文章）。
- **插件全生命周期测试**（`tests/test_plugin_lifecycle.py`，20 项）：启用 → 使用 → 禁用 → 重新启用全链路，验证路由 / 模板函数 / 菜单 / API 端点注册与清理、数据保留（禁用不删表）、权限种子幂等、视图守卫 404。
- **Alembic 迁移测试**（`tests/test_migrations.py`，9 项）：版本图线性无分叉、upgrade/downgrade 幂等、模拟生产 bootstrap（create_all → stamp 0001 → upgrade heads）、核心表结构与种子设置完整性校验。
- **API 契约测试**（`tests/test_api_contract.py`，17 项）：统一响应包 `{"code","message","data","meta"}` 结构、/site /columns /articles 端点字段契约、`api_enable`/`api_token` 门控（off 全端点 404、缺 token 401）、CORS 白名单 / 通配回显、曝光规则（草稿 / 已删除 / 停用栏目一律 404）、分页 meta 与 `per_page` 钳制（1..50）。
- **存储驱动抽象层测试**（`tests/test_storage.py`，16 项）：驱动注册表、归属插件门控回退、LocalStorageDriver 功能、`CloudStorageDriver` 字节流上传契约。
- **`oss_storage` 驱动自动发现**：插件启动时 `pkgutil` 扫描 `drivers/` 包，顶层 `CloudStorageDriver` 子类自动收集注册，新增云厂商只需新增驱动文件，零改动插件其它代码。
- **`CloudStorageDriver.save_bytes` 字节流上传契约**：默认经临时文件中转 `_put_object`，子类可覆写 `_put_bytes` 改用 SDK 原生字节流接口；`drivers/base.py` 补充新增云厂商驱动开发契约文档（必填类属性 / 方法清单）。

### Changed

- **存储驱动按「归属插件」门控**（`app/utils/storage.py`）：`register_driver` 新增 `owner_slug` 参数，驱动注册表记录归属插件；插件禁用后其驱动在 `get_driver` 中自动回退 `LocalStorageDriver`，替代原先写死 `OSS_PLUGIN_SLUG` 的单插件判断，任意插件均可安全注册驱动。
- pytest 注册 5 个新标记：`boundary` / `lifecycle` / `migration` / `contract` / `storage`。
- `tests/conftest.py`：种子数据移入独立 app context 并及时关闭，修复 flask-login 跨请求缓存 `g._login_user` 导致的登录失效；种子流程先建权限点再建角色。
- `tests/factories.py`：`make_user` 改为直接写 `UserRole` 关联行，修复角色绑定不落库。

### Fixed

- `app/utils/uploads.py` 重复文件检测引用已删除的 `_cloud_plugin_enabled` 私有函数，改用公开的 `_driver_allowed`，云端驱动的重复上传检测恢复正常。

---

## [2.6.1] - 2026-09-10

**架构与可维护性**版本。蓝图注册抽离、admin 按业务域分目录、引入 service 层剥离业务逻辑、插件热加载线程安全文档化与缓存优化。**无数据库结构变更**，覆盖代码即可升级。

### Added

- **`app/blueprints.py`**：蓝图注册从 `create_app` 抽离到独立模块，封装插件加载 → 注册蓝图 → CORS → 错误处理全流程，`create_app` 瘦身 25 行。
- **`app/services/` 业务逻辑层**：新增 `article_service.save_article`、`column_service.save_column`、`user_service.create_user/update_user`，将路由内联的业务逻辑（表单校验、DB 写入、审计日志、缓存清理）抽离到 service，路由层只负责 HTTP 协议转换。service 函数不依赖 `request`/`current_user` 全局对象，数据通过参数显式传入，返回 `(result, messages)` 由调用方 flash。
- **admin 目录按业务域重组**：`app/admin/content/`（column/article/fragment）与 `app/admin/system/`（setting/users/audit/backup/themes）两个子包，endpoint 命名空间 `admin.*` 保持不变。
- **插件启用清单缓存**：`enabled_slugs()` 经 Flask-Cache 缓存 60s，`set_enabled_slugs()` 写入后主动失效；Redis 后端时跨 worker 自动失效，SimpleCache 时最坏 60s 自愈。
- **Docker 部署支持 MariaDB**：`docker-compose.yml` 新增 `--profile mariadb`（`mariadb:11.4` LTS，MySQL 协议兼容、PyMySQL 直连）；`install.sh` 数据库选择新增「3) MariaDB 11.4」，数据卷检测、镜像拉取、凭据校验全链路支持。
- **Docker 安装国内镜像加速**：`install.sh` 步骤 3 可选自动配置 dockerd `registry-mirrors`（4 个国内站、合并写入不覆盖已有配置、自动备份重启）；未配置时以「多源前缀拉取 + retag」兜底并覆盖全部镜像（含此前遗漏的 `redis:7-alpine`），单镜像多源回退 + 重试。

### Changed

- `run.py` 显式 `use_reloader=debug`，生产环境关闭 reloader 避免插件重复加载。
- `app/plugin_system.py` 补充线程安全 / 多 worker 保证文档：URL Map 仅启动期修改，运行时启停只写 DB。
- `scripts/check_constants.py` 白名单路径随 admin 子包重组更新（`app/admin/setting.py` → `app/admin/system/setting.py`）。

### Fixed

- admin 子包重组后函数体内延迟导入（`audit`/`users`/`setting`/`backup` 等 10 处）相对层级未同步，访问对应后台页报 `ModuleNotFoundError: No module named 'app.admin.models'`。
- 插件启用 / 禁用提示在插件管理页重复显示两行（base.html 与页面模板各渲染一次 flash）；同步清理备份页的重复渲染。
- `uninstall.sh` profile 清理列表补齐 `mariadb` 与 `redis`。

### Upgrade

- 纯代码重构，无数据库迁移。覆盖代码后重启即可。

## [2.6.0] - 2026-09-10

**工程化完善**版本。新增发布 Checklist、pytest 测试脚手架 + GitHub Actions CI、统一异常处理（403/404/500 三协议分发）、常量治理（消除硬编码、统一 `app/constants.py`）。**无数据库结构变更**，覆盖代码即可升级。

### Added

- **发布 Checklist（`RELEASE.md`）**：标准化的发布操作清单（版本一致性 → 迁移 → 翻译 → 文档 → 测试 → tag → 发布后验证），配合 `scripts/check_release.py` 自动校验 CMS_VERSION / CHANGELOG / README / wiki.html 版本号一致。
- **pytest 测试脚手架**：`tests/` 目录含 conftest fixture（隔离 SQLite + 临时索引目录 + session 注入登录）与 9 个测试文件（冒烟 / 认证 RBAC / 工作流 / 搜索 / i18n / 插件 / API / 异常处理 / 常量治理），34 项测试全绿。
- **GitHub Actions CI（`.github/workflows/ci.yml`）**：三 Python 矩阵（3.10/3.11/3.12）跑 pytest + 发布一致性检查 + 常量门禁，共 3 个 job。
- **统一异常处理（`app/errors.py`）**：全局接管 400/403/404/405/500 + HTTPException + 未知异常，按请求路径分发三种协议——`/api/` 返回 JSON、`/admin/` 返回后台模板、前台返回主题模板；新增 6 个主题 403.html + 3 个后台 errors 模板。
- **常量治理（`app/constants.py`）**：零依赖常量模块统一 Workflow / Upload / Locales / Search / Roles / Pagination 命名空间；收编散落在 models/utils/admin/plugins 中的 17 处硬编码字面量；`scripts/check_constants.py` CI 门禁防新增回流。
- **`TestingConfig`**：`app/config.py` 新增测试环境配置类（TESTING=True、CSRF 禁用、内存 SQLite）。

### Changed

- `app/models/workflow.py` 与 `app/models/rbac.py` 的状态/角色常量改为从 `app/constants.py` 重导出（向后兼容）。
- 上传扩展名白名单（图片/主题/插件/简历）统一引用 `constants.Upload`。
- 搜索引擎名（whoosh/meilisearch）统一引用 `constants.Search`。
- 4 个插件（banner/product/recruit/auto_translate）的角色预设名统一引用 `constants.Roles`。
- `app/frontend/views.py` 的 404/500 错误处理迁移至 `app/errors.py` 统一注册。

### Upgrade

- **无数据库迁移**：覆盖代码重启即可。
- **CI 自动运行**：push 到 main 或提 PR 时 GitHub Actions 自动跑测试 + 检查；本地可 `pip install -r requirements-dev.txt && pytest`。
- **开发依赖**：`requirements-dev.txt` 含 pytest/pytest-cov/pytest-timeout。

---

## [2.5.2] - 2026-09-09

**一键翻译插件**版本。新增官方内置插件「一键翻译」，在文章、栏目、碎片、产品、表单、招聘、友情链接等编辑页的「多语言版本」标签页中提供一键翻译按钮，把默认语言（中文）的标题、摘要、正文、SEO 字段自动翻译填充为目标语言。**无数据库结构变更**，启用插件并配置翻译服务密钥后即时可用。

### Added

- **新增内置插件 `auto_translate`（一键翻译）**：
  - 编辑页多语言 Tab 自动出现「一键翻译为 XX」按钮；点击后收集默认语言内容调用翻译接口，译文回填到对应语言字段，人工校对后保存（不自动写库）。
  - 富文本（正文/单页内容）按 HTML 翻译，保留排版标签；普通字段按纯文本翻译。
  - 支持 4 种翻译服务：**百度通用翻译**（APP ID + 密钥）、**有道智云文本翻译**（应用 Key + 密钥）、**Google Cloud Translation v2**（API Key）、**DeepSeek 大模型**（API Key，OpenAI 兼容，长文/富文本排版保持最佳，也可改接口地址接入通义/智谱/Kimi 等）。
  - 长文按「块级标签 / 换行」安全边界自动分片，规避百度/有道单请求长度限制。
  - 插件设置页：服务商选择、凭证配置（密钥留空不覆盖）、「测试当前服务商」一键连通性验证。
  - 权限分离：超级管理员配置凭证（`auto_translate:manage`），内容编辑/内容审核角色可直接使用（`auto_translate:use`，启用时自动授予）。
  - 插件禁用时不注入任何脚本，翻译接口 404，对后台零影响。
- 核心仅新增一处模板钩子：后台 `base.html` 在 `{% block js %}` 前调用 `auto_translate_assets()`（插件未启用时由核心守卫输出空字符串）。
- **全文搜索纳入插件内容**：新增插件搜索提供者机制（`PluginBase.get_search_provider()` 钩子 + `app/utils/search.py` 的 `SearchProvider` 协议），插件自有内容（如产品）可进入全站搜索。
  - 「产品展示」「招聘管理」插件内容现已进入全站搜索：产品与岗位的标题、简介、正文（含英文翻译）均可被检索（岗位另支持按部门/地点/薪资搜索）；保存/删除/上下架/批量操作实时同步索引。
  - 索引文档以 `uid`（`类型:id`）+ `type` 区分内容类型，各类型不再互相覆盖；搜索结果按类型自动生成详情链接（文章 → 文章页，产品 → 产品页，岗位 → 岗位页）。
  - Whoosh 搜索结果补充返回摘要（schema `summary` 改为存储），结果列表可显示摘要片段。
  - 索引后端零命中时的实时 SQL 兜底同步覆盖插件内容；旧版索引（v2.5.2 前 schema）在首次写入时自动重建自愈。
  - Whoosh / Meilisearch / SQL LIKE 三后端同步支持；插件禁用时自动从索引移除其内容。
- **英文搜索页 i18n 修复**：四个中文主题 `search.html` 硬编码文案（搜索结果/统计行/未找到匹配结果）改为多语言；`messages.po` 补英文词条。
- **插件结构化内容多语言**：产品「规格参数」与招聘「所属部门/工作地点/薪资待遇」支持按语言维护。
  - `product_translations` 新增 `specs` 列（JSON 结构同主表），`recruit_job_translations` 新增 `department/location/salary` 列（Alembic 迁移 0007，启动时自动增量迁移）。
  - 后台编辑页多语言 Tab 可直接维护对应语言的规格参数与岗位结构化字段；前台详情/列表、内容 API、全站搜索（含 SQL 兜底）均按当前语言展示/召回，本地化规格参数文本同步纳入全文检索。
  - 「产品展示」「招聘管理」插件版本升级至 1.1.0。
- **核心翻译自动编译**：应用启动时若 `app/translations/*/LC_MESSAGES/messages.mo` 缺失或落后于 `.po` 自动编译（`.mo` 不入库，避免英文等语种全站 `_()` 回退中文）。
- 索引检索补充已发布状态过滤，避免召回草稿/归档。

### Changed

- 版本号 `CMS_VERSION` 由 `2.5.1` 升级为 `2.5.2`。

### 升级说明

- v2.5.x 站点：`git pull` → 重启应用（首次启动会自动编译翻译 `.mo`，并自动执行 Alembic 迁移 `0007` 补产品规格参数/岗位结构化字段翻译列）→ 后台「插件管理」启用「一键翻译」→ 进入「一键翻译」配置页选择服务商并填写密钥（可点「测试当前服务商」验证）→ 在任意内容编辑页的多语言 Tab 点「一键翻译」。
- 启用「产品展示」「招聘管理」的站点，插件随核心升级至 1.1.0，历史数据与翻译无缝保留。
- 翻译结果为机器翻译，发布前请人工校对。
- 本次索引结构有调整（新增 `uid`/`type` 字段）：升级后产品保存时会自动重建旧索引；也可到后台「系统设置 → 搜索设置」点一次「重建索引」使全部存量产品/岗位立即纳入全文检索。

## [2.5.1] - 2026-09-08

**全文检索国际化（i18n 搜索）**版本。在 v2.5.0 内容级多语言基础上，让全站搜索按当前语言检索对应语言的内容。**无数据库结构变更**，升级后到后台「系统设置 → 搜索设置」点击一次「重建索引」即可。

### Added

- **全文检索支持多语言**：Whoosh / Meilisearch / SQL LIKE 三个搜索后端全部按当前 locale 检索。
  - Whoosh 按语言分索引目录 `instance/search_index/<locale>/`；Meilisearch 按语言分索引 `zhycms_articles_<locale>`。
  - 每篇文章对每种语言写入一份索引文档，内容经 `t_field` 解析——有翻译用翻译，无翻译回退默认语言（与前台 `t()` 渲染表现完全一致，未翻译文章不会因切换语言而搜不到）。
  - 栏目名同步按语言索引，搜索结果中的栏目名称随语言切换。
  - 前台 `/search` 按当前语言（`?lang=xx` / session）检索对应语言索引；该语言索引尚未建立时自动回退默认语言索引。
  - 文章保存/删除时自动同步更新全部语言索引（复用 v2.4.0 的 `clear_content_cache` 钩子）。
  - 后台「搜索设置 → 重建索引」一键重建全部语言索引；健康检查分语言显示文档数（如 `zh:120, en:98`）。

### Changed

- 版本号 `CMS_VERSION` 由 `2.5.0` 升级为 `2.5.1`。
- `search_articles()` 新增 `locale` 参数；Whoosh 索引根目录由单层 `instance/search_index/` 改为 `<locale>/` 子目录（重建时自动清理旧单层结构）。

### 升级说明

- v2.5.0 站点：`git pull` → 重启应用 → 后台「系统设置 → 搜索设置」点击「重建索引」（生成各语言索引）。
- i18n 未开启的站点行为与 v2.5.0 完全一致（仅维护默认语言单一索引）。
- 无数据库迁移、无新增依赖。

## [2.5.0] - 2026-09-07

**内容级多语言（i18n 2.0）+ Redis 缓存与 Session**，企业出海刚需版本。无破坏性变更，覆盖代码 + 执行迁移即可升级。

### Added

- **内容级多语言（i18n 2.0）**：文章/栏目/碎片/产品/表单/岗位/友情链接支持多语言版本存储。
  - 新增 `article_translations`、`column_translations`、`fragment_translations` 三张核心翻译关联表（Alembic 迁移 `0005`），以及 `product_translations`（产品 title/summary/content/seo_*）、`form_translations`（表单 name/description/success_message）、`recruit_job_translations`（岗位 title/description）、`friend_link_translations`（友情链接名称）四张插件翻译表（Alembic 迁移 `0006`）。
  - 主表保留默认语言字段（冗余），翻译表存非默认语言；查不到翻译时 fallback 默认语言。
  - 前台模板新增 Jinja 全局 `t(obj, field)`，6 套主题共 44 个模板的内容字段已接入，产品详情/列表卡片、表单页文案、岗位列表/详情、友情链接名称同步适配。
  - 后台文章/栏目/碎片编辑页新增「多语言版本」Tab，产品/表单/岗位/友情链接编辑页同批接入，按语种切换录入翻译；富文本翻译字段使用 CKEditor5 与主编辑器一致。
  - 碎片仅翻译内容值（名称不随语言变化），友情链接仅翻译名称（URL/LOGO 不随语言变化）。
  - 栏目/文章前台 SEO（meta title/keywords/description）按当前语言取翻译，无翻译回退主表。
  - 产品 API（列表/详情/上下篇）按当前语言返回内容，API 缓存键加入 locale。
  - `slug` 不随语言变化，URL 保持稳定；语言切换沿用 `?lang=xx` + session 机制。
  - 页面缓存键加入 locale，不同语言互不串扰（含产品详情页缓存）。
- **Redis 缓存后端 + 服务端 Session**：
  - 应用启动时自动检测环境变量 `REDIS_URL`：有值且 Redis 可达 → 启用 RedisCache + Flask-Session 存 Redis，支撑多实例负载均衡；否则回退 SimpleCache + Cookie Session，单机部署零依赖。
  - 后台「系统设置 → Redis 缓存」只读状态页：展示当前运行状态（已启用/未启用/连接失败），未启用时引导安装 Redis 并设置环境变量；不提供手动开关，避免运行时切换导致状态不一致。
  - `docker-compose.yml` 新增可选 `redis` profile（redis:7-alpine + 256MB LRU），`install.sh` 新增 Redis 交互选项。

### Changed

- 版本号 `CMS_VERSION` 由 `2.4.2` 升级为 `2.5.0`。
- `requirements.txt` 新增 `redis>=5.0,<6.0`、`Flask-Session>=0.8,<1.0`。
- 移除后台左侧菜单「个人资料」「修改密码」两项（与右上角用户下拉菜单重复）。

### Fixed

- 修复前台文章详情页浅拷贝对象丢失 `translations` 关系导致多语言翻译无法渲染的问题。
- 修复 `t_field` 依赖 babel 缓存 locale 导致 `?lang=` 切换不生效的问题，改为直接调用 `select_locale()`。
- 修复产品编辑页规格参数分组渲染报 `TypeError: 'builtin_function_or_method' object is not iterable`（`g.items` 命中 dict 内置方法而非键值）。
- 修复栏目/文章前台 `_seo()` 未按当前语言取翻译 SEO 字段的问题。

### 升级说明

- v2.4.x 站点：`git pull` → `pip install -r requirements.txt` → `flask db upgrade` → 重启应用。
- 启用多语言：后台「系统设置 → 国际化」开启，配置默认语言与可用语种，编辑内容时在「多语言版本」Tab 录入翻译。
- 启用 Redis：设置环境变量 `REDIS_URL=redis://127.0.0.1:6379/0` 后重启应用；Docker 部署在 `install.sh` 中选择启用 Redis。
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

[Unreleased]: https://gitee.com/pollybird/zhycms/compare/v2.5.2...HEAD
[2.5.2]: https://gitee.com/pollybird/zhycms/compare/v2.5.1...v2.5.2
[2.5.1]: https://gitee.com/pollybird/zhycms/compare/v2.5.0...v2.5.1
[2.5.0]: https://gitee.com/pollybird/zhycms/compare/v2.4.2...v2.5.0
[2.4.2]: https://gitee.com/pollybird/zhycms/compare/v2.4.1...v2.4.2
[2.4.1]: https://gitee.com/pollybird/zhycms/compare/v2.4.0...v2.4.1
[2.4.0]: https://gitee.com/pollybird/zhycms/compare/v2.3.0...v2.4.0
[2.3.0]: https://gitee.com/pollybird/zhycms/compare/v2.2.0...v2.3.0
[2.2.0]: https://gitee.com/pollybird/zhycms/compare/v2.1.1...v2.2.0
[2.1.1]: https://gitee.com/pollybird/zhycms/compare/v2.1.0...v2.1.1
[2.1.0]: https://gitee.com/pollybird/zhycms/compare/v2.0...v2.1.0
[2.0.0]: https://gitee.com/pollybird/zhycms/compare/a717ad4...v2.0
[1.1.0]: https://gitee.com/pollybird/zhycms/compare/v1.0...a717ad4
[1.0.0]: https://gitee.com/pollybird/zhycms/releases/tag/v1.0
