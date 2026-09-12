"""v2.6.4: 栏目增加前台会员可见性字段

- columns.member_only（布尔，默认 0/false）
  False=所有访客可见；True=仅登录前台会员可见（由 member 插件解释，
  插件未启用时该字段不产生任何访问限制）。

本迁移为既有表补列；新装环境由 db.create_all() 按新模型直接建齐，
故做幂等检查（列已存在则跳过）。

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-12

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    from sqlalchemy import inspect
    insp = inspect(op.get_bind())
    return table_name in insp.get_table_names()


def _column_exists(table_name, column_name):
    from sqlalchemy import inspect
    insp = inspect(op.get_bind())
    if table_name not in insp.get_table_names():
        return False
    return column_name in [c['name'] for c in insp.get_columns(table_name)]


def upgrade():
    if _table_exists('columns') and not _column_exists('columns', 'member_only'):
        op.add_column('columns',
                      sa.Column('member_only', sa.Boolean(), nullable=False,
                                server_default=sa.false()))


def downgrade():
    if _column_exists('columns', 'member_only'):
        op.drop_column('columns', 'member_only')
