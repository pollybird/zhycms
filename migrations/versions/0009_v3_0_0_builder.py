"""v3.0.0: 可视化页面构建器表

- builder_pages：页面（作用域 home/page/list/article + 可选 column_id），
  含 draft_json / published_json 双布局槽位
- builder_revisions：发布修订快照

新装环境由 db.create_all() 直接建齐，本迁移做幂等检查。

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-12

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    from sqlalchemy import inspect
    insp = inspect(op.get_bind())
    return table_name in insp.get_table_names()


def upgrade():
    if not _table_exists('builder_pages'):
        op.create_table(
            'builder_pages',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('scope', sa.String(length=16), nullable=False),
            sa.Column('column_id', sa.Integer(), nullable=True),
            sa.Column('name', sa.String(length=100), nullable=False,
                      server_default=''),
            sa.Column('status', sa.String(length=16), nullable=False,
                      server_default='draft'),
            sa.Column('draft_json', sa.Text(), nullable=True),
            sa.Column('published_json', sa.Text(), nullable=True),
            sa.Column('published_at', sa.DateTime(), nullable=True),
            sa.Column('author_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.ForeignKeyConstraint(['column_id'], ['columns.id']),
            sa.ForeignKeyConstraint(['author_id'], ['users.id']),
            sa.UniqueConstraint('scope', 'column_id',
                                name='uq_builder_page_scope_column'),
        )
        op.create_index('ix_builder_pages_scope', 'builder_pages', ['scope'])
        op.create_index('ix_builder_pages_column_id', 'builder_pages',
                        ['column_id'])

    if not _table_exists('builder_revisions'):
        op.create_table(
            'builder_revisions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('page_id', sa.Integer(), nullable=False),
            sa.Column('data_json', sa.Text(), nullable=False),
            sa.Column('note', sa.String(length=255), server_default=''),
            sa.Column('author_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.ForeignKeyConstraint(['page_id'], ['builder_pages.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        )
        op.create_index('ix_builder_revisions_page_id', 'builder_revisions',
                        ['page_id'])


def downgrade():
    if _table_exists('builder_revisions'):
        op.drop_index('ix_builder_revisions_page_id',
                      table_name='builder_revisions')
        op.drop_table('builder_revisions')
    if _table_exists('builder_pages'):
        op.drop_index('ix_builder_pages_column_id', table_name='builder_pages')
        op.drop_index('ix_builder_pages_scope', table_name='builder_pages')
        op.drop_table('builder_pages')
