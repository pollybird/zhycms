"""数据库方言扩展包。

v3.3.0 信创适配：内置 openGauss 轻量方言，避免默认镜像引入额外依赖。
v3.3.1 信创适配：内置 KingbaseES（人大金仓）轻量方言，复用标准 psycopg2。
v3.3.2 信创适配：接入达梦 DM8，方言类延迟构建（依赖可选包 dmSQLAlchemy）。
"""
from .dm import register_dm_dialect
from .kingbase import KingbaseDialect, register_kingbase_dialect
from .opengauss import OpenGaussDialect, register_opengauss_dialect

__all__ = [
    'KingbaseDialect',
    'OpenGaussDialect',
    'register_dm_dialect',
    'register_kingbase_dialect',
    'register_opengauss_dialect',
]
