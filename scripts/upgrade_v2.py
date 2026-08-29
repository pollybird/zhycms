"""zhycms v1.1 → v2.0 升级迁移脚本（幂等，可重复执行）。

用法：
    # 使用 instance/db_config.json 中配置的正式库
    .venv/bin/python scripts/upgrade_v2.py

    # 或显式指定数据库 URI
    ZHOCMS_DB_URI='mysql+pymysql://user:pass@127.0.0.1:3306/zhycms?charset=utf8mb4' \
        .venv/bin/python scripts/upgrade_v2.py

做了什么：
  1. db.create_all() 创建 9 张新表（RBAC/审计/版本/备份/上传索引）
  2. 为旧表补齐 v2.0 新增列（users / articles / login_logs，逐列检查，存在即跳过）
  3. 按 is_enabled 回填 articles.status（v1.1 的启用开关 → v2.0 工作流状态）
  4. 为 articles.status 建索引
  5. 初始化 RBAC 预设角色与权限点（与启动逻辑一致，幂等）

不会做什么：
  - 不修改/删除任何既有数据，不改动 users.is_super（见 UPGRADE.md 的审查说明）
  - 不写入任何新的 Setting 行（新配置项由 Setting.get 自动回退 DEFAULTS）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from sqlalchemy import text, inspect

# v2.0 相对 v1.1 的新增表（由 create_all 创建）
NEW_TABLES = [
    'roles', 'permissions', 'role_permissions', 'user_roles',
    'user_column_permissions', 'audit_logs', 'article_versions',
    'backup_records', 'uploaded_files',
]

# v2.0 相对 v1.1 的旧表新增列（必须逐列 ALTER，create_all 不会给已有表加列）
# 列类型同时兼容 SQLite / MySQL / PostgreSQL
ADD_COLUMNS = {
    'users': [
        ('is_active_flag',   'BOOLEAN NOT NULL DEFAULT 1'),
        ('login_fail_count', 'INTEGER NOT NULL DEFAULT 0'),
        ('locked_until',     'DATETIME NULL'),
        ('last_login_city',  'VARCHAR(64) NULL'),
    ],
    'articles': [
        ('status',        "VARCHAR(16) NOT NULL DEFAULT 'published'"),
        ('reject_reason', 'VARCHAR(500) NULL'),
        ('reviewed_by',   'INTEGER NULL'),
        ('reviewed_at',   'DATETIME NULL'),
        ('created_by',    'INTEGER NULL'),
        ('updated_by',    'INTEGER NULL'),
    ],
    'login_logs': [
        ('user_id', 'INTEGER NULL'),
        ('city',    'VARCHAR(64) NULL'),
    ],
}

STATUS_INDEX = ('articles', 'status', 'ix_articles_status')


def get_columns(table):
    insp = inspect(db.engine)
    return {c['name'] for c in insp.get_columns(table)}


def get_indexes(table):
    insp = inspect(db.engine)
    return {i['name'] for i in insp.get_indexes(table)}


def main():
    app = create_app()
    with app.app_context():
        ok = fail = 0
        # 统一使用 db.session.execute + db.session.commit，
        # 避免在 session.connection() 上混用裸连接事务导致 session 状态错乱。

        # ---------- 1. 建新表（create_app 启动时已 create_all，此处幂等兜底） ----------
        existing = set(inspect(db.engine).get_table_names())
        for t in NEW_TABLES:
            if t in existing:
                print(f'  [skip] 表 {t} 已存在')
                ok += 1
            else:
                print(f'  [create] 表 {t}')
                ok += 1
        db.create_all()
        db.session.commit()

        # ---------- 2. 旧表补列 ----------
        for table, cols in ADD_COLUMNS.items():
            have = get_columns(table)
            for name, ddl in cols:
                if name in have:
                    print(f'  [skip] {table}.{name} 已存在')
                    ok += 1
                    continue
                try:
                    db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
                    db.session.commit()
                    print(f'  [alter] {table} ADD COLUMN {name} {ddl}')
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    db.session.rollback()
                    print(f'  [FAIL] {table}.{name}: {e}')
                    fail += 1

        # ---------- 3. 回填 articles.status（v1.1 is_enabled → v2.0 工作流状态） ----------
        # 关键：ALTER ADD COLUMN ... NOT NULL DEFAULT 'published' 会立即把所有旧行填成
        # 'published'，导致 is_enabled=0 的隐藏文章被错误公开。因此数据回填不能依赖
        # "status IS NULL" 条件，必须在首次迁移时全量按 is_enabled 重写一次；
        # 并用 schema_migrations 版本记录保证只做一次，重跑（幂等）不会覆盖运行期数据。
        db.session.execute(text(
            'CREATE TABLE IF NOT EXISTS schema_migrations ('
            'version VARCHAR(32) PRIMARY KEY, applied_at DATETIME)'))
        db.session.commit()
        migrated = db.session.execute(text(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 'v2.0_articles_status'")).scalar()
        if migrated:
            print('  [skip] articles.status 已回填过（schema_migrations 有 v2.0 记录），不覆盖运行期数据')
        else:
            db.session.execute(text(
                "UPDATE articles SET status = CASE WHEN is_enabled = 1 "
                "THEN 'published' ELSE 'draft' END"))
            db.session.execute(text(
                "INSERT INTO schema_migrations (version, applied_at) "
                "VALUES ('v2.0_articles_status', CURRENT_TIMESTAMP)"))
            db.session.commit()
            print('  [data] articles.status 全量回填：is_enabled=1 → published，is_enabled=0 → draft')

        # ---------- 4. status 索引 ----------
        table, col, idx = STATUS_INDEX
        if idx in get_indexes(table):
            print(f'  [skip] 索引 {idx} 已存在')
        else:
            try:
                db.session.execute(text(f'CREATE INDEX {idx} ON {table}({col})'))
                db.session.commit()
                print(f'  [index] CREATE INDEX {idx} ON {table}({col})')
            except Exception as e:  # noqa: BLE001
                db.session.rollback()
                print(f'  [FAIL] 索引 {idx}: {e}')
                fail += 1

        # ---------- 5. RBAC 预设角色与权限（与启动逻辑一致，幂等） ----------
        from app.models.rbac import Permission, Role
        Permission.ensure_presets()
        Role.ensure_presets()
        db.session.commit()
        print('  [rbac] 预设权限点与角色已初始化（超级管理员/内容审核员/内容编辑/只读查看员）')

        # ---------- 6. 自检 ----------
        print('\n========== 自检 ==========')
        have = get_columns('users')
        missing = [c for c, _ in ADD_COLUMNS['users'] if c not in have]
        print(f'users 新列: {"全部就绪" if not missing else "缺失 " + str(missing)}')
        have = get_columns('articles')
        missing = [c for c, _ in ADD_COLUMNS['articles'] if c not in have]
        print(f'articles 新列: {"全部就绪" if not missing else "缺失 " + str(missing)}')
        have = get_columns('login_logs')
        missing = [c for c, _ in ADD_COLUMNS['login_logs'] if c not in have]
        print(f'login_logs 新列: {"全部就绪" if not missing else "缺失 " + str(missing)}')
        tables = set(inspect(db.engine).get_table_names())
        missing = [t for t in NEW_TABLES if t not in tables]
        print(f'新表: {"全部就绪" if not missing else "缺失 " + str(missing)}')
        dist = db.session.execute(text(
            "SELECT status, COUNT(*) FROM articles GROUP BY status")).fetchall()
        print(f'articles.status 分布: {dict(dist)}')
        empty = db.session.execute(text(
            "SELECT COUNT(*) FROM articles WHERE status IS NULL OR status = ''")).scalar()
        print(f'未回填(仍空)的文章数: {empty}')
        roles = db.session.execute(text('SELECT COUNT(*) FROM roles')).scalar()
        perms = db.session.execute(text('SELECT COUNT(*) FROM permissions')).scalar()
        print(f'RBAC: 角色 {roles} 个, 权限点 {perms} 个')
        super_cnt = db.session.execute(
            text('SELECT COUNT(*) FROM users WHERE is_super = 1 AND is_deleted = 0')).scalar()
        print(f'is_super=1 的用户数: {super_cnt}（v1.1 默认全为超管，请按需在后台「用户列表」收紧，见 UPGRADE.md）')

        print(f'\n迁移完成：{ok} 项跳过/成功，{fail} 项失败')
        sys.exit(0 if fail == 0 else 1)


if __name__ == '__main__':
    main()
