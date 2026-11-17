"""v3.2.6: 登录日志增加站点维度

变更内容：
1. login_logs 新增 site_id（登录发生时所处的站点，NULL = 历史数据）；
2. 新增索引 ix_login_logs_site_id，供站点管理员按站点范围过滤。

实现要点：
- 幂等：新装库由 db.create_all() 已按模型建好列与索引，逐项检查后跳过；
- SQLite 通过 batch_alter_table 降级删除列/索引。

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def _has_table(table):
    return sa.inspect(op.get_bind()).has_table(table)


def _has_column(table, column):
    if not _has_table(table):
        return False
    return any(c['name'] == column
               for c in sa.inspect(op.get_bind()).get_columns(table))


def _has_index(table, index):
    if not _has_table(table):
        return False
    return any(i['name'] == index
               for i in sa.inspect(op.get_bind()).get_indexes(table))


def upgrade():
    if not _has_table('login_logs'):
        return
    if not _has_column('login_logs', 'site_id'):
        op.add_column('login_logs',
                      sa.Column('site_id', sa.Integer(), nullable=True))
    if not _has_index('login_logs', 'ix_login_logs_site_id'):
        op.create_index('ix_login_logs_site_id', 'login_logs', ['site_id'])


def downgrade():
    if not _has_table('login_logs'):
        return
    if _has_index('login_logs', 'ix_login_logs_site_id'):
        op.drop_index('ix_login_logs_site_id', table_name='login_logs')
    if _has_column('login_logs', 'site_id'):
        with op.batch_alter_table('login_logs') as batch_op:
            batch_op.drop_column('site_id')
