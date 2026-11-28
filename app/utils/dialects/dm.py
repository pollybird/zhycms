"""达梦 DM8 SQLAlchemy 方言适配（v3.3.2）。

依赖 PyPI ``dmpython``（DB-API 驱动）与 ``dmSQLAlchemy``（SQLAlchemy 方言包），
仅在 DM8 部署时需要，见 ``requirements-dm.txt``。本项目仅提供适配代码，
DM8 安装包、客户端工具与授权需用户自行从官方获取。

为什么需要自定义方言：
- ``dmSQLAlchemy`` 的 ``DMDDLCompiler`` 仅在 ``column.autoincrement is True``
  时追加 ``IDENTITY(1, 1)``。ZhyCMS 模型全部是
  ``db.Column(db.Integer, primary_key=True)``，SQLAlchemy 对单列整数主键
  使用默认值 ``autoincrement='auto'``，不会命中该判断，导致建表后主键无自增。
  本模块通过 DDLCompiler 子类按 SQLAlchemy 的自增判定语义补齐。
- ``dmSQLAlchemy`` 未提供 Alembic 集成，``DefaultImpl.get_by_dialect()``
  按 ``dialect.name`` 查表时找不到 ``dm``，故注册 ``DMImpl`` 兜底。

注册名：``dm``、``dm.dmPython``。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_INSTALL_HINT = ('缺少达梦 DM8 数据库驱动，请先安装：'
                 'pip install -r requirements-dm.txt（dmpython、dmSQLAlchemy）')

_DIALECT_CLASS_NAME = 'ZHDMDialect'


def _build_classes():
    """按需导入 dmSQLAlchemy 并生成方言 / DDL 编译器子类。

    必须惰性导入：``app.utils.dialects`` 在应用启动时无条件导入本模块，
    未安装 dmSQLAlchemy 的 MySQL / PostgreSQL 部署不应因此受影响。
    生成的类挂到模块全局，供 ``sqlalchemy.dialects.registry`` 按名加载。
    """
    global ZHDMDialect, ZHDMDDLCompiler

    from sqlalchemy import types as sqltypes
    from dmSQLAlchemy.base import DMDDLCompiler
    from dmSQLAlchemy.dmpython import DMDialect_dmPython

    class ZHDMDDLCompiler(DMDDLCompiler):
        """补齐整数主键的 ``IDENTITY(1, 1)``。

        dmSQLAlchemy 只识别 ``column.autoincrement == True``；这里复用
        SQLAlchemy ``_autoincrement_column`` 的判定语义（单列整数主键、
        无 Python / 服务端默认值），并对显式 ``autoincrement=True`` 的
        复合主键列放行。
        """

        def get_column_specification(self, column, **kwargs):
            colspec = super().get_column_specification(column, **kwargs)
            if 'IDENTITY' in colspec.upper():
                # 父类已按 server_default=Identity 生成，避免重复追加
                return colspec
            if not getattr(column, 'primary_key', False):
                return colspec
            if not isinstance(column.type, sqltypes.Integer):
                return colspec
            if column.autoincrement is False:
                return colspec
            if column.default is not None or column.server_default is not None:
                return colspec
            is_single_pk = (len(column.table.primary_key.columns) == 1
                            and column.table.primary_key.columns.contains_column(column))
            if not is_single_pk and column.autoincrement is not True:
                # 复合主键仅在显式 autoincrement=True 时自增
                return colspec
            return colspec + ' IDENTITY(1, 1)'

    class ZHDMDialect(DMDialect_dmPython):
        """达梦 DM8 方言（基于 dmSQLAlchemy，补齐自增主键 DDL）。"""

        name = 'dm'
        ddl_compiler = ZHDMDDLCompiler
        supports_statement_cache = True
        # dmSQLAlchemy 声明 insert_executemany_returning=True，但驱动对多行
        # INSERT ... RETURNING 返回的 rowcount 不可靠，SQLAlchemy 会因
        # “did not produce the correct number of INSERTed rows” 报错。
        # 关闭批量 RETURNING，回退为普通 executemany（单行插入仍用
        # lastrowid 回填主键）。
        use_insertmanyvalues = False
        insert_executemany_returning = False
        insert_executemany_returning_sort_by_parameter_order = False

    return ZHDMDialect, ZHDMDDLCompiler


def _register_alembic_impl():
    """注册 Alembic DDL 实现（``__dialect__='dm'``）。

    Alembic 的 ``DefaultImpl.get_by_dialect()`` 按 ``dialect.name`` 查表，
    未注册时抛 ``KeyError: 'dm'``。类定义时由 Alembic 元类自动登记。
    """
    try:
        from alembic.ddl.impl import DefaultImpl
    except ImportError:  # 未安装 alembic 时不影响应用运行
        return None

    class DMImpl(DefaultImpl):
        __dialect__ = 'dm'

    return DMImpl


def register_dm_dialect():
    """注册方言名：dm、dm.dmPython。幂等，可重复调用。

    返回 ``'installed'`` 表示注册成功；``'missing'`` 表示未安装
    ``dmSQLAlchemy`` / ``dmpython``（已记录中文安装提示，由调用方决定是否
    中止启动或回退）。
    """
    from sqlalchemy.dialects import registry

    try:
        _build_classes()
    except ImportError as e:
        logger.error('%s（原始错误：%s）', _INSTALL_HINT, e)
        return 'missing'

    registry.register('dm', __name__, _DIALECT_CLASS_NAME)
    registry.register('dm.dmPython', __name__, _DIALECT_CLASS_NAME)
    _register_alembic_impl()
    return 'installed'
