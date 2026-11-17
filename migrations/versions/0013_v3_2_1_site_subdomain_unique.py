"""v3.2.1: sites.subdomain 唯一约束

变更内容：
1. 空白子域统一规范化为 NULL（多个 NULL 可共存，空串会互相冲突）；
2. 子域重复时预检中止（不留下半建索引状态）；
3. `ix_sites_subdomain` 由普通索引改为唯一索引（已唯一时跳过）。

幂等：新装 db.create_all 已按模型建立唯一索引；旧库由本迁移补建。
SQLite / MySQL / PostgreSQL 均通过唯一索引实现。

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-16

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def _subdomain_indexes(bind):
    insp = sa.inspect(bind)
    if not insp.has_table('sites'):
        return []
    return [ix for ix in insp.get_indexes('sites')
            if (ix.get('column_names') or []) == ['subdomain']]


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table('sites'):
        return

    # 1. 空白子域转 NULL（唯一索引下空串只允许一条）
    bind.execute(sa.text(
        "UPDATE sites SET subdomain = NULL WHERE subdomain IS NOT NULL AND subdomain = ''"))

    indexes = _subdomain_indexes(bind)
    if any(ix.get('unique') for ix in indexes):
        return

    # 2. 预检重复子域（任何 DDL 之前中止）
    rows = bind.execute(sa.text(
        "SELECT subdomain, COUNT(*) AS c FROM sites "
        "WHERE subdomain IS NOT NULL GROUP BY subdomain HAVING COUNT(*) > 1"
    )).fetchall()
    if rows:
        detail = '；'.join(f'{r[0]}（{r[1]} 条）' for r in rows[:20])
        raise RuntimeError(
            '0013 迁移中止：存在重复子域，无法建立唯一索引。'
            f'请先清理后重试：{detail}')

    # 3. 普通索引 → 唯一索引
    for ix in indexes:
        op.drop_index(ix['name'], table_name='sites')
    op.create_index('ix_sites_subdomain', 'sites', ['subdomain'], unique=True)


def downgrade():
    bind = op.get_bind()
    indexes = _subdomain_indexes(bind)
    if not any(ix.get('unique') for ix in indexes):
        return
    for ix in indexes:
        op.drop_index(ix['name'], table_name='sites')
    op.create_index('ix_sites_subdomain', 'sites', ['subdomain'])
