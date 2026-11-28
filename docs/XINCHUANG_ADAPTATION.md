# 信创数据库适配专题

本文说明 ZhyCMS 的信创数据库适配现状、已验证范围，以及 GBase 等未适配数据库的自行适配参考。

> **结论先行**：官方已**实现并验证 openGauss**（v3.3.0，x86_64 + aarch64/鲲鹏）、
> **人大金仓 KingbaseES V9**（v3.3.1，pg 兼容模式，x86_64 + aarch64/鲲鹏）、
> **达梦 DM8**（v3.3.2，x86_64 + aarch64/鲲鹏）与
> **PolarDB for PostgreSQL**（v3.3.3，Apache 2.0 开源自托管；x86_64 已实测，aarch64 由 CI 覆盖）。
> **信创适配阶段性收尾（v3.3.3）**：官方信创数据库适配到此告一段落，后续不再新增数据库适配计划。
> 南大通用 GBase 系列（8a / 8c / 8s）**官方不再计划适配**，本文相关章节仅作为自行适配的参考资料，
> 不构成支持承诺。如有需要，可参照 openGauss / KingbaseES / 达梦 DM8 / PolarDB 的代码、测试与部署文档
> 自行完成适配。
>
> **授权提示**：KingbaseES 与达梦 DM8 均为商业软件，项目仅提供适配代码，
> 安装包、客户端工具与授权文件需用户自行从官方下载并获取官方授权
> （KingbaseES：<https://www.kingbase.com.cn/download.html>；
> 达梦：<https://www.dameng.com/>）。

## 一、适配现状

| 数据库 | 兼容基础 | 官方状态 | 验证范围 |
| --- | --- | --- | --- |
| openGauss 7.0 | PostgreSQL 协议 + 自有方言差异 | **已实现**（v3.3.0） | x86_64 + aarch64（鲲鹏）；迁移 `0020`、向导、业务读写、备份恢复 |
| 人大金仓 KingbaseES V9 | PostgreSQL 协议（pg 模式，`sys_` 系工具与系统表） | **已实现**（v3.3.1，pg 模式） | x86_64 + aarch64（鲲鹏）；迁移 `0020`、向导、业务读写、备份恢复、健康检查 |
| 达梦 DM8 | Oracle 风格自有协议（`dmPython` 驱动 + `dmSQLAlchemy` 方言） | **已实现**（v3.3.2） | x86_64 + aarch64（鲲鹏）；迁移 `0020`、初始化向导、自增主键、备份恢复、健康检查 |
| PolarDB for PostgreSQL 15 | PostgreSQL 协议（Apache 2.0 开源） | **已实现**（v3.3.3） | x86_64 已实测；aarch64 由 CI 覆盖；迁移 `0020`、向导、业务读写、备份恢复、健康检查、Compose 编排 |
| PolarDB-X | MySQL 协议（分布式） | 未实现 | 无 |
| 南大通用 GBase 8a | MySQL 协议（分析型 MPP） | **官方不再计划适配** | 无 |
| 南大通用 GBase 8c | PostgreSQL / openGauss 系（分布式） | **官方不再计划适配** | 无 |
| 南大通用 GBase 8s | Informix 系自有协议 | **官方不再计划适配** | 无 |

说明：GBase 三条产品线差异很大，官方不再计划适配；如需自行适配，请先确认具体产品线与版本，
并参照下方「3.4 南大通用 GBase」及已被官方验证的同类协议实现（KingbaseES / 达梦 DM8 / PolarDB）自行完成。

## 二、通用适配架构

openGauss 的适配已经形成一套可复用的接入框架。新增数据库时，原则上只改「连接层 +
方言层 + 运维工具映射」，不引入 ORM 之外的数据库抽象层，也不在业务代码中写厂商分支。

| 层 | 位置 | 需要做的事 |
| --- | --- | --- |
| 方言注册 | `app/utils/dialects/`、`app/__init__.py` | 新增方言模块；在 `db.init_app()` 之前注册；必要时注册 Alembic DDL 实现 |
| URI 与驱动 | `app/utils/dbconfig.py` | 增加 scheme、默认端口、驱动探测与中文错误提示；支持 TCP / Unix socket |
| 引擎参数 | `app/config.py::build_engine_options()` | 连接池、`connect_timeout`、`application_name` 等按方言设置 |
| 初始化向导 | `app/admin/auth.py`、`app/admin/templates/admin/setup.html` | 新增单选与端口联动；后台显示数据库名称 |
| 备份恢复 | `app/utils/backup_utils.py` | 按方言选择导出/导入工具与参数风格；支持工具目录环境变量 |
| 健康检查 | `app/frontend/views.py` | `/healthz?detail=1` 输出正确的 `db_dialect` |
| 测试 | `tests/`、`.github/workflows/compat.yml` | 方言单测 + 集成冒烟（默认 skip，由环境变量启用）；CI 增加服务容器 |

实现顺序建议：先跑通「连接 → 迁移 → 向导 → 业务读写」，再补备份恢复与健康检查，
最后补测试与文档。任何一步未实测，都必须在文档中标注「未验证」。

## 三、分库适配思路

