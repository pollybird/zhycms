# KingbaseES（人大金仓）部署指南（ZhyCMS v3.3.1）

> **授权声明（请务必先阅读）**：本项目**仅实现对 KingbaseES 的适配支持**。
> KingbaseES 是商业软件，其 Docker 镜像、客户端工具与授权文件（license）**均需用户
> 自行到官方下载并获取官方授权**，下载地址：
> <https://www.kingbase.com.cn/download.html>。
> 本仓库**不提供、不分发** KingbaseES 的镜像、二进制或许可证；使用前请确认已获得
> 合法授权。本文档中的镜像名、工具路径与命令均以官方 V9R1C10 版本为例（x86_64 与
> aarch64/鲲鹏均已端到端验证），请以你实际获取的官方版本为准。

本文说明如何让 ZhyCMS 运行在人大金仓 KingbaseES V9 的 **pg 兼容模式**
（`DB_MODE=pg`）上。应用侧通过内置方言支持 `kingbase+psycopg2://`，业务代码与
模型无需改动；连接与迁移复用标准 PyPI `psycopg2-binary` 驱动，**无需安装专用驱动**。

## 一、验证状态

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| KingbaseES V9R1C10（x86_64） | 已验证 | 实测镜像 `kingbase_v009r001c010b0004_single_x86:v1`，`DB_MODE=pg`，`SHOW server_version` 返回 `12.1` |
| 迁移至 `0020` | 已验证 | 54 张表，`alembic_version='0020'` |
| 初始化向导 / 业务读写 | 已验证 | 创建管理员、中文/布尔/时间回读、序列不回退 |
| 备份与恢复 | 已验证 | `sys_dump` 导出纯 SQL（直接管道 gzip），`ksql` 恢复到新库，表数一致 |
| Docker Compose 编排 | 已验证 | `docker-compose.kingbase.yml` 完成迁移与向导，应用镜像复用默认 `pollybird/zhycms:latest` |
| 健康检查标识 | 已验证 | `/healthz?detail=1` 返回 `db_dialect=kingbase` |
| aarch64 / 鲲鹏镜像 | 已验证 | 华为云鲲鹏 ARM（Huawei Cloud EulerOS 3.0，aarch64）实测通过，55 项全绿，详见 [docs/KINGBASE_ARM_TEST_REPORT.md](KINGBASE_ARM_TEST_REPORT.md) |
| 哨兵 / 集群 | 不适用 | 本项目只使用单个数据库连接串，HA 属部署侧能力 |

## 二、拓扑 A：Docker Compose（推荐）

仓库根目录的 `docker-compose.kingbase.yml` 会启动：

- `app`：`pollybird/zhycms:latest`（默认镜像已含 `psycopg2-binary`，**无需驱动变体**）；
- `db-kingbase`：用户自行加载的 KingbaseES 镜像（默认镜像名见下文 `KINGBASE_IMAGE`）；
- `db-init`：一次性容器，创建应用库 `zhycms`，并把 KingbaseES 的客户端工具
  （`ksql` / `sys_dump` 等）与动态库拷贝到共享卷 `kingbase_client`，供应用以只读方式挂载。

### 1. 加载官方镜像

先从官方获取 V9R1C10 的 Docker tar 包并加载（**镜像与授权请自行从官方下载获取**）：

```bash
docker load -i KingbaseES_V009R001C010B0004_x86_64_Docker.tar
# 加载后镜像名形如 kingbase_v009r001c010b0004_single_x86:v1
# 如你的镜像名不同，在 .env 中设置 KINGBASE_IMAGE 覆盖
```

### 2. 启动编排

```bash
cp docker/.env.example .env
# 至少修改 SECRET_KEY 与 KINGBASE_PASSWORD
docker compose -f docker-compose.kingbase.yml up -d

# 可选缓存 / 搜索
docker compose -f docker-compose.kingbase.yml --profile redis up -d
docker compose -f docker-compose.kingbase.yml --profile meilisearch up -d
```

访问 `http://localhost:5000` 完成初始化向导。容器启动时自动执行迁移。

关键环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `KINGBASE_PASSWORD` | `Kingbase123` | KingbaseES 密码；同时写入镜像入口的 `PASSWORD` 与客户端工具的 `KINGBASE_PASSWORD` |
| `KINGBASE_IMAGE` | `kingbase_v009r001c010b0004_single_x86:v1` | 你自行 `docker load` 的 KingbaseES 镜像名 |
| `WEB_PORT` | `5000` | 应用对外端口 |
| `SECRET_KEY` | `changeme` | 应用密钥，**生产务必修改** |
| `GS_DB`/目标库 | `zhycms`（编排内固定） | `db-init` 首次启动自动创建；如需修改请编辑 compose 文件 |

