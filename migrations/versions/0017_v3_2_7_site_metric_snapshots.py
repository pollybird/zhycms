"""v3.2.7: 新增站点资源指标每日快照表

变更内容：
1. 新建 site_metric_snapshots，按 (site_id, date) 唯一保存每日指标；
2. 为 site_id / date 建立索引，供趋势查询与站点过滤。

实现要点：
- 幂等：新装库由 db.create_all() 已按模型建好表与索引，检测到表存在即返回；
- 降级删除整表。

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def _has_table(table):
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade():
    if _has_table('site_metric_snapshots'):
        return

    op.create_table(
        'site_metric_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('site_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('article_count', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('view_count', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('cache_entries', sa.Integer(), nullable=True),
        sa.Column('disk_bytes', sa.BigInteger(), nullable=False,
                  server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('site_id', 'date', name='uq_site_metric_site_date'),
    )
    op.create_index('ix_site_metric_snapshots_site_id',
                    'site_metric_snapshots', ['site_id'])
    op.create_index('ix_site_metric_snapshots_date',
                    'site_metric_snapshots', ['date'])


def downgrade():
    if not _has_table('site_metric_snapshots'):
        return
    op.drop_index('ix_site_metric_snapshots_date',
                  table_name='site_metric_snapshots')
    op.drop_index('ix_site_metric_snapshots_site_id',
                  table_name='site_metric_snapshots')
    op.drop_table('site_metric_snapshots')