### 3.1 人大金仓 KingbaseES V9（pg 兼容模式）—— 已实现（v3.3.1）

KingbaseES 以 PostgreSQL 为兼容基础，是最接近 openGauss 的路径。v3.3.1 已在
**V9R1C10 的 pg 模式**下完成端到端适配与验证，覆盖 **x86_64** 与
**aarch64（鲲鹏）** 双架构，详见下文「九、KingbaseES V9 实测记录」与
[docs/DEPLOY_KINGBASE.md](DEPLOY_KINGBASE.md)、[docs/KINGBASE_ARM_TEST_REPORT.md](KINGBASE_ARM_TEST_REPORT.md)。

- **驱动与 URI**：连接与迁移**复用标准 PyPI `psycopg2-binary`**（KingbaseES 为 PG 线
  协议兼容，实测可直接连通），无需金仓官方专用驱动，也无需 `LD_LIBRARY_PATH` 即可
  连接。URI 为 `kingbase+psycopg2://system:pwd@host:54321/db`。
- **方言与迁移**：参照 [opengauss.py](../app/utils/dialects/opengauss.py) 新增
  [kingbase.py](../app/utils/dialects/kingbase.py)，仅覆盖
  `_get_server_version_info`（KingbaseES 的 `select version()` 返回
  `KingbaseES V009R001C010`，标准 PG 方言会抛 `AssertionError`），改用
  `SHOW server_version`（实测 `12.1`）解析为 `(12, 1)`，并注册 `KingbaseImpl`
  供 Alembic 按 `dialect.name` 查表。全量迁移 `0001→0020` 成功，public 表数 54。
- **备份恢复**：工具为 `sys_dump`（备份，stdout 纯 SQL，直接管道 gzip）/ `ksql`
  （恢复）。**密码通过 `KINGBASE_PASSWORD` 环境变量注入**——KingbaseES 的
  `ksql` / `sys_dump` / `sys_restore` **不识别 `PGPASSWORD`**（与 openGauss 不同，
  openGauss 用 `-W` 参数）。工具路径支持 `ZHYCMS_KINGBASE_BIN` / `KINGBASE_BIN` /
  `ZHYCMS_DB_DUMP_BIN_DIR`；`LD_LIBRARY_PATH` 需指向客户端 `lib`（应用不为 KingbaseES
  自动注入，与 openGauss 不同）。
- **与 openGauss 的关键差异**：
  - openGauss 需要官方 psycopg2 驱动 fork + `LD_LIBRARY_PATH`；KingbaseES 连接复用
    标准 `psycopg2-binary`，**无需驱动变体镜像**（默认 `pollybird/zhycms:latest` 即可）。
  - 密码环境变量：openGauss 用 `GS_PASSWORD` + 命令行 `-W`；KingbaseES 用
    `KINGBASE_PASSWORD`（不读 `PGPASSWORD`），命令行 `-w`。
  - 备份 stdout：openGauss `gs_dump` 有进度日志污染，需先落临时文件；KingbaseES
    `sys_dump` stdout 干净，可直接管道 gzip。
  - 版本编码：KingbaseES `server_version_num` 为 `major*10000+minor`（120001→(12,1)），
    非标准 PG 的 `major*10000+minor*100+patch`。
- **未覆盖 / 待验证**：仅 `DB_MODE=pg`；`oracle` / `mysql` / `sqlserver` 兼容模式、
  V8 系列暂未验证。
- **授权**：KingbaseES 为商业软件，镜像与授权文件需用户自行从
  <https://www.kingbase.com.cn/download.html> 获取；本项目不分发其二进制或许可证。

### 3.2 PolarDB for PostgreSQL —— 已实现（v3.3.3）

PolarDB for PostgreSQL 以 PostgreSQL 15 为兼容基础，源码遵循 **Apache License 2.0**，
是信创/开源场景中迁移成本最低的路径。v3.3.3 已完成端到端适配：**x86_64 已实测**，
**aarch64（鲲鹏）由 CI 矩阵覆盖**（官方镜像本身提供 `linux/arm64`），详见
[docs/DEPLOY_POLARDB.md](DEPLOY_POLARDB.md)。

- **驱动与 URI**：连接与迁移**复用标准 PyPI `psycopg2-binary`**（已在
  `requirements.txt`，无新增依赖），URI 形如
  `polardb_pg+psycopg2://user:password@host:5432/zhycms`。
- **方言与迁移**：新增 [polardb.py](../app/utils/dialects/polardb.py)，
  `PolarDBPGDialect` 继承 `PGDialect_psycopg2`，只做两件事：注册独立后端标识
  `polardb_pg`（便于向导、`/healthz` 与备份分支区分），以及父类版本解析失败时
  回退 `SHOW server_version`。PolarDB 的 `select version()` 返回
  `PostgreSQL 15.x (PolarDB 15.x.x.x build ...)`，标准 PG 正则可直接解析；
  DDL 完全复用 PostgreSQL，无需定制编译器。另注册 `PolarDBPGImpl` 供 Alembic
  按 `dialect.name` 查表。