> 编排默认端口 `54321`、管理账号 `system`、`DB_MODE=pg`。应用通过
> `kingbase+psycopg2://system:${KINGBASE_PASSWORD}@db-kingbase:54321/zhycms` 连接；
> 客户端工具经 `ZHYCMS_KINGBASE_BIN=/opt/kingbase/bin` 与 `LD_LIBRARY_PATH=/opt/kingbase/lib`
> 挂载调用，密码通过 `KINGBASE_PASSWORD` 环境变量注入。

## 三、拓扑 B：应用裸机 + 独立 KingbaseES

适用于数据库由 DBA 统一维护的场景。应用通过 TCP 连接 KingbaseES（已验证）。

### 1. 创建应用数据库

在 KingbaseES 节点上以管理账号执行（注意 KingbaseES 的 `CREATE DATABASE` / `DROP DATABASE`
不能放在同一事务块内，建议每条语句单独执行）：

```sql
CREATE DATABASE zhycms ENCODING 'UTF8';
```

> 默认管理账号为 `system`、默认库为 `test`/`kingbase`/`security`。生产环境建议为应用
> 单独建库；权限配置请遵循你方 DBA 规范。

### 2. 允许远程 TCP 与认证

按 KingbaseES 官方文档配置 `listen_addresses` 与 `pg_hba.conf`（KingbaseES V9 pg 模式
沿用 PostgreSQL 风格的 HBA 配置），放行应用所在网段后重载。

### 3. 启动应用

```bash
export ZHYCMS_DB_URI='kingbase+psycopg2://system:你的密码@10.0.0.21:54321/zhycms'
export ZHYCMS_ENV=production
export ZHYCMS_SECRET_KEY='<随机长字符串>'
python run.py
```

也可在初始化向导的数据库类型中选择 **KingbaseES（信创推荐）**，端口默认 `54321`、
账号 `system`，保存后会写入 `instance/db_config.json`。

Unix socket 形式同样支持，host 以 `/` 开头即可：

```text
kingbase+psycopg2://system:password@/var/lib/kingbase/run?host=/var/lib/kingbase/run&port=54321&dbname=zhycms
```

## 四、驱动与客户端工具说明

### 1. Python 驱动（连接与迁移）

KingbaseES 为 PG 线协议兼容，连接与迁移**直接使用标准 PyPI `psycopg2-binary`**，
与 PostgreSQL 共用同一驱动；默认镜像 `pollybird/zhycms:latest` 已内置，无需安装
专用驱动，也无需设置 `LD_LIBRARY_PATH` 即可连通。

> 本项目的内置轻量方言（`app/utils/dialects/kingbase.py`）仅用于让 SQLAlchemy /
> Alembic 正确识别 KingbaseES 的版本串——因为 KingbaseES 的 `select version()` 返回
> `KingbaseES V009R001C010`，会被标准 PostgreSQL 方言的版本解析拒绝。方言内部把
> `SHOW server_version`（`12.1`）解析为 `(12, 1)`，其余行为复用 PostgreSQL 方言。

### 2. 客户端工具（备份与恢复）

应用内「备份与恢复」功能需要 KingbaseES 的客户端工具 `sys_dump`（备份）与
`ksql`（恢复）。应用内备份产物为纯 SQL（plain 格式），故恢复只用 `ksql -f`，
**不依赖 `sys_restore`**（`sys_restore` 仅在你手工恢复 custom 格式备份时才需要）。
这些工具**不随 Python 驱动提供**，需要你在运行应用的机器上自行安装（或在容器中
挂载，见拓扑 A）。

工具查找优先级：

1. `ZHYCMS_DB_DUMP_BIN_DIR`（或 `DB_DUMP_BIN_DIR`）目录；
2. `ZHYCMS_KINGBASE_BIN` 目录（也兼容 `KINGBASE_BIN`）；
3. `ZHYCMS_DB_DUMP_BIN` 显式文件路径（仅备份工具 `sys_dump`）；
4. 系统 `PATH`。

示例（裸机）：

```bash
export ZHYCMS_KINGBASE_BIN=/opt/Kingbase/ES/V9/ClientTools/bin
export LD_LIBRARY_PATH=/opt/Kingbase/ES/V9/ClientTools/lib
```

> **`LD_LIBRARY_PATH` 必须指向 KingbaseES 客户端的 `lib` 目录**（含 `libkci.so` 等
> 动态库）。与 openGauss 不同，应用不会自动为 KingbaseES 注入 `LD_LIBRARY_PATH`，
> 请在启动应用前自行设置；未设置时连接与迁移不受影响，但「备份/恢复」会因找不到
> 动态库而失败。拓扑 A 的 compose 已为应用容器配置好 `LD_LIBRARY_PATH=/opt/kingbase/lib`。

