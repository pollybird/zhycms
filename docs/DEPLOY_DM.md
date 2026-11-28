# 达梦 DM8 部署指南（ZhyCMS v3.3.2）

> **授权声明（请务必先阅读）**：本项目**仅实现对达梦 DM8 的适配支持**。
> 达梦 DM8 是商业软件，其安装包、客户端工具与授权文件（license）**均需用户
> 自行到官方下载并获取官方授权**，下载地址：<https://www.dameng.com/>。
> 本仓库**不提供、不分发** DM8 的镜像、二进制或许可证；使用前请确认已获得
> 合法授权。本文档中的参数、工具路径与命令均以达梦 DM8 官方发行版为例，请以你
> 实际获取的官方版本为准。

本文说明如何让 ZhyCMS 运行在达梦 DM8 上。适配范围包括：连接、建表与 Alembic
迁移、初始化向导、业务读写、`/healthz` 健康检查、`dexp` / `dimp` 备份恢复。

## 一、验证状态

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 达梦 DM8（x86_64） | 已验证 | 本地环境完成端到端验证（实例与授权由开发/运维人员自备） |
| 迁移至 `0020` | 已验证 | `db.create_all()` 与启动引导中的 Alembic 增量升级均成功 |
| 初始化向导 / 建表 | 已验证 | 向导切换后建表 52 张，管理员与默认设置写入成功 |
| 整数主键自增 | 已验证 | 插入不带主键的记录后由 `IDENTITY(1, 1)` 生成 |
| 备份与恢复 | 已验证 | `dexp` 导出二进制 DMP（gzip 为 `.dmp.gz`），`dimp` 恢复 |
| 健康检查标识 | 已验证 | `/healthz?detail=1` 返回 `db_dialect=dm` |
| aarch64 | 未验证 | `dmpython` 提供 aarch64 wheel，但本项目未在 ARM 上实测 |
| 集群 / 读写分离 | 不适用 | 本项目只使用单个数据库连接串，HA 属部署侧能力 |

## 二、安装 Python 驱动

```bash
pip install -r requirements-dm.txt
```

该文件只包含两个 PyPI 包：

- `dmpython`：达梦官方 DB-API 驱动（提供 x86_64 / aarch64 manylinux wheel）；
- `dmSQLAlchemy`：SQLAlchemy 2.x 方言包。

安装后无需额外配置 `LD_LIBRARY_PATH` 即可连接数据库。**备份/恢复**另需达梦
客户端工具 `dexp` / `dimp`（随官方客户端安装）。

## 三、准备 DM8 实例与 Schema

1. 按达梦官方文档安装并初始化 DM8 实例，记下监听端口（默认 `5236`）。
2. 建议使用 UTF-8 字符集与大小写不敏感配置，例如 `dminit` 初始化参数：
   `PAGE_SIZE=16`、`CHARSET=1`（UTF-8）、`LENGTH_IN_CHAR=1`、`CASE_SENSITIVE=0`。
   （具体参数以官方安装程序为准，已有实例无需为此重建。）
3. 创建应用账号与 Schema（DM8 中 Schema 与用户同名）：

```sql
CREATE USER "ZHYCMS" IDENTIFIED BY "请替换为强密码";
GRANT DBA TO "ZHYCMS";
```

> **Schema 语义**：ZhyCMS 向导中的「数据库名」在 DM8 中对应 **Schema**，
> URI 的 database 段同样按 Schema 解析，请勿填写实例名。建议 Schema 与用户
> 同名，并保持大写（DM8 默认标识符大写）。

## 四、配置应用

### 方式 A：环境变量（推荐容器 / 自动化部署）

```bash
export ZHYCMS_DB_URI='dm+dmPython://ZHYCMS:密码@127.0.0.1:5236/ZHYCMS'
python run.py
```

### 方式 B：初始化向导

首次启动进入 `/admin/setup`，数据库类型选择 **达梦 DM8**：

| 字段 | 填写内容 |
| --- | --- |
| 主机 | DM8 实例地址，如 `127.0.0.1` |
| 端口 | 默认 `5236`，留空自动回填 |
| 数据库名 | Schema 名，如 `ZHYCMS` |
| 用户名 | 应用账号，如 `ZHYCMS` |
| 密码 | 上述账号密码 |

保存后应用会热切换引擎并自动建表（表结构即当前版本）；`alembic_version` 记录会在
应用**下次启动**时由启动引导补齐（stamp `0001` 后增量升级至 `0020`，与其它数据库
的向导流程一致）。启动完成后访问 `/healthz?detail=1`，应返回 `db_dialect=dm`、
`database=ok`。

## 五、备份与恢复

ZhyCMS 后台「备份管理」对 DM8 的映射：

- **备份**：`dexp USERID=用户/密码@主机:5236 FILE=<临时>.dmp LOG=<临时>.log SCHEMAS=<Schema>`，
  成功后 gzip 为 `zhycms_dm_<时间戳>.dmp.gz`；
- **恢复**：解压 `.dmp.gz` 后执行
  `dimp USERID=用户/密码@主机:5236 FILE=<临时>.dmp LOG=<临时>.log SCHEMAS=<Schema>`。

> **恢复语义**：与 PostgreSQL 备份一致，DM8 的 `dimp` 恢复要求目标 Schema 为空
> （或备份与目标对象不冲突）。恢复到仍有业务表的 Schema 会因对象已存在而失败，
> 请先清空目标 Schema 再恢复。

工具路径查找顺序：

1. `DB_DUMP_BIN_DIR`（应用配置，或环境变量 `ZHYCMS_DB_DUMP_BIN_DIR`）；
2. `ZHYCMS_DM_BIN`（可指向达梦客户端 `bin` 目录，也可指向 `DM_HOME`，会自动补 `bin/`）；
3. `DM_HOME/bin`；
4. 系统 `PATH`。

```bash
# 示例：客户端安装在 /opt/dmdbms
export ZHYCMS_DM_BIN=/opt/dmdbms/bin
```

若执行备份/恢复时提示找不到 `libdmdpi.so` 等动态库，需要把达梦客户端 `bin`
目录加入**运行应用进程**的 `LD_LIBRARY_PATH`（官方安装脚本通常会设置；解压或
复制式安装需手动设置）：

```bash
export LD_LIBRARY_PATH=/opt/dmdbms/bin:$LD_LIBRARY_PATH
```

> **安全提示**：达梦工具不支持 `PGPASSWORD` 一类的环境变量密码；应用以非交互方式
> 调用，密码通过 `USERID=用户/密码@主机:端口` 传入，会短暂出现在进程参数中。建议为备份单独
> 创建最小权限账号，并限制主机上的进程可见性。由于 `USERID` 以 `/`、`@` 分隔，
> 备份账号密码请避免包含这两个字符。

## 六、限制与注意

- **整数主键自增**：`dmSQLAlchemy` 只识别 `autoincrement=True`，本项目已在方言层
  为 `Column(Integer, primary_key=True)` 补充 `IDENTITY(1, 1)`；复合主键不会自动
  自增，如新建模型请显式指定。
- **大小写**：DM8 默认标识符大写；若实例初始化时开启大小写敏感，请保持 Schema
  与账号命名一致，避免迁移与查询找不到对象。
- **工具缺失**：未安装 `dexp` / `dimp` 时，连接、迁移与业务读写不受影响，仅后台
  备份/恢复不可用，页面会给出中文提示。
- **aarch64**：驱动 wheel 提供 aarch64 版本，但本项目暂未在 ARM 环境完成实测。
- **回退**：把 `ZHYCMS_DB_URI` 改回原数据库并重启即可，无结构变更。
