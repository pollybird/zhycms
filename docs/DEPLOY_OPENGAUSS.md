# openGauss 部署指南（ZhyCMS v3.3.0）

本文说明如何让 ZhyCMS 运行在 openGauss 上。应用侧通过内置方言支持
`opengauss+psycopg2://`，业务代码与模型无需改动。

## 一、验证状态

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| openGauss 7.0.0（x86_64） | 已验证 | 实测镜像 `opengauss/opengauss:7.0.0-RC3.B025-openEuler22.03`，`version()` 返回 `openGauss-lite 7.0.0-RC3` |
| 迁移至 `0020` | 已验证 | 52 张表，`MIGRATION_FAILED=None` |
| 初始化向导 / 业务读写 | 已验证 | 创建管理员、文章中文/布尔/时间回读、序列不回退 |
| 备份与恢复 | 已验证 | `gs_dump` 导出，`gsql` 恢复到新库，核心表行数一致 |
| Docker Compose 编排 | 已验证 | `docker-compose.opengauss.yml` 完成迁移与向导 |
| openGauss 官方 SQLAlchemy 方言 | 未验证 | `requirements-opengauss.txt` 为可选增强，默认走内置方言 |
| aarch64 驱动 | 未验证 | 本文驱动地址仅适用于 x86_64；ARM 需自行获取对应预编译包 |
| 哨兵 / 集群 | 不适用 | 本项目只使用单个数据库连接串，HA 属部署侧能力 |

## 二、拓扑 A：Docker Compose（推荐）

仓库根目录的 `docker-compose.opengauss.yml` 会同时启动：

- `app`：`pollybird/zhycms:opengauss`（内置 openGauss 驱动）；
- `db-opengauss`：`pollybird/opengauss:7.0.0`（官方镜像 + `openblas` 运行时依赖）。

```bash
cp docker/.env.example .env
# 至少修改 SECRET_KEY 与 OPENGAUSS_PASSWORD
docker compose -f docker-compose.opengauss.yml up -d --build

# 可选缓存 / 搜索
docker compose -f docker-compose.opengauss.yml --profile openamdc up -d
docker compose -f docker-compose.opengauss.yml --profile search up -d
```

访问 `http://localhost:5000` 完成初始化向导。容器启动时自动执行迁移。

关键环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OPENGAUSS_PASSWORD` | `Zhycms-2026og` | openGauss 密码，同时用于 `GS_PASSWORD` 与连接串 |
| `GS_DB`（编排内固定） | `zhycms` | 初始化数据库名；如需修改请直接编辑 `docker-compose.opengauss.yml` |
| `OPENGAUSS_IMAGE` | `pollybird/opengauss:7.0.0` | 派生数据库镜像 |
| `OPENGAUSS_BASE_IMAGE` | `opengauss/opengauss:7.0.0-RC3.B025-openEuler22.03` | 派生镜像的基座 |

> 密码限制：openGauss 要求大小写字母、数字、特殊字符齐全，且长度至少 8 位。
> 编排文件用 `-` 作特殊字符，避免 `@`、`#`、`%` 破坏数据库 URI；安装器按同一规则生成。

## 三、拓扑 B：应用裸机 + 独立 openGauss

适用于数据库由 DBA 统一维护的场景。应用通过 TCP 连接 openGauss（已验证）。

### 1. 创建应用账号与数据库

在 openGauss 节点上以初始用户执行：

```sql
CREATE USER zhycms WITH PASSWORD 'Zhycms-2026-og';
CREATE DATABASE zhycms OWNER zhycms ENCODING 'UTF8';
GRANT ALL PRIVILEGES ON DATABASE zhycms TO zhycms;
```

> 初始用户为 `gaussdb`。生产环境建议使用独立应用账号，避免直接用初始用户。
> 账号密码同样必须满足大小写、数字、特殊字符规则。

### 2. 允许远程 TCP 与外网认证

`postgresql.conf`：

```conf
listen_addresses = '*'
password_encryption_type = 2   # sha256
```

`pg_hba.conf` 追加来源网段（按实际网络收敛，勿长期放开 `0.0.0.0/0`）：

```conf
host all all 192.168.1.0/24 sha256
```

修改后重载：`gs_ctl reload -D $GAUSSDATA`。

### 3. 启动应用

```bash
export ZHYCMS_DB_URI='opengauss+psycopg2://zhycms:Zhycms-2026-og@10.0.0.21:5432/zhycms'
export ZHYCMS_ENV=production
export ZHYCMS_SECRET_KEY='<随机长字符串>'
python run.py
```

也可在初始化向导的数据库类型中选择 **openGauss（信创推荐）**，端口默认 5432，
保存后会写入 `instance/db_config.json`。

Unix socket 形式同样支持，host 以 `/` 开头即可：

```text
opengauss+psycopg2://zhycms:password@/var/lib/opengauss/run?host=/var/lib/opengauss/run&port=5432&dbname=zhycms
```

## 四、驱动安装

应用默认使用内置轻量方言（`app/utils/dialects/opengauss.py`），但仍需要
**openGauss 官方 psycopg2 驱动**——PyPI 上的 `psycopg2-binary` 不能连接 openGauss。

### 1. 预编译包（x86_64，已验证）