- **备份恢复**：与 PostgreSQL 一致，使用 `pg_dump`（备份）与 `psql`（恢复），
  密码通过 `PGPASSWORD` 环境变量注入。工具路径支持
  `ZHYCMS_POLARDB_BIN`（可指向 `bin` 目录或 `POLARDB_HOME`）、
  `ZHYCMS_DB_DUMP_BIN_DIR` 与 PATH。`pg_dump` 主版本需与服务端一致（15）。
- **向导与健康检查**：初始化向导新增「PolarDB for PostgreSQL」选项，默认端口
  `5432`；`/healthz?detail=1` 返回 `db_dialect=polardb_pg`。
- **镜像与编排**：新增 `docker-compose.polardb.yml`，使用官方多架构镜像
  `polardb/polardb_pg_binary:15`（也提供阿里云 ACR 地址），应用镜像为
  `pollybird/zhycms:polardb`（内置 `postgresql-client`）。Apache 2.0 许可允许
  仓库直接编排并分发镜像名，无需像金仓/达梦那样由用户自行获取。
- **未覆盖**：PolarDB-X 为 MySQL 协议、云上集群版的管理接口与共享存储（PFS）
  部署均未验证；11 / 17 主版本镜像存在但未做端到端验证。

### 3.3 达梦 DM8 —— 已实现（v3.3.2）

DM8 是 Oracle 风格的自有数据库。v3.3.2 已基于 PyPI 的 `dmpython` 驱动与
`dmSQLAlchemy` 方言完成端到端适配，并在 **x86_64 本地** 与 **华为云鲲鹏 ARM
（aarch64，EulerOS 3.0）** 完成验证（30 项测试全绿），详见
[docs/DEPLOY_DM.md](DEPLOY_DM.md) 与 [docs/DM8_ARM_TEST_REPORT.md](DM8_ARM_TEST_REPORT.md)。

- **驱动与 URI**：`pip install -r requirements-dm.txt` 安装 `dmpython` 与
  `dmSQLAlchemy`（均为 PyPI wheel，x86_64 / aarch64 均有产物），无需安装达梦
  客户端即可连接。URI 形如 `dm+dmPython://user:password@host:5236/SCHEMA`；
  方言会把 URI 的 database 段作为 Schema 使用。
- **方言与迁移**：新增 [dm.py](../app/utils/dialects/dm.py)，在 `dmSQLAlchemy`
  基础上注册 `dm` / `dm.dmPython` 两个方言名，并注册 `DMImpl` 供 Alembic 按
  `dialect.name` 查表。上游方言只在 `column.autoincrement is True` 时生成
  `IDENTITY`，而本项目模型使用 `Column(Integer, primary_key=True)`（默认
  `'auto'`），因此方言层覆盖 `get_column_specification`，为单列整数主键补齐
  `IDENTITY(1, 1)`；复合主键与显式 `autoincrement=False` 不补。全量迁移
  `0001→0020` 与 `db.create_all()` 均已实测通过。
- **备份恢复**：逻辑备份使用 `dexp`（导出二进制 DMP，应用侧 gzip 为
  `.dmp.gz`），恢复使用 `dimp`；密码通过 `USERID=user/password@host:port`
  传给工具（达梦工具不支持 `PGPASSWORD` 类环境变量）。工具路径支持
  `ZHYCMS_DM_BIN`（可指向 `bin` 目录或 `DM_HOME`）、`ZHYCMS_DB_DUMP_BIN_DIR`
  与 PATH。
- **向导与健康检查**：初始化向导新增「达梦 DM8」选项，默认端口 `5236`；
  「数据库名」对应 Schema（通常与用户名同名）；`/healthz?detail=1` 返回
  `db_dialect=dm`。
- **授权**：达梦 DM8 为商业软件，安装包、客户端工具与授权需用户自行从
  <https://www.dameng.com/> 获取；本项目不分发其二进制或许可证。

### 3.4 南大通用 GBase（官方不再计划适配，仅供参考）

**官方不再计划适配 GBase 系列。** 本节仅保留自行适配的参考思路，不构成支持承诺。
建议先阅读已被官方验证的同类协议实现，按「方言 / 驱动 / URI / 备份工具 / 向导 / 测试」分层自行落地：

- [DEPLOY_KINGBASE.md](DEPLOY_KINGBASE.md)：pg 协议、复用 `psycopg2-binary`、`sys_dump` / `ksql` 备份恢复；
- [DEPLOY_DM.md](DEPLOY_DM.md)：自有协议 + 专用驱动（`dmpython` + `dmSQLAlchemy`）、`dexp` / `dimp`；
- [DEPLOY_POLARDB.md](DEPLOY_POLARDB.md)：开源 pg 协议、内置方言、`pg_dump` / `psql` 与 Docker 编排。

若自行适配 GBase，可按产品线参考：

- **GBase 8a（MySQL 协议，分析型 MPP）**：可尝试复用 `mysql+pymysql`。需自行验证
  外键、事务、`AUTO_INCREMENT`、字符集与分布式表 DDL 限制；备份工具为集群侧
  `gcdump` 等，需按版本核验。
- **GBase 8c（PostgreSQL / openGauss 系，分布式）**：可复用 openGauss / PostgreSQL
  方言作为起点；重点是分布式建表所需的分布键、节点拓扑与 DDL 限制，以及
  `gs_dump` 类工具的可用性。
