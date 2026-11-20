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


def _settings_table():
    """轻量表构造：由 SQLAlchemy 按方言引用标识符，避免 key 保留字问题。"""
    return sa.table(
        'settings',
        sa.column('key', sa.String(100)),
        sa.column('value', sa.Text()),
        sa.column('description', sa.Text()),
        sa.column('updated_at', sa.DateTime()),
    )


def upgrade():
    conn = op.get_bind()
    settings = _settings_table()
    now = datetime.now()
    for key, value, desc in SEARCH_SETTINGS:
        # 幂等：仅当键不存在时插入（兼容所有数据库）
        exists = conn.execute(
            sa.select(sa.func.count()).select_from(settings)
            .where(settings.c.key == key)
        ).scalar()
        if exists == 0:
            conn.execute(settings.insert().values(
                key=key, value=value, description=desc, updated_at=now))


def downgrade():
    conn = op.get_bind()
    settings = _settings_table()
    for key, _, _ in SEARCH_SETTINGS:
        conn.execute(settings.delete().where(settings.c.key == key))
