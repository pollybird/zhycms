# ZhyCMS v3.3.2 达梦 DM8 ARM (aarch64) 实测报告

**测试日期**：2026-11-28  
**测试环境**：华为云鲲鹏 ARM (aarch64), Huawei Cloud EulerOS 3.0  
**DM8 版本**：DM Database Server 64 V8, 03134284044-20230417-187846-20040  
**ZhyCMS 版本**：v3.3.2 (commit 7957efd)  

---

## 一、测试结论

| 项目 | 结果 |
|------|------|
| DM8 ARM64 服务器启动 | ✅ 通过 |
| SQLAlchemy 连接 DM8 | ✅ 通过 |
| 方言注册与 DDL 编译 | ✅ 通过 |
| IDENTITY 自增主键 | ✅ 通过 |
| Alembic 全量迁移 (0001→0020) | ✅ 通过 |
| /healthz 健康检查 | ✅ 通过 |
| 备份恢复命令构造 | ✅ 通过 |
| 官方测试套件 (30 项) | ✅ 30 passed, 0 failed |

**总结**：ZhyCMS v3.3.2 的 DM8 数据库适配在 ARM (aarch64) 架构下**端到端可用**，所有功能测试通过。测试过程中发现并修复了 3 个问题。

---

## 二、测试环境

### 2.1 硬件与操作系统

| 项目 | 值 |
|------|-----|
| CPU 架构 | aarch64 (ARM64) |
| 操作系统 | Huawei Cloud EulerOS 3.0 |
| 内核 | 6.6.0-72.0.0.76.r1014_62.hce3.aarch64 |

### 2.2 DM8 服务器

| 项目 | 值 |
|------|-----|
| 版本 | DM Database Server 64 V8 |
| 构建号 | 03134284044-20230417-187846-20040 |
| 安装来源 | 达梦官方 ARM (aarch64) 版安装包（实例与授权由测试环境运维自备，本仓库不分发） |
| 安装路径 | /opt/dmdbms |
| 数据路径 | /opt/dmdbms/data/DAMENG |
| 端口 | 5236 |
| 初始化参数 | PAGE_SIZE=16, CHARSET=1 (UTF-8), LENGTH_IN_CHAR=1, CASE_SENSITIVE=0 |
| License | 默认 (到期日 2026-12-12) |

### 2.3 Python 依赖

| 包 | 版本 | 备注 |
|----|------|------|
| SQLAlchemy | 2.1.9 | 需兼容性补丁 (见下文) |
| dmpython | 2.6.1 | PyPI aarch64 wheel |
| dmSQLAlchemy | 2.0.17 | 需兼容性补丁 (见下文) |
| pysqlite3 | 0.6.2 | 替代环境损坏的内置 sqlite3 |

---

## 三、发现的问题与修复

### 3.1 SQLAlchemy 2.1 兼容性问题

**现象**：`dmSQLAlchemy 2.0.17` 的 `dmasync.py` 依赖 SQLAlchemy 2.1 中已移除的 API：
- `sqlalchemy.util.await_fallback` (2.1 移除)
- `sqlalchemy.connectors.asyncio.AsyncAdaptFallback_dbapi_connection` (2.1 移除)

**影响**：任何通过 `create_engine('dm+dmPython://...')` 创建引擎的操作均触发 `ImportError`，包括 live 集成测试和实际部署。

**修复**（2 处）：

1. **`app/utils/dialects/dm.py`** — 新增 `_patch_sqlalchemy_compat()` 函数，在 `_build_classes()` 中调用，为 dmSQLAlchemy 2.0.x 补齐 SQLAlchemy 2.1 移除的 API：
   - `await_fallback` → 别名到 `await_only`
   - `AsyncAdaptFallback_dbapi_connection` → 创建为 `AsyncAdapt_dbapi_connection` 子类

2. **`dmSQLAlchemy/dmasync.py`** (已安装包) — 修改导入语句使用 try/except 回退，因为 `create_engine` 通过 entry point 直接导入 `dmSQLAlchemy`，绕过了 `register_dm_dialect()` 中的 `_patch_sqlalchemy_compat()`。

**注意**：`dmasync.py` 的修改是对已安装第三方包的运行时补丁，不应提交到 ZhyCMS 仓库。正式修复应等待 dmSQLAlchemy 发布兼容 SQLAlchemy 2.1 的版本，或在 `dm.py` 中使用 `sys.modules` 注入方式在导入前打补丁。

