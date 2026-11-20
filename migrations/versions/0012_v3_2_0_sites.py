"""v3.2.0: 站群模式基座（sites 注册表 + site_id 维度列）

变更内容：
1. 新建 `sites` 站点注册表，插入默认站点 id=0（is_default=TRUE）；
2. 内容表新增 `site_id`（默认 0，带索引）：columns / articles / fragments /
   settings / audit_logs；插件会员表 members 存在时同样补列；
3. 唯一约束站点化：
   - columns.slug  → UNIQUE(site_id, slug)
   - fragments.slug→ UNIQUE(site_id, slug)
   - settings.key  → UNIQUE(key, site_id)
   - members.username → UNIQUE(site_id, username)
4. 幂等插入全局设置 `member_scope='shared'`（站点共享会员，兼容现网）。

兼容性：全部操作幂等（新装 db.create_all 已建列/表时跳过），
SQLite / MySQL / PostgreSQL 均通过「唯一索引」实现约束，避免 SQLite
不支持的 ALTER TABLE ADD CONSTRAINT。默认站点 0 使单站点部署零行为变化。

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

# revision identifiers, used by Alembic.
revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None

# 需要补 site_id 的核心表 + 内置内容插件表（表不存在时自动跳过）
_SCOPED_TABLES = (
    'columns', 'articles', 'fragments', 'settings', 'audit_logs',
    # v3.2.0 内置内容插件（插件未安装/未启用时表不存在）
    'forms', 'friend_links', 'products', 'recruit_jobs',
    'banner_groups', 'banners', 'members',
)

# (表名, 单列唯一字段, 站点化唯一索引名, 索引列)
_SITE_UNIQUE = (
    ('columns', 'slug', 'uq_column_site_slug', ['site_id', 'slug']),
    ('fragments', 'slug', 'uq_fragment_site_slug', ['site_id', 'slug']),
    ('settings', 'key', 'uq_setting_key_site', ['key', 'site_id']),
    ('members', 'username', 'uq_member_site_username', ['site_id', 'username']),
    ('forms', 'slug', 'uq_form_site_slug', ['site_id', 'slug']),
    ('banner_groups', 'slug', 'uq_banner_group_site_slug', ['site_id', 'slug']),
)


# 降级时需要恢复全局唯一约束的 (表名, 单列唯一字段)
_DOWNGRADE_UNIQUE = (
    ('columns', 'slug'), ('fragments', 'slug'), ('settings', 'key'),
    ('forms', 'slug'), ('banner_groups', 'slug'), ('members', 'username'),
)


def _find_downgrade_conflicts(conn):
    """v3.2.1：降级前预检跨站重复值，返回冲突描述列表（空表示可安全降级）。

    降级会恢复全局唯一索引，多站点数据下同 slug/key/username 可能跨站重复；
    直接执行 DDL 会半途失败并把数据库留在「部分降级」状态，因此在任何 DDL
    之前先做本检查。
    """
    insp = sa.inspect(conn)
    prep = conn.dialect.identifier_preparer
    conflicts = []
    for table, column in _DOWNGRADE_UNIQUE:
        if not insp.has_table(table):
            continue
        # 标识符按方言引用（settings.key 在 MySQL 中为保留字）
        tbl = prep.quote(table)
        col = prep.quote(column)
        try:
            rows = conn.execute(sa.text(
                f'SELECT {col}, COUNT(*) AS c FROM {tbl} '
                f'GROUP BY {col} HAVING COUNT(*) > 1')).fetchall()
        except SQLAlchemyError:
            # 列不存在（旧版插件表结构）时跳过，不影响其余表预检
            continue
        for row in rows:
            conflicts.append(f'{table}.{column}={row[0]}（{row[1]} 条）')
    return conflicts


def _settings_table():
    """轻量表构造：由 SQLAlchemy 按方言引用标识符，避免 key 保留字问题。"""
    return sa.table(
        'settings',
        sa.column('key', sa.String(100)),
        sa.column('site_id', sa.Integer()),
        sa.column('value', sa.Text()),
        sa.column('description', sa.Text()),
        sa.column('updated_at', sa.DateTime()),
    )


def _dialect():
    return op.get_bind().dialect.name


def _has_table(name):
    return sa.inspect(op.get_bind()).has_table(name)


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


def _drop_single_unique(table, column):
    """删除仅包含该列的唯一索引/唯一约束（SQLite 唯一索引优先）。"""
    insp = sa.inspect(op.get_bind())
    # 1) 唯一索引（SQLite 上 unique=True + index=True 会落成唯一索引）
    for ix in insp.get_indexes(table):
        if ix.get('unique') and (ix.get('column_names') or []) == [column]:
            op.drop_index(ix['name'], table_name=table)
            break
    else:
        # 2) 唯一约束（MySQL/PostgreSQL 的列级 UNIQUE）
        for uc in insp.get_unique_constraints(table):
            if (uc.get('column_names') or []) == [column]:
                name = uc.get('name')
                if name:
                    try:
                        op.drop_constraint(name, table, type_='unique')
                    except Exception:
                        # 约束名不可直接删除（如 SQLite autoindex）：忽略
                        pass
                break


def _ensure_site_column(table):
    if not _has_table(table):
        return
    if not _has_column(table, 'site_id'):
        op.add_column(
            table, sa.Column('site_id', sa.Integer(), nullable=False,
                             server_default='0'))
    if not _has_index(table, f'ix_{table}_site_id'):
        op.create_index(f'ix_{table}_site_id', table, ['site_id'])


def _ensure_single_column_index(table, column):
    """确保该列存在普通索引（去掉唯一性后仍可快速查询）。"""
    insp = sa.inspect(op.get_bind())
    for ix in insp.get_indexes(table):
        if (ix.get('column_names') or []) == [column] and not ix.get('unique'):
            return
    name = f'ix_{table}_{column}'
    if not _has_index(table, name):
        op.create_index(name, table, [column])


def upgrade():
    # ---------- 1. sites 注册表 ----------
    if not _has_table('sites'):
        op.create_table(
            'sites',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('slug', sa.String(100), nullable=False),
            sa.Column('domain', sa.String(255)),
            sa.Column('subdomain', sa.String(100)),
            sa.Column('status', sa.String(16), nullable=False,
                      server_default='open'),
            sa.Column('theme', sa.String(64)),
            sa.Column('is_default', sa.Boolean(), nullable=False,
                      server_default=sa.false()),
            sa.Column('seo_title', sa.String(255)),
            sa.Column('seo_keywords', sa.String(255)),
            sa.Column('seo_description', sa.String(500)),
            sa.Column('sort_order', sa.Integer(), nullable=False,
                      server_default='0'),
            sa.Column('is_deleted', sa.Boolean(), nullable=False,
                      server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(), nullable=False,
                      server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False,
                      server_default=sa.func.now()),
        )
        op.create_index('ix_sites_slug', 'sites', ['slug'], unique=True)
        op.create_index('ix_sites_domain', 'sites', ['domain'], unique=True)
        op.create_index('ix_sites_subdomain', 'sites', ['subdomain'])

    # ---------- 2. site_id 维度列 ----------
    for table in _SCOPED_TABLES:
        _ensure_site_column(table)

    # ---------- 3. 唯一约束站点化 ----------
    for table, column, unique_name, cols in _SITE_UNIQUE:
        if not _has_table(table):
            continue
        _drop_single_unique(table, column)
        _ensure_single_column_index(table, column)
        if not _has_index(table, unique_name):
            op.create_index(unique_name, table, cols, unique=True)

    # ---------- 4. 默认站点 id=0 ----------
    bind = op.get_bind()
    exists = bind.execute(sa.text('SELECT COUNT(*) FROM sites WHERE id = 0')).scalar()
    if not exists:
        if _dialect() == 'mysql':
            # MySQL 默认 0 会被当作自增值，需临时关闭该行为
            op.execute("SET SESSION sql_mode = CONCAT(@@sql_mode, ',NO_AUTO_VALUE_ON_ZERO')")
        op.execute(
            "INSERT INTO sites "
            "(id, name, slug, status, is_default, sort_order, is_deleted,"
            " created_at, updated_at) VALUES "
            "(0, '默认站点', 'default', 'open', TRUE, 0, FALSE,"
            " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )

    # ---------- 5. 全局设置 member_scope ----------
    if _has_table('settings'):
        settings = _settings_table()
        exists = bind.execute(
            sa.select(sa.func.count()).select_from(settings)
            .where(sa.and_(settings.c.key == 'member_scope',
                           settings.c.site_id == 0))
        ).scalar()
        if not exists:
            bind.execute(settings.insert().values(
                key='member_scope', site_id=0, value='shared',
                description='站群会员归属：shared 共享（默认）/ isolated 站点独立',
                updated_at=sa.func.now()))


def downgrade():
    bind = op.get_bind()
    # v3.2.1：先预检跨站重复值，冲突时在任何 DDL 之前中止（避免半降级）
    conflicts = _find_downgrade_conflicts(bind)
    if conflicts:
        raise RuntimeError(
            '0012 降级中止：存在跨站重复值，无法恢复全局唯一约束。'
            '请先合并/清理后重试：' + '；'.join(conflicts[:20]))

    # 还原唯一约束
    for table, column, unique_name, _cols in _SITE_UNIQUE:
        if not _has_table(table):
            continue
        if _has_index(table, unique_name):
            op.drop_index(unique_name, table_name=table)
        idx_name = f'ix_{table}_{column}'
        if _has_index(table, idx_name):
            op.drop_index(idx_name, table_name=table)
        op.create_index(idx_name, table, [column], unique=True)

    # 删除 site_id 列与索引
    for table in _SCOPED_TABLES:
        if not _has_table(table) or not _has_column(table, 'site_id'):
            continue
        if _has_index(table, f'ix_{table}_site_id'):
            op.drop_index(f'ix_{table}_site_id', table_name=table)
        try:
            with op.batch_alter_table(table) as batch:
                batch.drop_column('site_id')
        except Exception:
            # SQLite 旧版本批处理失败时保留列（非破坏性降级）
            bind.execute(sa.text(f'SELECT 1'))

    if _has_table('settings'):
        settings = _settings_table()
        bind.execute(settings.delete().where(settings.c.key == 'member_scope'))

    # 站点权限表（新装由 db.create_all 创建）
    if _has_table('user_site_permissions'):
        op.drop_table('user_site_permissions')

    if _has_table('sites'):
        for ix_name in ('ix_sites_subdomain', 'ix_sites_domain', 'ix_sites_slug'):
            if _has_index('sites', ix_name):
                op.drop_index(ix_name, table_name='sites')
        op.drop_table('sites')
