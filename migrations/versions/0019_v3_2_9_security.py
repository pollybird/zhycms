"""v3.2.9: 会员短信验证码连续失败计数

为会员短信验证码表增加 fail_count 字段，用于连续输错后主动作废验证码。
会员插件未安装时自动跳过，升降级均幂等。

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-20

"""
from alembic import op
import sqlalchemy as sa


revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def _has_table(table):
    return sa.inspect(op.get_bind()).has_table(table)


def _has_column(table, column):
    if not _has_table(table):
        return False
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(col['name'] == column for col in columns)


def upgrade():
    if _has_table('member_sms_codes') and not _has_column('member_sms_codes', 'fail_count'):
        op.add_column(
            'member_sms_codes',
            sa.Column('fail_count', sa.Integer(), nullable=False, server_default='0'),
        )


def downgrade():
    if _has_column('member_sms_codes', 'fail_count'):
        op.drop_column('member_sms_codes', 'fail_count')