```bash
curl -fL -o /tmp/openGauss-Python.tar.gz \
  https://opengauss.obs.cn-south-1.myhuaweicloud.com/7.0.0/openEuler22.03/x86/openGauss-Python-7.0.0-openEuler22.03-x86_64.tar.gz

mkdir -p /tmp/ogpy && tar -xzf /tmp/openGauss-Python.tar.gz -C /tmp/ogpy
cp -r /tmp/ogpy/psycopg2* /usr/local/lib/python3.12/site-packages/
# 运行期库路径（psycopg2 与 libpq 依赖）
export LD_LIBRARY_PATH=/tmp/ogpy/lib:$LD_LIBRARY_PATH
```

> 已知问题：该驱动包自带旧版 `libssl.so.3` / `libcrypto.so.3`，若加入
> `LD_LIBRARY_PATH` 会覆盖系统 OpenSSL，导致 Python `_ssl` 报
> `OPENSSL_3.3.0 not found`。Docker 构建脚本已在解压后删除这两个库；
> 裸机安装时也应删除 `lib/libssl.so.3`、`lib/libcrypto.so.3`，仅保留 `libpq` 等依赖。

### 2. 可选：官方 SQLAlchemy 方言

```bash
pip install -r requirements-opengauss.txt
```

安装后应用会自动优先使用官方方言，未安装则回退内置方言。该分支在本次
交付中**未实测**，默认部署不需要它。

### 3. Docker 镜像

`:opengauss` 标签在构建阶段完成驱动安装，无需手工操作：

```bash
docker build -t pollybird/zhycms:opengauss \
  --build-arg INSTALL_OPENGAUSS_DRIVER=1 \
  --build-arg OPENGAUSS_PY_URL=https://opengauss.obs.cn-south-1.myhuaweicloud.com/7.0.0/openEuler22.03/x86/openGauss-Python-7.0.0-openEuler22.03-x86_64.tar.gz .
```

默认构建（`INSTALL_OPENGAUSS_DRIVER=0`）不改变现有 `mysql` / `postgresql` / `latest` 镜像。

## 五、运行验证

```bash
curl -s http://127.0.0.1:5000/healthz?detail=1
```

预期包含：

```json
{"status": "ok", "database": "ok", "db_dialect": "opengauss"}
```

后台页脚会显示 openGauss，初始化向导中的数据库类型也会保留 openGauss。

## 六、备份与恢复

openGauss 的备份工具与 PostgreSQL 不通用，应用已按方言区分：

- 导出：`gs_dump`，数据库名作为**位置参数**（不支持 `-d`），密码用 `-W`；
- 恢复：`gsql -d <db> -f <sql> -W <password>`；
- 运行前自动注入 `LD_LIBRARY_PATH`（默认 `/usr/local/opengauss/lib`）。

工具查找优先级：

1. `ZHYCMS_DB_DUMP_BIN_DIR`（或 `DB_DUMP_BIN_DIR`）目录；
2. `OPENGAUSS_BIN` 目录；
3. `ZHYCMS_DB_DUMP_BIN` 显式文件路径（仅备份工具）；
4. 系统 `PATH`。

示例：

```bash
export OPENGAUSS_BIN=/usr/local/opengauss/bin
export ZHYCMS_DB_DUMP_BIN_DIR=/usr/local/opengauss/bin
```

后台「备份与恢复」生成的备份文件名为 `zhycms_opengauss_<时间戳>.sql.gz`。

> `gs_dump` 的进度日志会写入 stdout。应用使用 `-f` 先落临时文件再压缩，
> 避免日志混入 SQL；手工执行时也应遵循同样做法。

## 七、故障速查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'psycopg2'` | 未安装 openGauss 官方驱动 | 按第四节安装预编译包 |
| `psycopg2.OperationalError: invalid connection option` | 使用了 PyPI `psycopg2-binary` | 换成 openGauss 官方 psycopg2 fork |
| `OPENSSL_3.3.0 not found` | 驱动自带旧 OpenSSL 覆盖了系统库 | 删除驱动目录下 `libssl.so.3` / `libcrypto.so.3` |
| `no pg_hba.conf entry for host` | 未放行客户端网段 | 在 `pg_hba.conf` 增加 `host ... sha256` 后 reload |
| `password authentication failed` | 密码不符合规则或加密方式不一致 | 确认密码四类字符齐全；`password_encryption_type=2` |
| `could not connect ... Connection refused` | 未监听外部地址 / 防火墙 | 设置 `listen_addresses='*'`，放行 5432 |
| `KeyError: 'opengauss'`（迁移） | 方言未注册 | 升级到 v3.3.0；应用启动时会自动注册 Alembic DDL |
| `gs_dump: option -d not recognized` | 使用了 PostgreSQL 参数风格 | 使用位置参数库名，或交由应用内置备份 |
| `gs_dump: error while loading shared libraries` | 缺少 openGauss 库路径 | 设置 `LD_LIBRARY_PATH=/usr/local/opengauss/lib` |
| 健康检查始终 `database=error` | 连接串用户名/库名错误 | 用 `gsql -d zhycms -U zhycms -W` 手工验证 |

## 八、限制说明

- **版本**：目标为 openGauss 7.0.0 LTS；本次实测为 7.0.0-RC3（lite）镜像。
- **架构**：仅验证 x86_64；aarch64 需自行准备驱动，未做验证。
- **方言**：内置方言覆盖版本解析与 Alembic DDL 注册，未实现 openGauss 特有语法扩展。
- **高可用**：应用只接受单个 `ZHYCMS_DB_URI`，主备切换、读写分离由数据库侧或代理层负责。