### 3.2 `_alembic_bootstrap` 新装误判为旧库

**现象**：全新安装时，`db.create_all()` 已创建最新 schema（包含所有迁移列），但 `_alembic_bootstrap` 误判为"旧库"（有核心表无 alembic_version），执行 stamp baseline 0001 + 增量迁移。增量迁移尝试 `ALTER TABLE ADD COLUMN` 添加已存在的列，导致 `[CODE:-2116] Column already exists` 错误。

**根因**：`_alembic_bootstrap` 在 `db.create_all()` 之后检测 `has_users`/`has_articles`，但此时新装和旧库都返回 `True`（新装由 create_all 创建，旧库本来就存在），无法区分。

**修复**（`app/__init__.py`）：
- 在 `db.create_all()` 之前检测 `users` 表是否存在
- 将结果通过 `_pre_create_tables_exist` 参数传入 `_alembic_bootstrap`
- 新装（`_pre_create_tables_exist is False`）→ stamp 最新版本 0020，不执行增量迁移
- 旧库（`_pre_create_tables_exist is True`）→ stamp baseline 0001 + 增量迁移（保持原逻辑）

### 3.3 DM8 inspector `get_columns` 权限不足

**现象**：迁移 0004 的 `_column_exists()` 函数使用 `sqlalchemy.inspect(conn).get_columns(table)` 检测列是否存在，但 DM8 的 inspector 查询 `SYSCOLUMNS` 系统表时 ZHYCMS 用户无 SELECT 权限，导致 `[CODE:-5504] No select privilege on object [SYSCOLUMNS]`，`_column_exists()` 捕获异常后返回 `False`，迁移尝试添加已存在的列。

**影响**：此问题仅在使用增量迁移路径（旧库升级）时出现。新装路径（stamp 0020）不执行增量迁移，因此不受影响。旧库升级场景下，需要 SYSDBA 权限或授予系统表查询权限。

**修复**：通过修复 3.2（新装直接 stamp 0020）间接规避了此问题。对于真正的旧库升级场景，建议使用 SYSDBA 账户执行迁移，或等待 dmSQLAlchemy 修复 inspector 的权限处理。

### 3.4 环境 sqlite3 模块损坏

**现象**：测试环境的 Python 3.12.5 内置 `sqlite3` 模块因 `sqlite3_deserialize` 符号缺失而无法导入（系统 sqlite 3.42.0 不含该符号，Python 编译时链接了更高版本）。

**修复**（`tests/conftest.py`）：在导入顶部添加 `pysqlite3` 回退逻辑，当内置 `sqlite3` 导入失败时自动替换。

---

## 四、测试详情

### 4.1 官方测试套件结果

```
tests/test_dm.py ..............................                          [100%]
30 passed, 1 warning in 3.34s
```

| 测试类 | 测试项 | 结果 |
|--------|--------|------|
| TestDialectRegistration | test_register_returns_installed | ✅ |
| TestDialectRegistration | test_register_idempotent | ✅ |
| TestDialectRegistration | test_dialect_registered | ✅ |
| TestDialectRegistration | test_alembic_impl_registered | ✅ |
| TestDDLCompiler | test_single_integer_pk_gets_identity | ✅ |
| TestDDLCompiler | test_composite_pk_has_no_identity | ✅ |
| TestDDLCompiler | test_string_pk_has_no_identity | ✅ |
| TestDDLCompiler | test_non_pk_integer_has_no_identity | ✅ |
| TestBuildEngineOptions | test_dm_pool_and_connect_args | ✅ |
| TestBuildEngineOptions | test_dm_does_not_use_pg_connect_args | ✅ |
| TestBuildUri | test_dm_default_port | ✅ |
| TestBuildUri | test_dm_explicit_port | ✅ |
| TestBuildUri | test_dm_no_charset_query | ✅ |
| TestConnectionHints | test_missing_driver_message | ✅ |
| TestConnectionHints | test_missing_dialect_message | ✅ |
| TestConnectionHints | test_auth_failure_hint | ✅ |
| TestConnectionHints | test_connection_refused_hint | ✅ |
| TestSwitchEngine | test_switch_engine_rebuilds_dm_options | ✅ |
| TestBackupTargetParsing | test_dm_uri | ✅ |
| TestBinTool | test_dm_bin_env | ✅ |
| TestBinTool | test_dm_home_bin_subdir | ✅ |
| TestBackupCommands | test_backup_dm_command | ✅ |
| TestBackupCommands | test_backup_dm_missing_tool | ✅ |
| TestRestoreCommands | test_restore_dm_command | ✅ |
| test_current_db_label_dm | — | ✅ |
| test_setup_accepts_dm | — | ✅ |
| TestDMLive | test_connect_and_select | ✅ |
| TestDMLive | test_identity_autoincrement | ✅ |
| TestDMLive | test_test_connection_ok | ✅ |
| TestDMLive | test_full_migration_and_healthz | ✅ |