- **GBase 8s（Informix 系）**：协议与 SQL 方言均不同，工作量最高；需要专用
  驱动与独立方言，备份工具为 Informix 系（`dbexport` / `dbimport` 等），
  不建议与 8a/8c 共用适配方案。

## 四、工作量与风险矩阵

| 数据库 | 方言改造 | 驱动接入 | 备份工具 | 迁移风险 | 综合评估 |
| --- | --- | --- | --- | --- | --- |
| KingbaseES V9 | 小（复用 PG） | 小（复用 psycopg2-binary） | 小（`sys_dump`） | 低-中 | **已实现**（v3.3.1，pg 模式，x86_64 + aarch64/鲲鹏） |
| PolarDB for PostgreSQL 15 | 极小（复用 PG） | 极小（复用 psycopg2-binary） | 小（`pg_dump`/`psql`） | 低 | **已实现**（v3.3.3，Apache 2.0；x86_64 已实测，aarch64 由 CI 覆盖） |
| PolarDB-X | 小 | 极小 | 云平台为主 | 中（分布式 DDL） | 未实现（MySQL 协议，不在本次范围） |
| 达梦 DM8 | 中（复用 dmSQLAlchemy） | 小（`dmpython` wheel） | 中（`dexp`/`dimp`） | 中-高 | **已实现**（v3.3.2，x86_64 + aarch64/鲲鹏） |
| GBase 8a | 中 | 小 | 中 | 中-高（事务/外键） | 官方不再计划适配；可自行参照 KingbaseES / openGauss 文档 |
| GBase 8c | 中 | 小 | 中 | 中（分布键） | 官方不再计划适配；可自行参照 openGauss 文档 |
| GBase 8s | 大 | 大 | 大 | 高 | 官方不再计划适配；预计自行适配成本最高 |

以上为经验判断，实际以目标版本、部署形态与业务 SQL 复杂度为准。

## 五、贡献指南

官方已不再新增信创数据库适配计划（含 GBase 系列）。社区如需自行适配，可参考本文的
分层思路、已验证后端（openGauss / KingbaseES / 达梦 DM8 / PolarDB）的代码与测试，
以及下方提交要求；官方不对 GBase 等未适配数据库提供支持承诺。

### 1. Issue 需提供的信息

- 数据库产品、版本、CPU 架构与部署形态（单机 / 主备 / 分布式 / 云托管）；
- 驱动名称与版本、Python 版本、SQLAlchemy 版本；
- 迁移结果（`alembic_version`、表数量、失败脚本与报错）；
- 已验证项与未验证项清单；
- 与 MySQL / PostgreSQL / openGauss 的 SQL 或 DDL 差异。

### 2. 代码贡献范围

- 方言与注册：`app/utils/dialects/`、`app/__init__.py`；
- URI、端口、驱动探测与错误提示：`app/utils/dbconfig.py`；
- 引擎参数：`app/config.py`；
- 初始化向导与显示：`app/admin/auth.py`、`setup.html`；
- 备份恢复映射：`app/utils/backup_utils.py`；
- 健康检查：`app/frontend/views.py`；
- 测试：`tests/` 下的方言单测与集成用例；CI：`.github/workflows/compat.yml`；
- 文档：部署指南、故障速查、支持矩阵与验证状态。

### 3. 提交要求

1. 不引入 ORM 之外的数据库抽象层，不在业务代码中写厂商分支；差异收敛在方言与
   工具映射层。
2. 默认部署行为不变：未选择新数据库时，MySQL / PostgreSQL / SQLite 行为不得变化。
3. 必须附带可复现的验证证据（迁移日志、关键表行数、CRUD 回读、备份恢复结果）。
4. 未实测的能力必须显式标注「未验证」，不得在文档中声称已支持。
5. 新增依赖放入可选 requirements 文件，不修改 `requirements.txt` 的默认安装集。
6. 通过现有门禁：`check_constants.py`、`check_excepts.py`、`check_openapi.py`、
   `check_release.py`、`git diff --check`，以及全量 pytest。

### 4. 参考实现

- 方言与注册：[app/utils/dialects/opengauss.py](../app/utils/dialects/opengauss.py)
- 连接与驱动探测：[app/utils/dbconfig.py](../app/utils/dbconfig.py)
- 备份恢复映射：[app/utils/backup_utils.py](../app/utils/backup_utils.py)
- 单元测试：[tests/test_opengauss_v330.py](../tests/test_opengauss_v330.py)
- 集成测试：[tests/test_compat_integration.py](../tests/test_compat_integration.py)
- 部署样例：[docs/DEPLOY_OPENGAUSS.md](DEPLOY_OPENGAUSS.md)

## 六、验证状态声明

