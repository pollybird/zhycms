"""baseline: v2.3.0 完整 schema

新装站点由 db.create_all() 建表后 stamp 此版本；
v2.3.0 及更早旧库检测到已有核心表（users + articles）但无 alembic_version 表时，
直接 stamp 此版本，不执行 DDL。

Revision ID: 0001
Revises:
Create Date: 2026-09-02

"""
from alembic import op  # noqa: F401

# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # 新装路径：db.create_all() 已建全部核心表，此处仅标记起点
    # 旧库路径：env.py 直接 stamp，不执行此函数
    pass


def downgrade():
    # baseline 不支持降级
    pass
