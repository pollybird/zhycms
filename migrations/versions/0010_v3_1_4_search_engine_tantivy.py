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


def _settings_table():
    """轻量表构造：由 SQLAlchemy 按方言引用标识符，避免 key 保留字问题。"""
    return sa.table(
        'settings',
        sa.column('key', sa.String(100)),
        sa.column('value', sa.Text()),
    )


def _switch(conn, old_value, new_value):
    settings = _settings_table()
    conn.execute(
        settings.update()
        .where(sa.and_(settings.c.key == 'search_engine',
                       settings.c.value == old_value))
        .values(value=new_value))


def upgrade():
    _switch(op.get_bind(), 'whoosh', 'tantivy')


def downgrade():
    _switch(op.get_bind(), 'tantivy', 'whoosh')
