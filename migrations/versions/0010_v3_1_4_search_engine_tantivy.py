"""v3.1.4: 搜索引擎标识 whoosh → tantivy（数据迁移）

v3.1.4 将内置全文搜索引擎由 Whoosh 切换为 Tantivy（Whoosh/jieba 已停止维护）。
本迁移把存量站 settings 表中的 search_engine='whoosh' 改写为 'tantivy'；
已选择 meilisearch / sql 的站点不受影响。
无表结构变更。兼容 SQLite / MySQL / PostgreSQL。

注意：索引文件不在迁移中处理——应用启动时检测 tantivy 索引缺失会自动
后台重建（见 app/__init__.py），重建期间搜索走 SQL LIKE 兜底。

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-24

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE settings SET value = 'tantivy' "
        "WHERE `key` = 'search_engine' AND value = 'whoosh'"
    ))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE settings SET value = 'whoosh' "
        "WHERE `key` = 'search_engine' AND value = 'tantivy'"
    ))
