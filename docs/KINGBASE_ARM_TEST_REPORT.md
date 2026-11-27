# KingbaseES V9 ARM (aarch64/鲲鹏) 端到端实测报告

**版本**: ZhyCMS v3.3.1 + DDL 编译器修复  
**环境**: 华为云鲲鹏 ARM (aarch64), Huawei Cloud EulerOS 3.0, kernel 6.6.0  
**KingbaseES**: V009R001C010B0004 (ARM aarch64 Docker 镜像提取)  
**日期**: 2026-11-27  

---

## 1. 测试环境

| 项目 | 值 |
|------|-----|
| CPU 架构 | aarch64 (鲲鹏) |
| 操作系统 | Huawei Cloud EulerOS 3.0 |
| Python | 3.12.5 |
| SQLAlchemy | 2.x (psycopg2-binary 驱动) |
| KingbaseES | V009R001C010, server_version=12.1 |
| KingbaseES 端口 | 54321 |
| KingbaseES 用户 | system (trust 认证) |
| 数据库 | zhycms_test (52 张表) |

## 2. 发现的兼容性问题与修复

### 2.1 问题：`db.create_all()` 在 KingbaseES 上 FK 约束失败

**根因**: SQLAlchemy PG 方言对 `Column(unique=True, index=True)` 只创建独立 `CREATE UNIQUE INDEX`，不在 `CREATE TABLE` 中内联 `UNIQUE` 约束。KingbaseES 比 PostgreSQL 更严格，FK 引用列必须有显式 `UNIQUE CONSTRAINT`，仅 `UNIQUE INDEX` 不够。

**影响范围**: ZhyCMS 中 5 个 `unique=True, index=True` 列：
- `Permission.code` — 被 `RolePermission.permission_code` FK 引用（直接导致失败）
- `Role.code`
- `User.username`
- `Site.slug`
- `Site.subdomain`

**修复**: 在 `app/utils/dialects/kingbase.py` 中添加 `KingbaseDDLCompiler`，覆盖 `get_column_specification`，为 `unique=True` 但缺少表级 `UniqueConstraint` 的列补充列级 `UNIQUE` 关键字。

```python
class KingbaseDDLCompiler(PGDDLCompiler):
    def get_column_specification(self, column, **kwargs):
        colspec = super().get_column_specification(column, **kwargs)
        if not column.unique:
            return colspec
        has_table_level_uc = any(
            isinstance(c, schema.UniqueConstraint)
            and len(c.columns) == 1
            and c.columns[0].name == column.name
            for c in column.table.constraints
        )
        if not has_table_level_uc:
            colspec += " UNIQUE"
        return colspec
```

**DDL 行为对比**:

| 列定义 | 修复前 (PG 方言) | 修复后 (KingbaseES 方言) |
|--------|------------------|--------------------------|
| `unique=True` | `UNIQUE (code)` (表级) | `UNIQUE (code)` (表级, 不变) |
| `unique=True, index=True` | 无 UNIQUE 约束, 仅 `CREATE UNIQUE INDEX` | `code VARCHAR(128) NOT NULL UNIQUE` (列级) |
| 无 unique | 无 UNIQUE | 无 UNIQUE (不变) |

### 2.2 方言版本解析（v3.3.1 原有）

`select version()` 返回 `KingbaseES V009R001C010`，标准 PG 方言解析失败。覆盖 `_get_server_version_info` 改用 `SHOW server_version`（返回 `12.1` → `(12, 1)`）。

## 3. 测试结果

### 3.1 单元测试 (`tests/test_kingbase.py`)

| 修复前 | 修复后 |
|--------|--------|
| 28 passed, **2 failed** | **30 passed**, 0 failed |

失败项 `test_full_migration_and_healthz` 和 `test_backup_produces_kingbase_dump` 均因 `db.create_all()` FK 约束问题失败，修复后全部通过。

### 3.2 端到端集成测试 (25 项)

| 类别 | 项数 | 结果 |
|------|------|------|
| 方言注册与版本解析 | 3 | 全部通过 |
| create_app + db.create_all | 4 | 全部通过 |
| CRUD 操作 (User/Role/Permission/RolePermission) | 8 | 全部通过 |
| 健康检查 (version/server_version/pool) | 3 | 全部通过 |
| 备份恢复 (sys_dump) | 4 | 全部通过 |
| UNIQUE 约束修复验证 | 3 | 全部通过 |
| Alembic 迁移验证 | 1 | 全部通过 |
| **总计** | **25** | **25 passed, 0 failed** |

### 3.3 关键验证细节

- **db.create_all()**: 51 张模型表全部创建成功，Alembic 迁移 0001→0020 全部执行
- **permissions.code UNIQUE CONSTRAINT**: 约束名 `permissions_code_key`，FK `role_permissions_permission_code_fkey` 引用成功
- **sys_dump 备份**: 206,573 bytes，rc=0
- **Alembic 迁移**: 使用 `KingbaseImpl`（非 SQLiteImpl），当前版本 `0020`
- **连接池**: pool_size=10, max_overflow=20, pool_recycle=1800

## 4. 代码变更

| 文件 | 变更 |
|------|------|
| `app/utils/dialects/kingbase.py` | +40 行：新增 `KingbaseDDLCompiler` 类，`KingbaseDialect.ddl_compiler` 指向它 |

## 5. 结论

KingbaseES V9 (V009R001C010) 在华为云鲲鹏 ARM (aarch64) 上经 ZhyCMS v3.3.1 + DDL 编译器修复后，端到端全部通过（30 单元测试 + 25 集成测试 = 55 项全绿）。修复不影响 PostgreSQL 和其他数据库后端的行为，仅在 KingbaseES 方言层面补充 UNIQUE 约束。
