"""v2.4.0: uploaded_files 增加 storage 列 + 存储驱动设置

- uploaded_files.storage VARCHAR(16) NOT NULL DEFAULT 'local'
  （local / aliyun / tencent / qiniu，记录每个文件的存储归属，
  切换云驱动后旧文件 URL 不失效）
- 幂等插入 Setting storage_driver=local（默认本地存储，升级零行为变化）

兼容 SQLite / MySQL / PostgreSQL（batch 模式 + SELECT 预检）。

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def _column_exists(conn, table, column):
    """跨库判断列是否存在（SQLite / MySQL / PostgreSQL 通用查 information_schema 不现实，
    用 PRAGMA / SHOW COLUMNS 分支；这里统一用 SQLAlchemy inspect）。"""
    from sqlalchemy import inspect
    insp = inspect(conn)
    try:
        cols = [c['name'] for c in insp.get_columns(table)]
        return column in cols
    except Exception:
        return False


def upgrade():
    conn = op.get_bind()

    # 1. uploaded_files 加 storage 列（batch 模式兼容 SQLite）
    if not _column_exists(conn, 'uploaded_files', 'storage'):
        with op.batch_alter_table('uploaded_files') as batch_op:
            batch_op.add_column(sa.Column(
                'storage', sa.String(length=16), nullable=False,
                server_default='local'))

    # 2. 幂等插入 storage_driver 设置
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    exists = conn.execute(
        sa.text('SELECT COUNT(*) FROM settings WHERE `key` = :key'),
        {'key': 'storage_driver'}
    ).scalar()
    if exists == 0:
        conn.execute(sa.text(
            'INSERT INTO settings (`key`, value, description, updated_at) '
            'VALUES (:key, :value, :desc, :now)'
        ), {'key': 'storage_driver', 'value': 'local',
            'desc': '文件存储驱动（local 本地 / aliyun 阿里云OSS / tencent 腾讯云COS / qiniu 七牛云）',
            'now': now})


def downgrade():
    conn = op.get_bind()
    if _column_exists(conn, 'uploaded_files', 'storage'):
        with op.batch_alter_table('uploaded_files') as batch_op:
            batch_op.drop_column('storage')
    conn.execute(
        sa.text('DELETE FROM settings WHERE `key` = :key'),
        {'key': 'storage_driver'}
    )
