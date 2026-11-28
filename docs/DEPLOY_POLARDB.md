# PolarDB for PostgreSQL 部署指南（ZhyCMS v3.3.3）

本文说明如何让 ZhyCMS 运行在 PolarDB for PostgreSQL 15 上。应用侧通过内置方言
支持 `polardb_pg+psycopg2://`，业务代码与模型无需改动。

> **许可说明**：PolarDB for PostgreSQL 源码遵循 Apache License 2.0，官方提供可自由
> 拉取与分发的 Docker 镜像。本仓库的 `docker-compose.polardb.yml` 直接引用官方镜像
> `polardb/polardb_pg_binary:15`（Docker Hub），也可使用阿里云 ACR 镜像
> `registry.cn-hangzhou.aliyuncs.com/polardb_pg/polardb_pg_binary:15`。

> **范围**：本文仅覆盖 **PolarDB for PostgreSQL**（PG 协议兼容）。PolarDB-X 为 MySQL
> 协议，不在本适配范围内；云上 PolarDB 集群版可使用其连接地址，但集群管理接口未实测。

## 一、验证状态

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| PolarDB for PostgreSQL 15（x86_64） | 已验证 | 官方镜像 `polardb/polardb_pg_binary:15`，实测版本 `15.20.5.0`，单机文件系统部署 |
| PolarDB for PostgreSQL 15（aarch64/鲲鹏） | CI 覆盖 | 官方镜像提供 `linux/arm64`；由 `compat.yml` 的 aarch64 job 验证，本地未实测 |
| 迁移至 `0020` | 已验证 | 全新库直接 stamp `0020`，`public` schema 表数 ≥ 40 |
| 初始化向导 / 业务读写 | 已验证 | 创建管理员、中文/布尔/时间回读 |
| 备份与恢复 | 已验证 | 应用内 `pg_dump` 导出、`psql` 导入；同主版本客户端 |
| Docker Compose 编排 | 已验证 | `docker-compose.polardb.yml` 完成初始化、迁移与向导 |
| 其它主版本（11 / 17） | 未验证 | 镜像存在，但客户端与 DDL 兼容性未做端到端验证 |
| 云上 PolarDB 集群版 / PolarDB-X | 不适用 | 集群与 MySQL 协议不在本适配范围 |

## 二、拓扑 A：Docker Compose（推荐）

仓库根目录的 `docker-compose.polardb.yml` 会同时启动：

- `app`：`pollybird/zhycms:polardb`（内置 `postgresql-client`，供 `pg_dump` / `psql` 备份恢复）；
- `db-polardb`：`polardb/polardb_pg_binary:15`（官方二进制镜像）；
- `openamdc`：默认信创缓存后端（Redis 协议兼容），随编排自动启动。

```bash
cp docker/.env.example .env
# 至少修改 SECRET_KEY 与 POLARDB_PASSWORD
docker compose -f docker-compose.polardb.yml up -d --build

# 默认已包含 openAMDC 缓存（随编排自动启动）
docker compose -f docker-compose.polardb.yml up -d --build

# 可选搜索
docker compose -f docker-compose.polardb.yml --profile search up -d
# 如需改用 Redis：追加 --profile redis 并设置 REDIS_URL=redis://redis:6379/0
```

访问 `http://localhost:5000` 完成初始化向导。容器启动时会执行数据库初始化与迁移。

关键环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `POLARDB_PASSWORD` | `Zhycms-2026pdb` | 应用账号与 `postgres` 超级用户密码 |
| `POLARDB_IMAGE` | `polardb/polardb_pg_binary:15` | 数据库镜像；生产建议固定精确标签（如 `15.20.5.0`） |
| `POLARDB_HOST_PORT` | `5432` | 宿主机映射端口；与已有 PostgreSQL 同机部署时改为 5433 等 |
| `SECRET_KEY` | `changeme` | 应用会话密钥，必须修改 |

初始化脚本 `docker/polardb/init.sh` 会在首次启动时：

1. 修正数据卷 `/var/polardb` 属主；
2. 以 `postgres` 用户执行 `initdb -k -A trust`；
3. 设置 `listen_addresses='*'`，并追加 `host all all all scram-sha-256`；
4. 创建应用账号 `zhycms` 与数据库 `zhycms`（owner 为 `zhycms`）；
5. 启动数据库并跟随日志；容器停止时 `pg_ctl -m fast stop` 优雅关闭。

> 该镜像要求 `--privileged` 与 `SYS_PTRACE`，建议宿主机内存 4GB 以上、共享内存
> 512MB 以上（编排已设置 `shm_size: 512m`）。

## 三、拓扑 B：应用裸机 + 独立 PolarDB-PG

适用于数据库由 DBA 统一维护的场景。

### 1. 初始化实例

按官方文档在数据目录初始化并启动：

```bash
mkdir -p /data/polardb
/u01/polardb_pg/bin/initdb -k -A trust -D /data/polardb
# postgresql.conf 中按需设置 listen_addresses / port
/u01/polardb_pg/bin/pg_ctl -D /data/polardb -l /data/polardb/server.log -w start
```

### 2. 创建应用账号与数据库

