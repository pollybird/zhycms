"""v2.5.0: 插件多语言翻译表（i18n 2.0 插件部分）

新增四张插件翻译关联表：
- product_translations：产品多语言 title/summary/content/seo_*
- form_translations：表单多语言 name/description/success_message
- recruit_job_translations：岗位多语言 title/description
- friend_link_translations：友情链接多语言名称（仅名称；URL/LOGO 不随语言变化）

主表保留默认语言字段（冗余），翻译表存非默认语言，查不到 fallback 主表。
启动期 db.create_all() 也会为新装/已启用插件兜底建表，本迁移保证
Alembic metadata 与 schema 一致（避免 autogenerate 误报）。

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-06

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    from sqlalchemy import inspect
    insp = inspect(op.get_bind())
    return table_name in insp.get_table_names()


def upgrade():
    # ---- product_translations ----
    if not _table_exists('product_translations'):
        op.create_table(
            'product_translations',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
            sa.Column('locale', sa.String(10), nullable=False),
            sa.Column('title', sa.String(200), nullable=False),
            sa.Column('summary', sa.Text(), nullable=True),
            sa.Column('content', sa.Text(), nullable=True),
            sa.Column('seo_title', sa.String(255), nullable=True),
            sa.Column('seo_keywords', sa.String(255), nullable=True),
            sa.Column('seo_description', sa.String(500), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('product_id', 'locale', name='uq_product_locale'),
        )
        op.create_index('ix_product_trans_locale', 'product_translations', ['locale'])
        op.create_index('ix_product_trans_product_id', 'product_translations', ['product_id'])

    # ---- form_translations ----
    if not _table_exists('form_translations'):
        op.create_table(
            'form_translations',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('form_id', sa.Integer(), sa.ForeignKey('forms.id', ondelete='CASCADE'), nullable=False),
            sa.Column('locale', sa.String(10), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('success_message', sa.String(255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('form_id', 'locale', name='uq_form_locale'),
        )
        op.create_index('ix_form_trans_locale', 'form_translations', ['locale'])
        op.create_index('ix_form_trans_form_id', 'form_translations', ['form_id'])

    # ---- recruit_job_translations ----
    if not _table_exists('recruit_job_translations'):
        op.create_table(
            'recruit_job_translations',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('job_id', sa.Integer(), sa.ForeignKey('recruit_jobs.id', ondelete='CASCADE'), nullable=False),
            sa.Column('locale', sa.String(10), nullable=False),
            sa.Column('title', sa.String(200), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('job_id', 'locale', name='uq_recruit_job_locale'),
        )
        op.create_index('ix_recruit_job_trans_locale', 'recruit_job_translations', ['locale'])
        op.create_index('ix_recruit_job_trans_job_id', 'recruit_job_translations', ['job_id'])

    # ---- friend_link_translations ----
    if not _table_exists('friend_link_translations'):
        op.create_table(
            'friend_link_translations',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('link_id', sa.Integer(), sa.ForeignKey('friend_links.id', ondelete='CASCADE'), nullable=False),
            sa.Column('locale', sa.String(10), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.UniqueConstraint('link_id', 'locale', name='uq_friend_link_locale'),
        )
        op.create_index('ix_friend_link_trans_locale', 'friend_link_translations', ['locale'])
        op.create_index('ix_friend_link_trans_link_id', 'friend_link_translations', ['link_id'])


def downgrade():
    for tbl in ('friend_link_translations', 'product_translations', 'form_translations',
                'recruit_job_translations'):
        if _table_exists(tbl):
            op.drop_table(tbl)
