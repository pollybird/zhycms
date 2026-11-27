"""KingbaseES SQLAlchemy 方言（内置轻量实现，v3.3.1）。

适用：人大金仓 KingbaseES V9（``DB_MODE=pg`` 兼容模式）。KingbaseES 为 PG
线协议兼容，可直接使用标准 PyPI ``psycopg2-binary`` 驱动，无需专用驱动或
``LD_LIBRARY_PATH``。

为什么需要自定义方言：
- KingbaseES 的 ``select version()`` 返回 ``KingbaseES V009R001C010``，
  标准 PostgreSQL 方言的 ``_get_server_version_info`` 解析该串会抛
  ``AssertionError``，导致 ``create_engine`` 连接后获取
  ``server_version_info`` 失败。
- 本方言覆盖版本解析，改用 ``SHOW server_version``（V9R1C10 实测返回
  ``12.1``）解析为 ``(12, 1)``，让 SQLAlchemy / Alembic 按 PostgreSQL 12
  行为工作。
- KingbaseES 对 FK 引用列的唯一性约束检查比 PostgreSQL 更严格：
  PostgreSQL 允许 FK 引用仅有 ``UNIQUE INDEX`` 的列，而 KingbaseES 要求
  显式 ``UNIQUE CONSTRAINT``。SQLAlchemy PG 方言对
  ``Column(unique=True, index=True)`` 只生成独立 ``CREATE UNIQUE INDEX``
  而不在 ``CREATE TABLE`` 中内联 ``UNIQUE`` 约束，导致 ``db.create_all()``
  在 KingbaseES 上因 FK 约束检查失败。本方言通过自定义 DDL 编译器，
  为 ``unique=True`` 但缺少 ``UniqueConstraint`` 的列补充内联 ``UNIQUE``，
  确保 KingbaseES 的 FK 约束检查通过。

注册名：``kingbase``、``kingbase.psycopg2``。
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import schema
from sqlalchemy.dialects.postgresql.base import PGDDLCompiler
from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2

logger = logging.getLogger(__name__)

_KINGBASE_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


class KingbaseDDLCompiler(PGDDLCompiler):
    """KingbaseES DDL 编译器：补充 ``unique=True`` 列的内联 UNIQUE 约束。

    SQLAlchemy PG 方言对 ``Column(unique=True, index=True)`` 只创建独立
    ``CREATE UNIQUE INDEX``，不在 ``CREATE TABLE`` 中生成 ``UNIQUE`` 约束。
    KingbaseES 比 PostgreSQL 更严格，FK 引用列必须有显式 ``UNIQUE CONSTRAINT``，
    仅 ``UNIQUE INDEX`` 不够。此编译器为缺少 ``UniqueConstraint`` 的
    ``unique=True`` 列在列定义中补充 ``UNIQUE`` 关键字。
    """

    def get_column_specification(self, column, **kwargs):
        colspec = super().get_column_specification(column, **kwargs)
        if not column.unique:
            return colspec
        # Column(unique=True) 不带 index 时，PG 方言已在表级生成
        # UniqueConstraint，无需重复添加。Column(unique=True, index=True)
        # 时，PG 方言只创建独立 UNIQUE INDEX，没有 UniqueConstraint，
        # 需要在此补充列级 UNIQUE 约束以满足 KingbaseES FK 检查。
        has_table_level_uc = any(
            isinstance(c, schema.UniqueConstraint)
            and len(c.columns) == 1
            and c.columns[0].name == column.name
            for c in column.table.constraints
        )
        if not has_table_level_uc:
            colspec += " UNIQUE"
        return colspec


class KingbaseDialect(PGDialect_psycopg2):
    """KingbaseES（pg 兼容模式）方言，复用标准 psycopg2 驱动。"""

    name = "kingbase"
    driver = "psycopg2"
    supports_statement_cache = True
    supports_transactional_ddl = True
    ddl_compiler = KingbaseDDLCompiler

    def _get_server_version_info(self, connection):
        # 优先 SHOW server_version（V9R1C10 返回 "12.1" → (12, 1)），
        # 失败回退 SHOW server_version_num（"120001" → (12, 1)）。
        for sql in ("SHOW server_version", "SHOW server_version_num"):
            try:
                raw = connection.exec_driver_sql(sql).scalar()
            except Exception:  # noqa: BLE001 任一 SHOW 失败即尝试下一项
                continue
            text = str(raw or "").strip()
            if not text:
                continue
            if sql.endswith("server_version_num"):
                # KingbaseES 的 server_version_num 编码为 major*10000 + minor
                # （V9R1C10 实测 "12.1" 对应 "120001"），与标准 PG 编码不同。
                try:
                    n = int(text)
                except ValueError:
                    continue
                return (n // 10000, n % 10000)
            m = _KINGBASE_VERSION_RE.match(text)
            if m:
                parts = [int(g) for g in m.groups() if g is not None]
                if parts:
                    return tuple(parts)
        # 极端兜底：避免返回 None 导致后续版本比较崩溃。
        # 留痕便于运维排查（如连到非预期库 / 权限不足导致 SHOW 失败被静默掩盖）。
        logger.warning(
            'KingbaseES 版本解析失败（SHOW server_version / server_version_num 均不可用），'
            '回退默认版本 (12, 1)')
        return (12, 1)


def _register_alembic_impl():
    """注册 Alembic DDL 实现。

    Alembic 的 ``DefaultImpl.get_by_dialect()`` 按 ``dialect.name`` 查表，
    未注册时抛 ``KeyError: 'kingbase'``。复用 PostgreSQL 实现，类定义时由
    Alembic 元类自动登记（``__dialect__``）。
    """
    try:
        from alembic.ddl.postgresql import PostgresqlImpl
    except ImportError:  # 未安装 alembic 时不影响应用运行
        return None

    class KingbaseImpl(PostgresqlImpl):
        __dialect__ = 'kingbase'

    return KingbaseImpl


def register_kingbase_dialect():
    """注册方言名：kingbase、kingbase.psycopg2。幂等，可重复调用。

    KingbaseES 无官方 PyPI SQLAlchemy 方言包，始终注册本模块内置实现。
    返回 ``'builtin'`` 表示实际生效的实现。
    """
    from sqlalchemy.dialects import registry

    registry.register("kingbase", __name__, "KingbaseDialect")
    registry.register("kingbase.psycopg2", __name__, "KingbaseDialect")
    _register_alembic_impl()
    return 'builtin'
