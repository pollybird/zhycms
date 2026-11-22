"""openGauss SQLAlchemy 方言（内置轻量实现）。

适用：无法引入 opengauss-sqlalchemy 官方包，或需锁定 SQLAlchemy 版本的场景。

说明：
- openGauss 内核基于 PostgreSQL 9.2.4，返回 (9, 2, 4) 可关闭 PG 高版本
  专有语法探测，避免方言误判（该取值已在 openGauss 7.0.0 上完成全量业务验证）。
- 注册名：opengauss、opengauss.psycopg2（与官方包一致，便于无感切换）。
- 依赖：openGauss 版 psycopg2（不是 PyPI 标准 psycopg2）。
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2

logger = logging.getLogger(__name__)

_OG_VERSION_RE = re.compile(r"openGauss(?:-lite)?[\s/]+(\d+)\.(\d+)\.(\d+)", re.I)
_BASE_PG_VERSION = (9, 2, 4)

# 官方包可能使用的顶层模块名
_OFFICIAL_MODULES = ('opengauss', 'opengauss_sqlalchemy')


class OpenGaussDialect(PGDialect_psycopg2):
    """openGauss 集中式单机方言（psycopg2 / openGauss 驱动）。"""

    name = "opengauss"
    driver = "psycopg2"
    supports_statement_cache = True
    supports_transactional_ddl = True

    def _get_server_version_info(self, connection):
        raw = connection.exec_driver_sql("select version()").scalar()
        text = str(raw or "")
        if _OG_VERSION_RE.search(text):
            return _BASE_PG_VERSION
        # 兼容部分发行版 version() 返回标准 PostgreSQL 串
        return super()._get_server_version_info(connection)


def _register_alembic_impl():
    """注册 Alembic DDL 实现。

    Alembic 的 ``DefaultImpl.get_by_dialect()`` 直接按 ``dialect.name`` 查表
    （``_impls[dialect.name]``），未注册时抛 ``KeyError: 'opengauss'``。
    复用 PostgreSQL 实现并在类定义时由 Alembic 元类自动登记。
    """
    try:
        from alembic.ddl.postgresql import PostgresqlImpl
    except ImportError:  # 未安装 alembic 时不影响应用运行
        return None

    class OpenGaussImpl(PostgresqlImpl):
        __dialect__ = 'opengauss'

    return OpenGaussImpl


def _official_available():
    """官方 opengauss-sqlalchemy 是否已安装（D1：官方包优先）。"""
    import importlib.util

    for mod in _OFFICIAL_MODULES:
        try:
            if importlib.util.find_spec(mod) is not None:
                return True
        except (ImportError, ValueError):
            continue
    return False


def register_opengauss_dialect():
    """注册方言名：opengauss、opengauss.psycopg2。幂等，可重复调用。

    官方包已安装时保留其注册结果；否则注册本模块的内置方言。
    返回 ``'official'`` / ``'builtin'`` 表示实际生效的实现。
    """
    from sqlalchemy.dialects import registry

    if _official_available():
        logger.debug('检测到官方 opengauss-sqlalchemy，跳过内置方言注册')
        impl = 'official'
    else:
        registry.register("opengauss", __name__, "OpenGaussDialect")
        registry.register("opengauss.psycopg2", __name__, "OpenGaussDialect")
        impl = 'builtin'
    _register_alembic_impl()
    return impl
