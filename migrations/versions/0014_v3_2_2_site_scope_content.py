"""v3.2.2: 站群内容表站点维度补全

变更内容（表不存在时逐表跳过）：
1. tutorial_categories / tutorials：新增 site_id；slug 全局唯一 → 站内唯一
   （uq_tutorial_category_site_slug / uq_tutorial_site_slug）；
2. builder_pages：新增 site_id；(scope, column_id) → (site_id, scope, column_id)；
3. uploaded_files：新增 site_id；建立 (site_id, content_hash) 普通索引；
4. member_oauths：新增 site_id；(provider, openid) → (site_id, provider, openid)。

实现要点：
- 新列先以 NOT NULL + server_default='0' 添加，存量数据自动归到默认站点；
- 建唯一索引前预检站内重复，冲突则在任何 DDL 之前中止；
- 降级前预检跨站重复，冲突即中止（复用 0012 的预检模式），避免半降级；
- SQLite 无法直接删除表级唯一约束，使用 batch_alter_table 重建表。

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0014'
down_revision = '0013'
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


def _ensure_site_column(table):
    """补 site_id 列与单列索引（幂等）。"""
    if not _has_table(table):
        return False
    if not _has_column(table, 'site_id'):
        op.add_column(
            table,
            sa.Column('site_id', sa.Integer(), nullable=False, server_default='0'))
    if not _has_index(table, f'ix_{table}_site_id'):
        op.create_index(f'ix_{table}_site_id', table, ['site_id'])
    # 存量行一律归属默认站点 0（防御：列刚添加时理论已由 server_default 填 0）
    op.get_bind().execute(sa.text(
        f'UPDATE {table} SET site_id = 0 WHERE site_id IS NULL'))
    return True


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


def _ensure_plain_index(table, column):
    name = f'ix_{table}_{column}'
    if not _has_index(table, name):
        op.create_index(name, table, [column])


def _duplicate_rows(table, columns):
    """返回按给定列分组后重复的行描述（用于建唯一索引前预检）。"""
    non_null = ' AND '.join(f'{c} IS NOT NULL' for c in columns)
    cols = ', '.join(columns)
    rows = op.get_bind().execute(sa.text(
        f'SELECT {cols}, COUNT(*) AS c FROM {table} '
        f'WHERE {non_null} GROUP BY {cols} HAVING COUNT(*) > 1')).fetchall()
    return [f'{table}({", ".join(str(v) for v in r[:-1])})={r[-1]}' for r in rows]


def _abort_if_duplicates(prefix, conflicts):
    if conflicts:
        raise RuntimeError(
            f'{prefix}迁移中止：存在与目标唯一约束冲突的数据，'
            '请先清理后重试：' + '；'.join(conflicts[:20]))


def _ensure_unique_index(table, name, columns):
    if _has_index(table, name):
        return
    _abort_if_duplicates(f'0014（{table}.{name}）', _duplicate_rows(table, columns))
    op.create_index(name, table, columns, unique=True)


# 降级预检：(表名, 列, 说明)
_DOWNGRADE_UNIQUE = (
    ('tutorials', ['slug'], '教程'),
    ('tutorial_categories', ['slug'], '教程分类'),
    ('builder_pages', ['scope', 'column_id'], '页面构建'),
    ('member_oauths', ['provider', 'openid'], '第三方绑定'),
)

# 需要补 site_id 的表
_SCOPED_TABLES = (
    'tutorial_categories', 'tutorials', 'builder_pages',
    'uploaded_files', 'member_oauths',
)


def upgrade():
    # ---------- 1. site_id 列 ----------
    for table in _SCOPED_TABLES:
        _ensure_site_column(table)

    # ---------- 2. 教程：slug 站点级唯一 ----------
    if _has_table('tutorial_categories'):
        _drop_unique('tutorial_categories', ['slug'])
        _ensure_plain_index('tutorial_categories', 'slug')
        _ensure_unique_index(
            'tutorial_categories', 'uq_tutorial_category_site_slug',
            ['site_id', 'slug'])
    if _has_table('tutorials'):
        _drop_unique('tutorials', ['slug'])
        _ensure_plain_index('tutorials', 'slug')
        _ensure_unique_index(
            'tutorials', 'uq_tutorial_site_slug', ['site_id', 'slug'])

    # ---------- 3. 页面构建：站点 + 作用域唯一 ----------
    if _has_table('builder_pages'):
        _drop_unique('builder_pages', ['scope', 'column_id'])
        _ensure_unique_index(
            'builder_pages', 'uq_builder_page_site_scope_column',
            ['site_id', 'scope', 'column_id'])

    # ---------- 4. 上传索引：站内内容 hash ----------
    if _has_table('uploaded_files'):
        if not _has_index('uploaded_files', 'ix_uploaded_file_site_hash'):
            op.create_index('ix_uploaded_file_site_hash', 'uploaded_files',
                            ['site_id', 'content_hash'])

    # ---------- 5. 第三方绑定：站点级 openid 唯一 ----------
    if _has_table('member_oauths'):
        _drop_unique('member_oauths', ['provider', 'openid'])
        _ensure_unique_index(
            'member_oauths', 'uq_member_oauth_site_openid',
            ['site_id', 'provider', 'openid'])


def downgrade():
    bind = op.get_bind()

    # 降级会恢复全局唯一：先预检跨站重复，任何 DDL 之前中止（避免半降级）
    conflicts = []
    for table, columns, label in _DOWNGRADE_UNIQUE:
        if not _has_table(table):
            continue
        try:
            conflicts.extend(_duplicate_rows(table, columns))
        except sa.exc.SQLAlchemyError:
            continue
    _abort_if_duplicates('0014 降级', conflicts)

    # ---------- 1. 移除站点级唯一索引 ----------
    for table, name in (
            ('tutorial_categories', 'uq_tutorial_category_site_slug'),
            ('tutorials', 'uq_tutorial_site_slug'),
            ('builder_pages', 'uq_builder_page_site_scope_column'),
            ('member_oauths', 'uq_member_oauth_site_openid'),
            ('uploaded_files', 'ix_uploaded_file_site_hash')):
        if _has_index(table, name):
            op.drop_index(name, table_name=table)

    # ---------- 2. 恢复全局唯一 ----------
    for table in ('tutorial_categories', 'tutorials'):
        if not _has_table(table):
            continue
        plain = f'ix_{table}_slug'
        if _has_index(table, plain):
            op.drop_index(plain, table_name=table)
        if not _has_index(table, plain):
            op.create_index(plain, table, ['slug'], unique=True)

    if _has_table('builder_pages'):
        if not _has_index('builder_pages', 'uq_builder_page_scope_column'):
            op.create_index('uq_builder_page_scope_column', 'builder_pages',
                            ['scope', 'column_id'], unique=True)

    if _has_table('member_oauths'):
        if not _has_index('member_oauths', 'uq_member_oauth_openid'):
            op.create_index('uq_member_oauth_openid', 'member_oauths',
                            ['provider', 'openid'], unique=True)

    # ---------- 3. 删除 site_id 列 ----------
    for table in _SCOPED_TABLES:
        if not _has_table(table) or not _has_column(table, 'site_id'):
            continue
        if _has_index(table, f'ix_{table}_site_id'):
            op.drop_index(f'ix_{table}_site_id', table_name=table)
        try:
            with op.batch_alter_table(table) as batch:
                batch.drop_column('site_id')
        except Exception:
            # SQLite 批处理失败时保留列（非破坏性降级）
            bind.execute(sa.text('SELECT 1'))
