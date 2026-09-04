"""v2.4.0: 插入全文搜索相关 Setting 默认值

幂等插入 search_engine / search_meili_url 等 6 个搜索设置键。
已有值不覆盖。兼容 SQLite / MySQL / PostgreSQL。

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-02

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

SEARCH_SETTINGS = [
    ('search_engine', 'whoosh', '全文搜索引擎（whoosh / meilisearch / sql）'),
    ('search_meili_url', '', 'Meilisearch 服务地址'),
    ('search_meili_key', '', 'Meilisearch API Key'),
    ('search_index_on_save', 'on', '文章保存时自动索引（on / off）'),
    ('search_results_per_page', '20', '每页搜索结果数'),
    ('search_highlight', 'on', '高亮匹配关键词（on / off）'),
]


def upgrade():
    conn = op.get_bind()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for key, value, desc in SEARCH_SETTINGS:
        # 幂等：仅当键不存在时插入（兼容所有数据库）
        exists = conn.execute(
            sa.text('SELECT COUNT(*) FROM settings WHERE `key` = :key'),
            {'key': key}
        ).scalar()
        if exists == 0:
            conn.execute(sa.text(
                'INSERT INTO settings (`key`, value, description, updated_at) '
                'VALUES (:key, :value, :desc, :now)'
            ), {'key': key, 'value': value, 'desc': desc, 'now': now})


def downgrade():
    conn = op.get_bind()
    for key, _, _ in SEARCH_SETTINGS:
        conn.execute(
            sa.text('DELETE FROM settings WHERE `key` = :key'),
            {'key': key}
        )