## 五、运行验证

```bash
curl -s http://127.0.0.1:5000/healthz?detail=1
```

预期包含：

```json
{"status": "ok", "database": "ok", "db_dialect": "kingbase"}
```

后台页脚会显示 KingbaseES，初始化向导中的数据库类型也会保留 KingbaseES。

## 六、备份与恢复

KingbaseES 的备份工具与 PostgreSQL 不通用，应用已按方言区分：

- 导出：`sys_dump`（stdout 为纯 SQL，**无进度日志污染**，直接管道 gzip）；
- 恢复：`ksql -w -d <db> -f <sql>`；
- **密码通过 `KINGBASE_PASSWORD` 环境变量注入**——KingbaseES 的 `ksql` / `sys_dump` /
  `sys_restore` **不识别 `PGPASSWORD`**（v3.3.1 实测），因此应用只设置
  `KINGBASE_PASSWORD`，密码不会出现在命令行参数中。

> 裸机手工备份时也请遵循同样约定，例如：
> ```bash
> export KINGBASE_PASSWORD='你的密码'
> export LD_LIBRARY_PATH=/opt/Kingbase/ES/V9/ClientTools/lib
> /opt/Kingbase/ES/V9/ClientTools/bin/sys_dump -h 127.0.0.1 -p 54321 -U system -d zhycms | gzip > zhycms.sql.gz
> ```

后台「备份与恢复」生成的备份文件名为 `zhycms_kingbase_<时间戳>.sql.gz`，gzip 内
首部为 `-- Kingbase database dump`，可用 `ksql` 或 `sys_restore` 还原。

## 七、故障速查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `AssertionError` / 版本解析失败（用 `postgresql+psycopg2://` 时） | 标准 PG 方言无法解析 `KingbaseES V009...` 版本串 | 改用 `kingbase+psycopg2://` URI 或向导选 KingbaseES |
| `KeyError: 'kingbase'`（迁移） | 方言未注册 | 升级到 v3.3.1；应用启动时会自动注册 |
| `password authentication failed` | 未设置 `KINGBASE_PASSWORD` 或密码错误 | 确认 `KINGBASE_PASSWORD` 已注入；ksql/sys_dump 不读 `PGPASSWORD` |
| `ksql: error while loading shared libraries: libkci.so` | 缺少 KingbaseES 客户端库路径 | 设置 `LD_LIBRARY_PATH` 指向客户端 `lib` 目录 |
| `no pg_hba.conf entry for host` | 未放行客户端网段 | 在 KingbaseES HBA 配置增加来源网段后重载 |
| `could not connect ... Connection refused` | 未监听外部地址 / 防火墙 / 端口错 | 确认端口为 `54321`，`listen_addresses` 放行，防火墙开放 |
| `command not found: sys_dump` / `ksql` | 客户端工具未安装或路径未配置 | 设置 `ZHYCMS_KINGBASE_BIN` 指向客户端 `bin` 目录 |
| 健康检查始终 `database=error` | 连接串账号/库名/端口错误 | 用 `ksql -h <host> -p 54321 -U system -d zhycms -w` 手工验证 |
| `CREATE DATABASE cannot run inside a transaction block` | 多语句 `-c` 被包进事务 | 每条 `CREATE/DROP DATABASE` 单独一个 `ksql -c` 调用 |

## 八、限制说明

- **兼容模式**：仅支持 KingbaseES 的 **pg 兼容模式**（`DB_MODE=pg`）；`oracle` /
  `mysql` / `sqlserver` 兼容模式不在支持范围内。
- **架构**：x86_64 与 aarch64（鲲鹏）双架构均已端到端实测通过；aarch64 在华为云鲲鹏 EulerOS 3.0 上 55 项全绿，详见 [docs/KINGBASE_ARM_TEST_REPORT.md](KINGBASE_ARM_TEST_REPORT.md)。
- **默认端口与账号**：默认端口 `54321`、默认管理账号 `system`。
- **驱动**：连接与迁移复用标准 `psycopg2-binary`，无需专用驱动；但备份/恢复所需的
  `ksql` / `sys_dump` 客户端工具需用户自行安装并配置 `ZHYCMS_KINGBASE_BIN` 与
  `LD_LIBRARY_PATH`。
- **高可用**：应用只接受单个 `ZHYCMS_DB_URI`，主备切换、读写分离由数据库侧或代理层负责。
- **授权**：KingbaseES 为商业软件，镜像与授权文件请自行从
  <https://www.kingbase.com.cn/download.html> 获取；本项目不分发其二进制或许可证。
