"""v3.3.4: 站点多域名与子域作用域

变更内容：
1. 新增 site_domains 表，保存站点的附加独立域名（主域名仍为 sites.domain）；
2. `ix_sites_subdomain` 由唯一索引改为普通索引——子域标签改为按所属域名
   作用域唯一（www.a.com 与 www.b.com 可分别归属不同站点），唯一性由应用层
   保存校验保证。

幂等：新装 db.create_all 已按模型建表/普通索引；旧库由本迁移补齐。
SQLite / MySQL / PostgreSQL / openGauss / KingbaseES / DM8 / PolarDB 通用。

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-28

"""
from alembic import op
import sqlalchemy as sa


revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def _has_table(table):
    return sa.inspect(op.get_bind()).has_table(table)


def _subdomain_indexes(bind):
    insp = sa.inspect(bind)
    if not insp.has_table('sites'):
        return []
    return [ix for ix in insp.get_indexes('sites')
            if (ix.get('column_names') or []) == ['subdomain']]


def upgrade():
    bind = op.get_bind()

    # 1. 子域唯一索引 → 普通索引（按域名作用域唯一由应用层校验）
    if _has_table('sites'):
        indexes = _subdomain_indexes(bind)
        if any(ix.get('unique') for ix in indexes):
            for ix in indexes:
                op.drop_index(ix['name'], table_name='sites')
            op.create_index('ix_sites_subdomain', 'sites', ['subdomain'])

    # 2. 站点附加域名表
    if not _has_table('site_domains'):
        op.create_table(
            'site_domains',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('site_id', sa.Integer(), nullable=False),
            sa.Column('domain', sa.String(length=255), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.ForeignKeyConstraint(['site_id'], ['sites.id'],
                                    ondelete='CASCADE'),
            sa.UniqueConstraint('domain', name='uq_site_domains_domain'),
        )
        op.create_index('ix_site_domains_site_id', 'site_domains', ['site_id'])


def downgrade():
    bind = op.get_bind()

    if _has_table('site_domains'):
        op.drop_index('ix_site_domains_site_id', table_name='site_domains')
        op.drop_table('site_domains')

    if not _has_table('sites'):
        return
    indexes = _subdomain_indexes(bind)
    if any(ix.get('unique') for ix in indexes):
        return

    # 恢复唯一索引前预检重复子域（任何 DDL 之前中止）
    rows = bind.execute(sa.text(
        "SELECT subdomain, COUNT(*) AS c FROM sites "
        "WHERE subdomain IS NOT NULL GROUP BY subdomain HAVING COUNT(*) > 1"
    )).fetchall()
    if rows:
        detail = '；'.join(f'{r[0]}（{r[1]} 条）' for r in rows[:20])
        raise RuntimeError(
            '0021 降级中止：存在重复子域，无法恢复唯一索引。'
            f'请先清理后重试：{detail}')

    for ix in indexes:
        op.drop_index(ix['name'], table_name='sites')
    op.create_index('ix_sites_subdomain', 'sites', ['subdomain'], unique=True)