除 openGauss 7.0（x86_64 + aarch64/鲲鹏）、openAMDC 1.0.0（x86_64 + aarch64/鲲鹏）、
**人大金仓 KingbaseES V9（pg 兼容模式，x86_64 + aarch64/鲲鹏）**、
**达梦 DM8（v3.3.2，x86_64 + aarch64/鲲鹏）**与
**PolarDB for PostgreSQL 15（v3.3.3，Apache 2.0；x86_64 已实测，aarch64 由 CI 覆盖）**外，
本文提及的南大通用 GBase 8a/8c/8s **官方不再计划适配**，PolarDB-X 尚未适配，均未验证；
相关章节仅作为自行适配的参考资料，不构成支持承诺。如需自行适配，请参照 KingbaseES、
达梦 DM8、PolarDB 等已验证后端的代码、测试与部署文档。
文中驱动名、工具名与差异点为适配方向，可能随产品版本变化，落地前请以目标环境的官方文档和实测结果为准。

### 多架构镜像

| 镜像 | x86_64 | aarch64 | 说明 |
| --- | --- | --- | --- |
| `pollybird/zhycms:mysql` / `:postgresql` / `:latest` | 已发布 | 已发布 | 同一 manifest，Docker 自动匹配当前架构 |
| `pollybird/zhycms:opengauss` | 已发布 | 已发布 | 内置对应架构的 openGauss psycopg2 驱动 |
| `pollybird/opengauss:7.0.0` | 已发布 | 已发布 | 内置 `openblas` 与 `libatomic` |
| `pollybird/openamdc:1.0.0` | 已发布 | 已发布 | 内置 `snappy`；aarch64 默认忽略 COW 告警 |
| `pollybird/zhycms:polardb` | 随 v3.3.3 发布 | 随 v3.3.3 发布 | 内置 `postgresql-client`（`pg_dump` / `psql`） |
| `polardb/polardb_pg_binary:15` | 官方已发布 | 官方已发布 | PolarDB 官方多架构二进制镜像 |

各镜像另提供 `*-amd64` / `*-arm64` 子标签便于单独拉取。应用镜像已完成双架构构建与
初始化验证；openAMDC 镜像完成双架构启动与 `PING` 验证；openGauss 数据库镜像完成
ARM 依赖与动态库校验，双架构启动由兼容性 CI 覆盖。

## 七、openGauss ARM 架构（aarch64/鲲鹏）实测记录

v3.3.0 发布后，在华为云鲲鹏 ARM 环境（Huawei Cloud EulerOS 3.0，aarch64）上对
openGauss 7.0 Lite 进行了端到端实测，验证结果如下：

### 环境信息

| 项目 | 值 |
| --- | --- |
| CPU 架构 | aarch64（鲲鹏） |
| 操作系统 | Huawei Cloud EulerOS 3.0 |
| openGauss 版本 | openGauss-Lite 7.0.0 build 2397a86f, aarch64-unknown-linux-gnu |
| Python 驱动 | openGauss-Python 7.0.0（aarch64），psycopg2 |
| 驱动安装路径 | `/tmp/opengauss/python-driver/`（需设置 `LD_LIBRARY_PATH` 与 `PYTHONPATH`） |

### ARM 架构依赖注意事项

openGauss Lite 在 aarch64 上运行需要以下系统库，部分发行版默认未安装：

- **`libopenblas.so.0`**：提供 `cblas_sgemv`、`LAPACKE_sgeqrf`、`LAPACKE_sorgqr` 等符号。
  若系统已有 scipy 内嵌的 openblas（如 `/usr/lib64/python3.x/site-packages/scipy.libs/libopenblas*.so`），
  可创建 wrapper `.so` 桥接符号；否则需安装 `openblas` 包。
- **`libatomic.so.1`**：提供 `__atomic_load_16`、`__atomic_store_16` 等 128 位原子操作。
  需安装 `libatomic`（GCC 运行时库），或编译带 `LIBATOMIC_1.0` 版本符号的 stub。

已发布的 `pollybird/opengauss:7.0.0` 与 `pollybird/zhycms:opengauss` 均已提供 **x86_64 / aarch64 多架构**镜像：数据库镜像内置 `openblas` 与 `libatomic`，应用镜像内置对应架构的 openGauss psycopg2 驱动，ARM 环境可直接使用。如需自定义构建，可显式指定 ARM 驱动地址：

```bash
docker build -t pollybird/zhycms:opengauss-arm \
  --build-arg INSTALL_OPENGAUSS_DRIVER=1 \
  --build-arg OPENGAUSS_PY_URL=https://opengauss.obs.cn-south-1.myhuaweicloud.com/7.0.0/openEuler22.03/arm/openGauss-Python-7.0.0-openEuler22.03-aarch64.tar.gz .
```

`docker-compose.opengauss.yml` 的两个服务均无需替换镜像（多架构标签会自动匹配当前架构）；如使用外部数据库，改用 `ZHYCMS_DB_URI` 指向即可。

### 实测结果（26 项全部通过）

| 类别 | 验证项 | 结果 |
| --- | --- | --- |
| 方言注册 | `opengauss+psycopg2://` URI 解析、方言版本返回 (9,2,4) | 通过 |
| Alembic DDL | `0020` 迁移建表（52 张表） | 通过 |
| 初始化向导 | openGauss 选项可选、建号成功 | 通过 |
| 业务读写 | 用户/角色/站点/栏目/文章/设置 CRUD | 通过 |
| Webhook | 订阅 CRUD、事件投递 | 通过 |
| 备份恢复 | `gs_dump` 导出、`gsql` 导入 | 通过 |
| 健康检查 | `/healthz?detail=1` 输出 `db_dialect=opengauss` | 通过 |
| 集成测试 | `test_compat_integration.py`（openGauss 2 项） | 通过 |