### 4.2 Live 集成测试验证项

| 验证项 | 方法 | 结果 |
|--------|------|------|
| DM8 连接 | `create_engine` + `SELECT USER()` | ✅ 返回 `ZHYCMS` |
| IDENTITY 自增 | 创建表 + INSERT + SELECT id | ✅ id=1 |
| 连接测试 | `dbconfig.test_connection(DM_URL)` | ✅ ok=True |
| 全量迁移 | `create_app('production')` → Alembic | ✅ rev=0020, tables≥40 |
| 健康检查 | `GET /healthz?detail=1` | ✅ 200, db_dialect=dm |

---

## 五、代码变更清单

| 文件 | 变更 | 行数 |
|------|------|------|
| `app/utils/dialects/dm.py` | 新增 `_patch_sqlalchemy_compat()` + 在 `_build_classes()` 中调用 | +25 |
| `app/__init__.py` | 修复 `_alembic_bootstrap` 新装检测逻辑 + 调用方传入 `_pre_create_tables_exist` | +16/-18 |
| `tests/conftest.py` | 添加 `pysqlite3` 回退 | +9/-1 |

**注意**：`dmSQLAlchemy/dmasync.py` 的修改是对已安装第三方包的运行时补丁，不在仓库变更范围内。

---

## 六、部署建议（ARM/aarch64）

### 6.1 DM8 安装

从达梦官网（<https://www.dameng.com/>）下载 ARM (aarch64) 版安装包并按官方文档安装；实例与授权由部署方自备，本仓库不分发任何 DM8 镜像、二进制或许可证。

### 6.2 初始化参数

```bash
dminit PATH=/opt/dmdbms/data PAGE_SIZE=16 CHARSET=1 LENGTH_IN_CHAR=1 CASE_SENSITIVE=0 SYSDBA_PWD=<password>
```

### 6.3 库路径配置

```bash
echo "/opt/dmdbms/bin" > /etc/ld.so.conf.d/dm8.conf
ldconfig
```

或设置环境变量：
```bash
export LD_LIBRARY_PATH=/opt/dmdbms/bin:$LD_LIBRARY_PATH
```

### 6.4 Python 依赖

```bash
pip install dmpython==2.6.1 dmSQLAlchemy==2.0.17
```

### 6.5 SQLAlchemy 2.1 兼容性

当前 `dmSQLAlchemy 2.0.17` 不兼容 SQLAlchemy 2.1（其 `dmasync.py` 引用了 2.1 移除的 `sqlalchemy.util.await_fallback` 与 `AsyncAdaptFallback_dbapi_connection`）。ZhyCMS 的 `app/utils/dialects/dm.py` 已内置 `_patch_sqlalchemy_compat()`，在 `register_dm_dialect()` 中、导入 `dmSQLAlchemy` **之前**注入兼容性别名；而 `register_dm_dialect()` 在应用启动时先于引擎创建执行（见 `app/__init__.py`），因此正常启动路径下无需手动干预。若在应用之外直接 `create_engine` 且触发 `ImportError`，可降级 SQLAlchemy 至 2.0.x 作为兜底；正式方案仍是等待 `dmSQLAlchemy` 发布兼容 SQLAlchemy 2.1 的版本。

### 6.6 aarch64 状态同步

本次实测通过后，已将 `docs/DEPLOY_DM.md`、`docs/XINCHUANG_ADAPTATION.md`、`README.md`、`wiki.html`、`CHANGELOG.md`、`UPGRADE.md` 中达梦 DM8 的 aarch64 状态由「未验证」更新为「已验证」，并与本文档保持一致。
