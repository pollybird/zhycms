"""v3.1.5: 后台富文本 Markdown 支持（双写存储）

为 5 张表新增「Markdown 原文 + 格式标记」两列：
- articles.content_md / content_format
- article_translations.content_md / content_format
- columns.page_content_md / page_content_format
- column_translations.page_content_md / page_content_format
- fragments.value_md / value_format

content_format 取值：html（默认，老数据语义不变）/ markdown。
content 列始终是 HTML（全站消费方零改动），*_md 列保存 Markdown 原文
供编辑页回填。另幂等插入设置键 editor_default_mode='ckeditor'。

新列均不建索引（规避 MySQL 5.6 的 767 字节索引前缀限制）。
本迁移为既有表补列，做幂等检查；兼容 SQLite / MySQL / PostgreSQL。

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-01

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None

# (表名, md 列名, format 列名)
_TARGETS = [
    ('articles', 'content_md', 'content_format'),
    ('article_translations', 'content_md', 'content_format'),
    ('columns', 'page_content_md', 'page_content_format'),
    ('column_translations', 'page_content_md', 'page_content_format'),
    ('fragments', 'value_md', 'value_format'),
]


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
    for table, md_col, fmt_col in _TARGETS:
        if not _table_exists(table):
            continue
        if not _column_exists(table, md_col):
            op.add_column(table, sa.Column(md_col, sa.Text(), nullable=True))
        if not _column_exists(table, fmt_col):
            op.add_column(table, sa.Column(
                fmt_col, sa.String(16), nullable=False,
                server_default='html'))

    # 幂等插入设置键：默认编辑模式（ckeditor / markdown），已有值不覆盖
    conn = op.get_bind()
    if _table_exists('settings'):
        exists = conn.execute(
            sa.text("SELECT COUNT(*) FROM settings WHERE `key` = 'editor_default_mode'")
        ).scalar()
        if exists == 0:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute(sa.text(
                'INSERT INTO settings (`key`, value, description, updated_at) '
                "VALUES ('editor_default_mode', 'ckeditor', "
                "'后台默认编辑模式（ckeditor / markdown，仅影响新建内容）', :now)"
            ), {'now': now})


def downgrade():
    # 注意：删列会丢失 Markdown 原文，但 content（HTML）不受影响
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM settings WHERE `key` = 'editor_default_mode'"))
    for table, md_col, fmt_col in _TARGETS:
        if _column_exists(table, fmt_col):
            op.drop_column(table, fmt_col)
        if _column_exists(table, md_col):
            op.drop_column(table, md_col)