### CI 矩阵

`.github/workflows/compat.yml` 已扩展为 x86_64 + aarch64 双架构矩阵：

- x86_64：`ubuntu-latest` runner，数据库镜像 `pollybird/opengauss:7.0.0`，x86 驱动 URL
- aarch64：`ubuntu-24.04-arm` runner，数据库镜像 `pollybird/opengauss:7.0.0`，ARM 驱动 URL

两个 job 使用同一个多架构标签，runner 架构决定实际拉取的镜像变体；镜像已内置
`libopenblas` 与 `libatomic`，CI 无需再安装运行时依赖。两个 job 使用相同的
`GS_PASSWORD` / `GS_DB` 初始化参数与 ARM/x86 驱动。

`docker-compose.opengauss.yml` 也已添加 ARM 版本 `OPENGAUSS_PY_URL` 注释说明。

> 说明：上述 26 项结果为贡献者在鲲鹏 ARM 环境的实测记录。双架构 CI 已于 2026-11-22 在
> GitHub Actions 跑通：`openGauss migration smoke (x86_64)`、`openGauss migration smoke (aarch64)`
> 与 `openAMDC full test suite` 均通过（run 45018096964）。多架构镜像发布后，aarch64 job
> 已改为直接验证 `pollybird/opengauss:7.0.0`。

## 八、openAMDC ARM 架构（aarch64/鲲鹏）实测记录

v3.3.0 发布后，在华为云鲲鹏 ARM 环境（Huawei Cloud EulerOS 3.0，aarch64）上对
openAMDC 1.0.0 进行了端到端实测，验证结果如下：

### 环境信息

| 项目 | 值 |
| --- | --- |
| CPU 架构 | aarch64（鲲鹏） |
| 操作系统 | Huawei Cloud EulerOS 3.0 |
| openAMDC 版本 | 1.0.0 (git_sha1: 6758505d, build_id: 33e20a190bbc7819) |
| openAMDC 模式 | standalone |
| 编译器 | GCC 12.3.1 (openEuler) |
| Python | 3.12.5 |
| redis-py | 8.2.0 |

### 编译与安装

