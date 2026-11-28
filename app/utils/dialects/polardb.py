"""PolarDB for PostgreSQL SQLAlchemy 方言（内置轻量实现，v3.3.3）。

适用：PolarDB for PostgreSQL 15（本地文件系统 / 单机部署，开源 Apache 2.0）。
PolarDB-PG 复用 PostgreSQL 线协议，可直接使用标准 PyPI ``psycopg2-binary``
驱动，无需专用驱动或客户端库。

为什么需要自定义方言：
- 需要一个独立后端标识 ``polardb_pg``，让初始化向导、``/healthz`` 与备份
  分支能区分「PolarDB」与「PostgreSQL」，而不是退化为 ``postgresql``。
- ``select version()`` 返回 ``PostgreSQL 15.x (PolarDB 15.x.x.x build ...)``，
  标准 PostgreSQL 方言的正则可正常解析；但 PolarDB 后续版本可能调整版本串，
  本方言在父类解析失败时回退 ``SHOW server_version``，避免启动崩溃。
- Alembic 的 ``DefaultImpl.get_by_dialect()`` 按 ``dialect.name`` 查表，
  未注册时会抛 ``KeyError: 'polardb_pg'``，需注册 PostgreSQL 实现子类。

DDL 复用标准 PostgreSQL 实现：PolarDB-PG 与 PG 15 语法兼容，整数主键、
索引、外键与唯一约束行为一致，无需像 KingbaseES 那样定制 DDL 编译器。

注册名：``polardb_pg``、``polardb_pg.psycopg2``。
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


class PolarDBPGDialect(PGDialect_psycopg2):
    """PolarDB for PostgreSQL 方言，复用标准 psycopg2 驱动。"""

    name = 'polardb_pg'
    driver = 'psycopg2'
    supports_statement_cache = True
    supports_transactional_ddl = True

    def _get_server_version_info(self, connection):
        # 正常路径：父类可解析 "PostgreSQL 15.x (PolarDB 15.x.x.x build ...)"。
        try:
            return super()._get_server_version_info(connection)
        except AssertionError:
            logger.debug('polardb_pg 父类版本解析失败，回退 SHOW server_version')

        # 回退一：SHOW server_version（通常返回 "15.20"）。
        for sql in ('SHOW server_version', 'SHOW server_version_num'):
            try:
                raw = connection.exec_driver_sql(sql).scalar()
            except Exception:  # noqa: BLE001 任一 SHOW 失败即尝试下一项
                logger.debug('polardb_pg version probe %r failed, trying next', sql)
                continue
            text = str(raw or '').strip()
            if not text:
                continue
            if sql.endswith('server_version_num'):
                # PostgreSQL 编码：major*10000 + minor*100 + patch
                try:
                    n = int(text)
                except ValueError:
                    continue
                return (n // 10000, (n % 10000) // 100)
            m = _VERSION_RE.match(text)
            if m:
                parts = [int(g) for g in m.groups() if g is not None]
                if parts:
                    return tuple(parts)

        # 极端兜底：PolarDB-PG 当前基线为 15，避免返回 None 导致版本比较崩溃。
        logger.warning(
            'PolarDB-PG 版本解析失败（父类与 SHOW server_version 均不可用），'
            '回退默认版本 (15, 0)')
        return (15, 0)


def _register_alembic_impl():
    """注册 Alembic DDL 实现（复用 PostgreSQL 实现）。

    Alembic 的 ``DefaultImpl.get_by_dialect()`` 按 ``dialect.name`` 查表，
    未注册时抛 ``KeyError: 'polardb_pg'``。类定义时由 Alembic 元类自动登记。
    """
    try:
        from alembic.ddl.postgresql import PostgresqlImpl
    except ImportError:  # 未安装 alembic 时不影响应用运行
        return None

    class PolarDBPGImpl(PostgresqlImpl):
        __dialect__ = 'polardb_pg'

    return PolarDBPGImpl


def register_polardb_dialect():
    """注册方言名：polardb_pg、polardb_pg.psycopg2。幂等，可重复调用。

    PolarDB-PG 无独立 PyPI 方言包，始终注册本模块内置实现。
    返回 ``'builtin'`` 表示实际生效的实现。
    """
    from sqlalchemy.dialects import registry

    registry.register('polardb_pg', __name__, 'PolarDBPGDialect')
    registry.register('polardb_pg.psycopg2', __name__, 'PolarDBPGDialect')
    _register_alembic_impl()
    return 'builtin'
