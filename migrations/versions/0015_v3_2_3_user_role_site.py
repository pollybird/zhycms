"""v3.2.3: 用户角色支持站点维度

变更内容：
1. user_roles 新增 site_id（NULL = 平台级/全局角色，非空 = 只在指定站点生效）；
2. 唯一约束由 (user_id, role_id) 调整为 (user_id, role_id, site_id)。

实现要点：
- 幂等：新装库由 db.create_all() 已按模型建好列与约束，逐项检查后跳过；
- SQLite 无法直接删除表级唯一约束，使用 batch_alter_table 重建表；
- 降级前预检「同一用户同一角色跨站点重复」，冲突即中止（避免半降级）。

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def _dialect():
    return op.get_bind().dialect.name


def _has_table(table):
    return sa.inspect(op.get_bind()).has_table(table)


def _has_column(table, column):
    if not _has_table(table):
        return False
    return any(c['name'] == column
               for c in sa.inspect(op.get_bind()).get_columns(table))


def _has_index(table, name):
    if not _has_table(table):
        return False
    return any(ix['name'] == name
               for ix in sa.inspect(op.get_bind()).get_indexes(table))


def _unique_name_exists(table, name):
    """唯一索引或唯一约束同名存在（两种建法都要兼容）。"""
    if not _has_table(table):
        return False
    insp = sa.inspect(op.get_bind())
    if any(ix.get('name') == name for ix in insp.get_indexes(table)):
        return True
    return any(uc.get('name') == name
               for uc in insp.get_unique_constraints(table))


def _find_unique(table, columns):
    """返回仅由给定列组成的唯一索引/唯一约束信息，找不到返回 None。"""
    insp = sa.inspect(op.get_bind())
    for ix in insp.get_indexes(table):
        if ix.get('unique') and list(ix.get('column_names') or []) == columns:
            return ('index', ix['name'])
    for uc in insp.get_unique_constraints(table):
        if list(uc.get('column_names') or []) == columns:
            return ('constraint', uc.get('name'))
    return None


def _drop_unique(table, columns):
    """删除仅由给定列组成的唯一索引/约束（SQLite 约束走 batch 重建）。"""
    found = _find_unique(table, columns)
    if found is None:
        return
    kind, name = found
    if kind == 'index':
        op.drop_index(name, table_name=table)
        return
    if not name:
        return
    if _dialect() == 'sqlite':
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_='unique')
    else:
        op.drop_constraint(name, table, type_='unique')


def _duplicate_rows(table, columns):
    """返回按给定列分组后重复的行描述（用于恢复旧唯一约束前预检）。"""
    cols = ', '.join(columns)
    rows = op.get_bind().execute(sa.text(
        f'SELECT {cols}, COUNT(*) AS c FROM {table} '
        f'GROUP BY {cols} HAVING COUNT(*) > 1')).fetchall()
    return [f'{table}({", ".join(str(v) for v in r[:-1])})={r[-1]}' for r in rows]


def upgrade():
    if not _has_table('user_roles'):
        return

    # ---------- 1. site_id 列与普通索引 ----------
    if not _has_column('user_roles', 'site_id'):
        op.add_column('user_roles',
                      sa.Column('site_id', sa.Integer(), nullable=True))
    if not _has_index('user_roles', 'ix_user_roles_site_id'):
        op.create_index('ix_user_roles_site_id', 'user_roles', ['site_id'])

    # ---------- 2. 唯一约束站点化 ----------
    _drop_unique('user_roles', ['user_id', 'role_id'])
    if not _unique_name_exists('user_roles', 'uq_user_role_site'):
        op.create_index('uq_user_role_site', 'user_roles',
                        ['user_id', 'role_id', 'site_id'], unique=True)


def downgrade():
    if not _has_table('user_roles'):
        return

    # 恢复 (user_id, role_id) 全局唯一：先预检跨站点重复，任何 DDL 之前中止
    _abort_if_duplicates('0015 降级', _duplicate_rows(
        'user_roles', ['user_id', 'role_id']))

    # ---------- 1. 移除站点级唯一约束 ----------
    _drop_unique('user_roles', ['user_id', 'role_id', 'site_id'])

    # ---------- 2. 恢复全局唯一 ----------
    if not _unique_name_exists('user_roles', 'uq_user_role'):
        op.create_index('uq_user_role', 'user_roles',
                        ['user_id', 'role_id'], unique=True)

    # ---------- 3. 删除 site_id 索引与列 ----------
    if _has_index('user_roles', 'ix_user_roles_site_id'):
        op.drop_index('ix_user_roles_site_id', table_name='user_roles')
    if _has_column('user_roles', 'site_id'):
        try:
            with op.batch_alter_table('user_roles') as batch:
                batch.drop_column('site_id')
        except Exception:
            # SQLite 批处理失败时保留列（非破坏性降级）
            op.get_bind().execute(sa.text('SELECT 1'))


def _abort_if_duplicates(prefix, conflicts):
    if conflicts:
        raise RuntimeError(
            f'{prefix}迁移中止：存在与目标唯一约束冲突的数据，'
            '请先清理后重试：' + '；'.join(conflicts[:20]))