openAMDC 源码来自 [openeuler-mirror/openAMDC](https://github.com/openeuler-mirror/openAMDC)，
在 ARM 环境上直接 `make -j$(nproc)` 编译，总耗时约 20 分钟（含 RocksDB）。

**ARM 依赖注意事项**：RocksDB 依赖 `libsnappy`，部分 ARM 发行版默认未安装。
当前环境无 cmake，需手动从 snappy 1.2.1 源码编译：生成 `snappy-stubs-public.h` 后
用 g++ 直接编译 4 个 .cc 文件并创建 `libsnappy.a`。Docker 镜像中已预装此依赖，
容器部署无需额外处理。

### 实测结果（79 项全部通过）

| 类别 | 验证项 | 数量 | 结果 |
| --- | --- | --- | --- |
| 后端识别 | `redis_backend.describe()` 返回 `flavor=openamdc`、`version=1.0.0` | 3 | 通过 |
| 缓存读写与 TTL | SET/GET/DEL/TTL | 4 | 通过 |
| 会话存储 | `zhycms:sess:` 前缀 key 读写 | 2 | 通过 |
| 限流计数 | INCR 递增与 GET 回读 | 4 | 通过 |
| JWT 吊销黑名单 | SET NX 吊销、重复 SET NX 失败、EXISTS | 3 | 通过 |
| 健康检查 redis_flavor | INFO server 含 `openamdc_version`、无 `redis_version`、git_sha1 匹配 | 3 | 通过 |
| scan_iter 回退 | scan_iter 匹配多个 key | 1 | 通过 |
| 缓存前缀隔离 | `zhycms:cache:` 与 `zhycms:sess:` 互不干扰、清理缓存不影响会话 | 4 | 通过 |
| Lua 脚本原子性 | Lua INCR 20 次顺序递增 | 2 | 通过 |
| SET NX 分布式锁 | 获取锁、重复获取失败、GET 锁值 | 3 | 通过 |
| EXPIRE / PERSIST | TTL 修改与持久化 | 3 | 通过 |
| KEYS pattern | KEYS 匹配多个 key | 1 | 通过 |
| DBSIZE | DBSIZE 返回整数 | 1 | 通过 |
| Pipeline | 10 次 SET + 10 次 GET 批量操作 | 2 | 通过 |
| Transaction | MULTI/EXEC 原子事务 | 1 | 通过 |
| openAMDC 特有字段 | `worker_threads`、`openamdc_mode`、`openamdc_build_id` | 3 | 通过 |
| 最大内存策略 | CONFIG GET maxmemory-policy | 1 | 通过 |
| 复杂操作组合 | APPEND、SETRANGE | 2 | 通过 |
| Hash 操作 | HSET/HGET/HSET mapping/HLEN/HDEL/HEXISTS | 6 | 通过 |
| List 操作 | LPUSH/LRANGE/RPOP/LLEN | 4 | 通过 |
| Sorted Set 操作 | ZADD/ZRANGE/ZSCORE/ZREM/ZCARD | 5 | 通过 |
| SETEX / GETSET | SETEX/GET/GETSET | 3 | 通过 |
| MSET / MGET | 批量设置与获取 5 个 key | 2 | 通过 |
| TTL 语义 | 无 TTL key 的 TTL=-1、PERSIST 返回 False | 2 | 通过 |
| EXISTS 多 key | EXISTS 单 key/不存在/多 key | 3 | 通过 |
| TYPE 命令 | TYPE string/list | 2 | 通过 |
| **ZhyCMS 集成测试** | `test_compat_integration.py` TestOpenAMDC 4 项 | 4 | 通过 |
| **总计** | | **79** | **全部通过** |

### 关键结论

1. **openAMDC 1.0.0 在 ARM（aarch64/鲲鹏）上完全可用**：从源码编译、启动、到所有 Redis 协议操作均正常
2. **ZhyCMS v3.3.0 的 openAMDC 适配在 ARM 上零问题**：后端识别、缓存、会话、限流、JWT 吊销、Lua 脚本、分布式锁全部通过
3. **缓存前缀隔离修复已验证**：`zhycms:cache:` 与 `zhycms:sess:` 前缀互不干扰，清理缓存不会导致登出
4. **openAMDC 特有字段正确暴露**：`openamdc_version`、`openamdc_git_sha1`、`openamdc_mode`、`worker_threads` 等
5. **编译依赖注意事项**：ARM 上需手动安装 `libsnappy`（RocksDB 依赖），Docker 镜像中已预装

> 说明：上述 79 项为贡献者在鲲鹏 ARM 环境的实测记录。项目发布的 `pollybird/openamdc:1.0.0`
> 已提供 x86_64 / aarch64 多架构镜像，两个架构均完成启动与 `PING` 冒烟验证。

## 九、KingbaseES V9（pg 兼容模式，x86_64 + aarch64/鲲鹏）实测记录

v3.3.1 在 **x86_64** 与 **aarch64（鲲鹏）** 双架构环境下，用官方镜像（V9R1C10，
`DB_MODE=pg`）对 KingbaseES 进行了端到端实测，验证结果如下。

> **授权提示**：KingbaseES 为商业软件，本项目不分发其镜像与授权文件；镜像与授权请
> 自行从 <https://www.kingbase.com.cn/download.html> 获取。

### 环境信息

| 项目 | 值 |
| --- | --- |
| CPU 架构 | x86_64 |
| KingbaseES 版本 | V009R001C010（`select version()`） |
| 兼容模式 | `DB_MODE=pg` |
| 端口 / 管理账号 | `54321` / `system` |
| 版本串 | `SHOW server_version` = `12.1`；`SHOW server_version_num` = `120001` → `(12, 1)` |
| Python 驱动 | 标准 PyPI `psycopg2-binary`（无需专用驱动） |
| 客户端工具 | 镜像内 `/home/kingbase/install/kingbase/bin/{sys_dump,ksql,sys_restore}` + `lib/libkci.so` |

### 关键差异结论（相对 PostgreSQL / openGauss）

1. **必须自定义方言**：KingbaseES 的 `select version()` 返回 `KingbaseES V009R001C010`，
   标准 `postgresql+psycopg2` 方言的版本解析会抛 `AssertionError`，故必须用
   `kingbase+psycopg2://` 走内置方言。
2. **`server_version_num` 编码与标准 PG 不同**：KingbaseES 为 `major*10000+minor`
   （120001 → `(12,1)`），不是 PG 的 `major*10000+minor*100+patch`；方言按此解析。
3. **客户端工具不识别 `PGPASSWORD`**：`ksql` / `sys_dump` / `sys_restore` 只认
   `KINGBASE_PASSWORD`，应用据此注入，密码不进命令行。
4. **`sys_dump` stdout 干净**：与 openGauss `gs_dump` 不同，KingbaseES `sys_dump`
   的 stdout 是纯 SQL（无进度日志污染），可直接管道 gzip。
5. **连接复用标准 psycopg2**：无需金仓官方 Python 驱动，也无需 `LD_LIBRARY_PATH`
   即可连通；但备份/恢复的客户端工具需要 `LD_LIBRARY_PATH` 指向其 `lib`。

### 实测结果

| 类别 | 验证项 | 结果 |
| --- | --- | --- |
| 方言注册 | `kingbase+psycopg2://` URI 解析、方言版本返回 `(12, 1)` | 通过 |
| Alembic DDL | `0001→0020` 迁移建表（54 张表），`alembic_version='0020'` | 通过 |
| 初始化向导 | KingbaseES 选项可选、默认端口 54321 / 账号 system、连接测试通过 | 通过 |
| 业务读写 | 中文 / 布尔 / 时间回读、序列不回退 | 通过 |
| 备份恢复 | `sys_dump` 导出（gzip 首部 `-- Kingbase database dump`）、`ksql` 恢复到空库，表数一致 | 通过 |
| 健康检查 | `/healthz?detail=1` 输出 `db_dialect=kingbase` | 通过 |
| Compose 编排 | `docker-compose.kingbase.yml` 启动后应用连库建表、备份功能可用 | 通过 |
| 单元测试 | `tests/test_kingbase.py` 离线 27 项 + live 集成 3 项 | 通过 |

### CI 说明

KingbaseES 为商业软件，镜像与授权需用户自行获取，**本轮未接入 GitHub Actions CI**
（避免在公共 CI 中分发商业镜像）。集成测试 `tests/test_kingbase.py` 默认跳过，仅在
设置 `ZHYCMS_TEST_KINGBASE_URL` 后启用，供本地与私有化环境回归。

### aarch64 / 鲲鹏架构实测

v3.3.1 发布后，在华为云鲲鹏 ARM 环境（Huawei Cloud EulerOS 3.0，aarch64，kernel
6.6.0）上对 KingbaseES V9R1C10（V009R001C010B0004，从 ARM aarch64 Docker 镜像提取，
`DB_MODE=pg`，`SHOW server_version` = `12.1`）完成了端到端实测，详见
[docs/KINGBASE_ARM_TEST_REPORT.md](KINGBASE_ARM_TEST_REPORT.md)。

**环境**：Python 3.12.5 + 标准 `psycopg2-binary` 驱动，端口 `54321` / 账号 `system`。

**发现并修复的 DDL 问题**：KingbaseES 比 PostgreSQL 更严格，FK 引用列必须有显式
`UNIQUE CONSTRAINT`，仅 `UNIQUE INDEX` 不够——`Column(unique=True, index=True)` 在
PG 方言下只生成独立 `CREATE UNIQUE INDEX`，导致 `db.create_all()` 时 FK 约束失败。
为此在 [app/utils/dialects/kingbase.py](../app/utils/dialects/kingbase.py) 新增
`KingbaseDDLCompiler`（覆盖 `get_column_specification`，为缺表级 `UniqueConstraint`
的 `unique=True` 列补列级 `UNIQUE` 关键字），受影响列：`Permission.code`、`Role.code`、
`User.username`、`Site.slug`、`Site.subdomain`。该修复仅作用于 KingbaseES 方言层，
不影响 PostgreSQL 及其他后端。

**实测结果（55 项全绿）**：

| 类别 | 结果 |
| --- | --- |
| 单元测试 `tests/test_kingbase.py` | 修复前 28 passed / 2 failed → 修复后 **30 passed / 0 failed** |
| 端到端集成 | **25 passed / 0 failed**（方言注册、`db.create_all()`、CRUD、健康检查、备份恢复、UNIQUE 约束、Alembic 迁移） |
| `db.create_all()` | 51 张模型表全部创建成功 |
| Alembic 迁移 | `0001→0020` 全部执行，`alembic_version='0020'`（使用 `KingbaseImpl`） |
| `sys_dump` 备份 | 206,573 bytes，rc=0 |

> 说明：上述 55 项为贡献者在鲲鹏 ARM（aarch64）环境的实测记录。x86_64 与 aarch64
> 均已完成端到端验证，KingbaseES pg 兼容模式在双架构下可用。

## 十、PolarDB for PostgreSQL 15 实测记录（v3.3.3）

在 Linux x86_64 + Docker 环境使用官方镜像
`registry.cn-hangzhou.aliyuncs.com/polardb_pg/polardb_pg_binary:15`
（与 Docker Hub `polardb/polardb_pg_binary:15` 同源）完成端到端验证，实测版本：

```text
PostgreSQL 15.20 (PolarDB 15.20.5.0 build unknown) on x86_64-linux-gnu
```

| 类别 | 结果 |
| --- | --- |
| 实例初始化 | `docker/polardb/init.sh` 完成 `initdb -k`、创建 `zhycms` 账号与数据库、启动实例 |
| 容器重启 | `stop` 触发 `pg_ctl -m fast stop`；再次 `start` 跳过 initdb 与建库，幂等通过 |
| Alembic 迁移 | `alembic_version='0020'` |
| 建表 | `public` schema 共 **52** 张表（含 `alembic_version`） |
| 默认站点 | `sites` 表存在 `id=0`、`name=默认站点` |
| 联机测试 `tests/test_polardb.py` | 设置 `ZHYCMS_TEST_POLARDB_URL` 后 **27 passed / 0 failed**（含方言注册、CRUD、迁移、`/healthz`） |
| 离线测试 | 未设置联机地址时 **23 passed / 4 skipped** |
| `pg_dump` 备份 | **131,882 bytes**，含 52 条 `CREATE TABLE`，rc=0 |
| `psql` 恢复 | 导入全新数据库后 `public` 表数 **52**，rc=0 |
| 初始化向导 | `test_setup_accepts_polardb` 覆盖 `polardb_pg` 提交、默认端口 5432 与 URI 落盘 |
| aarch64 | 官方镜像含 `linux/arm64`，由 `compat.yml` 的 `polardb (aarch64)` job 覆盖；本地未实测 |

> 备份恢复使用 PolarDB 自带 `/u01/polardb_pg/bin/pg_dump` 与 `psql`，与 PostgreSQL
> 原生工具链一致；应用内备份分支已按 `polardb_pg` 后端接入。
