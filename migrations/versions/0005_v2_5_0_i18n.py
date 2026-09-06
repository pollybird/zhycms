"""v2.5.0: 内容级多语言（i18n 2.0）翻译表

新增三张翻译关联表（核心模型）：
- article_translations：文章多语言 title/summary/content/seo_*
- column_translations：栏目多语言 name/summary/page_content/seo_*
- fragment_translations：碎片多语言 name/value

主表保留默认语言字段（冗余），翻译表存非默认语言，查不到 fallback 主表。
插件（product/form/job）的翻译表由各插件迁移自行创建。

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-06

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    from sqlalchemy import inspect
    insp = inspect(op.get_bind())
    return table_name in insp.get_table_names()


def upgrade():
    # ---- article_translations ----
    if not _table_exists('article_translations'):
        op.create_table(
            'article_translations',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('article_id', sa.Integer(), sa.ForeignKey('articles.id', ondelete='CASCADE'), nullable=False),
            sa.Column('locale', sa.String(10), nullable=False),
            sa.Column('title', sa.String(255), nullable=False),
            sa.Column('summary', sa.Text(), nullable=True),
            sa.Column('content', sa.Text(), nullable=True),
            sa.Column('seo_title', sa.String(255), nullable=True),
            sa.Column('seo_keywords', sa.String(255), nullable=True),
            sa.Column('seo_description', sa.String(500), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('article_id', 'locale', name='uq_article_locale'),
        )
        op.create_index('ix_article_trans_locale', 'article_translations', ['locale'])
        op.create_index('ix_article_trans_article_id', 'article_translations', ['article_id'])

    # ---- column_translations ----
    if not _table_exists('column_translations'):
        op.create_table(
            'column_translations',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('column_id', sa.Integer(), sa.ForeignKey('columns.id', ondelete='CASCADE'), nullable=False),
            sa.Column('locale', sa.String(10), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('summary', sa.Text(), nullable=True),
            sa.Column('page_content', sa.Text(), nullable=True),
            sa.Column('seo_title', sa.String(255), nullable=True),
            sa.Column('seo_keywords', sa.String(255), nullable=True),
            sa.Column('seo_description', sa.String(500), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('column_id', 'locale', name='uq_column_locale'),
        )
        op.create_index('ix_column_trans_locale', 'column_translations', ['locale'])
        op.create_index('ix_column_trans_column_id', 'column_translations', ['column_id'])

    # ---- fragment_translations ----
    if not _table_exists('fragment_translations'):
        op.create_table(
            'fragment_translations',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('fragment_id', sa.Integer(), sa.ForeignKey('fragments.id', ondelete='CASCADE'), nullable=False),
            sa.Column('locale', sa.String(10), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('value', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('fragment_id', 'locale', name='uq_fragment_locale'),
        )
        op.create_index('ix_fragment_trans_locale', 'fragment_translations', ['locale'])
        op.create_index('ix_fragment_trans_fragment_id', 'fragment_translations', ['fragment_id'])


def downgrade():
    for tbl in ('article_translations', 'column_translations', 'fragment_translations'):
        if _table_exists(tbl):
            op.drop_table(tbl)
