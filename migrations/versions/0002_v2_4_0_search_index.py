"""v2.4.0: 新增 search_index 元数据表

用于跨搜索引擎的索引一致性追踪：记录每篇文章的最后索引时间和内容哈希，
rebuild_all() 时可跳过未变更文章，提升重建效率。

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-02

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    # 幂等：全新安装路径下 db.create_all() 已按当前 ORM 建出 search_index 表，
    # 此处跳过 DDL，仅让 alembic 版本正常前进；旧库（表不存在）才执行建表。
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table('search_index'):
        return
    op.create_table(
        'search_index',
        sa.Column('article_id', sa.Integer(), nullable=False),
        sa.Column('indexed_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('content_hash', sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint('article_id'),
    )
    op.create_index('ix_search_index_indexed_at', 'search_index', ['indexed_at'])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table('search_index'):
        return
    op.drop_index('ix_search_index_indexed_at', table_name='search_index')
    op.drop_table('search_index')
