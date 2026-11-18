"""v3.2.8: 站点异步任务与回收站表

变更内容：
1. 新建 site_jobs，记录站点克隆/备份导入等异步任务的进度与状态；
2. 新建 site_recycle_bin，记录被删除站点与可彻底删除时间。

实现要点：
- 幂等：新装库由 db.create_all() 已按模型建好表与索引，检测到表存在即返回；
- 降级删除两张新表。

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def _has_table(table):
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade():
    if not _has_table('site_jobs'):
        op.create_table(
            'site_jobs',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('site_id', sa.Integer(), nullable=False,
                      server_default='0'),
            sa.Column('job_type', sa.String(32), nullable=False),
            sa.Column('status', sa.String(16), nullable=False,
                      server_default='pending'),
            sa.Column('progress', sa.Integer(), nullable=False,
                      server_default='0'),
            sa.Column('message', sa.String(255), nullable=True),
            sa.Column('payload_json', sa.Text(), nullable=True),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_site_jobs_site_id', 'site_jobs', ['site_id'])
        op.create_index('ix_site_jobs_job_type', 'site_jobs', ['job_type'])
        op.create_index('ix_site_jobs_created_at', 'site_jobs', ['created_at'])
        op.create_index('ix_site_jobs_site_type_status', 'site_jobs',
                        ['site_id', 'job_type', 'status'])

    if not _has_table('site_recycle_bin'):
        op.create_table(
            'site_recycle_bin',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('site_id', sa.Integer(), nullable=False),
            sa.Column('slug', sa.String(100), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('deleted_by', sa.Integer(), nullable=True),
            sa.Column('deleted_at', sa.DateTime(), nullable=False),
            sa.Column('purge_at', sa.DateTime(), nullable=False),
            sa.Column('restored_at', sa.DateTime(), nullable=True),
            sa.Column('snapshot_json', sa.Text(), nullable=True),
        )
        op.create_index('ix_site_recycle_bin_site_id', 'site_recycle_bin',
                        ['site_id'])
        op.create_index('ix_site_recycle_bin_purge_at', 'site_recycle_bin',
                        ['purge_at'])


def downgrade():
    if _has_table('site_recycle_bin'):
        op.drop_index('ix_site_recycle_bin_purge_at',
                      table_name='site_recycle_bin')
        op.drop_index('ix_site_recycle_bin_site_id',
                      table_name='site_recycle_bin')
        op.drop_table('site_recycle_bin')
    if _has_table('site_jobs'):
        op.drop_index('ix_site_jobs_site_type_status', table_name='site_jobs')
        op.drop_index('ix_site_jobs_created_at', table_name='site_jobs')
        op.drop_index('ix_site_jobs_job_type', table_name='site_jobs')
        op.drop_index('ix_site_jobs_site_id', table_name='site_jobs')
        op.drop_table('site_jobs')