```sql
ALTER ROLE postgres PASSWORD '<强密码>';
CREATE ROLE zhycms LOGIN PASSWORD '<强密码>';
CREATE DATABASE zhycms OWNER zhycms;
```

> PostgreSQL 15 起 `public` schema 归数据库 owner 所有；应用账号必须是库 owner，
> 否则首次建表会报权限不足。

### 3. 允许应用连接

`postgresql.conf`：

```conf
listen_addresses = '*'
port = 5432
```

`pg_hba.conf` 追加来源网段（按实际网络收敛，勿长期放开 `0.0.0.0/0`）：

```conf
host all all 192.168.1.0/24 scram-sha-256
```

修改后执行 `pg_ctl reload -D /data/polardb`。

### 4. 启动应用

```bash
export ZHYCMS_DB_URI='polardb_pg+psycopg2://zhycms:<密码>@10.0.0.31:5432/zhycms'
export ZHYCMS_ENV=production
export ZHYCMS_SECRET_KEY='<随机长字符串>'
python run.py
```

也可在初始化向导的数据库类型中选择 **PolarDB for PostgreSQL**，端口默认 5432，
保存后会写入 `instance/db_config.json`。

## 四、驱动与依赖

- 应用复用 `psycopg2-binary`（已在 `requirements.txt`），**无需新增 Python 依赖**；
- 本版本无数据库迁移，`alembic_version` 仍为 `0020`；
- `:polardb` 应用镜像通过 `--build-arg INSTALL_PG_CLIENT=1` 安装
  `postgresql-client`（Debian bookworm 默认 15），其他镜像不受影响。

如需手工构建：

```bash
docker build -t pollybird/zhycms:polardb \
  --build-arg INSTALL_PG_CLIENT=1 .
```

## 五、运行验证

```bash
curl -s http://127.0.0.1:5000/healthz?detail=1
```

预期包含：

```json
{"status": "ok", "database": "ok", "db_dialect": "polardb_pg"}
```

后台页脚会显示 PolarDB for PostgreSQL，初始化向导中的数据库类型也会保留该选项。

## 六、备份与恢复

PolarDB-PG 与 PostgreSQL 工具兼容，应用按后端 `polardb_pg` 选择：

- 导出：`pg_dump --no-password`，数据库名作为位置参数；
- 恢复：`psql -f <sql>`；
- 密码通过 `PGPASSWORD` 环境变量注入，不出现在命令行参数中。

工具查找优先级：

1. `ZHYCMS_DB_DUMP_BIN_DIR`（或 `DB_DUMP_BIN_DIR`）目录；
2. `ZHYCMS_POLARDB_BIN` 目录（可指向 `bin` 目录或 `POLARDB_HOME`）；
3. `ZHYCMS_DB_DUMP_BIN` 显式文件路径（仅备份工具）；
4. 系统 `PATH`。

示例：

```bash
export ZHYCMS_POLARDB_BIN=/u01/polardb_pg/bin
```

后台「备份与恢复」生成的文件名为 `zhycms_polardb_pg_<时间戳>.sql.gz`。

> **主版本必须匹配**：`pg_dump` 不能导出比自己更新的服务端。使用 15 的服务端时，
> 请使用 15.x 客户端；若改用 17 镜像，需同步更换客户端或直接使用 PolarDB 自带
> 的 `/u01/polardb_pg/bin` 工具。

## 七、故障速查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'psycopg2'` | 未安装驱动 | `pip install psycopg2-binary` |
| `KeyError: 'polardb_pg'`（迁移） | 方言未注册 | 升级到 v3.3.3；应用启动时会自动注册 Alembic DDL |
| `no pg_hba.conf entry for host` | 未放行客户端网段 | 增加 `host all all <网段> scram-sha-256` 后 reload |
| `password authentication failed` | 账号密码错误或认证方式不符 | 核对账号密码；确认 `pg_hba.conf` 使用 `scram-sha-256` |
| `could not connect ... Connection refused` | 未监听外部地址 / 防火墙 | 设置 `listen_addresses='*'`，放行 5432 |
| `permission denied for schema public` | 应用账号不是库 owner | `CREATE DATABASE zhycms OWNER zhycms` |
| `server version: 15.x; pg_dump version: 14.x` | 客户端主版本低于服务端 | 安装同主版本客户端，或设置 `ZHYCMS_POLARDB_BIN` |
| 容器启动失败 `initdb: cannot be run as root` | 未以 root 启动初始化脚本 | 保持编排中的 `user: root`，由脚本 `su postgres` 执行 |
| `pg_ctl: directory ... is not a database cluster directory` | 数据卷为空或挂载错误 | 确认 `/var/polardb` 挂载到持久化卷并允许写 |

## 八、限制说明

- **版本**：目标为 PolarDB for PostgreSQL 15；11 / 17 镜像存在但未验证。
- **部署形态**：仅支持单机文件系统（localfs）部署；共享存储（PFS）与集群版需按官方文档部署。
- **备份范围**：应用备份为单库逻辑备份，不包含集群级对象与配置；集群版请使用官方备份体系。
- **高可用**：应用只接受单个 `ZHYCMS_DB_URI`，主备切换、读写分离由数据库侧或代理层负责。
- **PolarDB-X**：MySQL 协议，不在本适配范围内。
