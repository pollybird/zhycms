"""v2.5.2: 插件结构化内容字段多语言

- product_translations 增加 specs（JSON，结构同主表 products.specs：
  [{'group','items':[{'name','value'}]}]；空/NULL 回退主表默认语言）
- recruit_job_translations 增加 department / location / salary
  （岗位结构化短字段多语言；空/NULL 回退主表默认语言；
  headcount 为数值不随语言变化）

本迁移为既有表补列；新装环境表由 db.create_all() 按新模型直接建齐，
故均做幂等检查（表或列已存在则跳过）。

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-09

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0007'
down_revision = '0006'
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
    # ---- product_translations.specs ----
    if _table_exists('product_translations') and \
            not _column_exists('product_translations', 'specs'):
        op.add_column('product_translations',
                      sa.Column('specs', sa.Text(), nullable=True))

    # ---- recruit_job_translations.department/location/salary ----
    if _table_exists('recruit_job_translations'):
        if not _column_exists('recruit_job_translations', 'department'):
            op.add_column('recruit_job_translations',
                          sa.Column('department', sa.String(100), nullable=True))
        if not _column_exists('recruit_job_translations', 'location'):
            op.add_column('recruit_job_translations',
                          sa.Column('location', sa.String(200), nullable=True))
        if not _column_exists('recruit_job_translations', 'salary'):
            op.add_column('recruit_job_translations',
                          sa.Column('salary', sa.String(100), nullable=True))


def downgrade():
    if _column_exists('product_translations', 'specs'):
        op.drop_column('product_translations', 'specs')
    for col in ('salary', 'location', 'department'):
        if _column_exists('recruit_job_translations', col):
            op.drop_column('recruit_job_translations', col)
