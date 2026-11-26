"""数据库方言扩展包。

v3.3.0 信创适配：内置 openGauss 轻量方言，避免默认镜像引入额外依赖。
v3.3.1 信创适配：内置 KingbaseES（人大金仓）轻量方言，复用标准 psycopg2。
"""
from .kingbase import KingbaseDialect, register_kingbase_dialect
from .opengauss import OpenGaussDialect, register_opengauss_dialect

__all__ = [
    'KingbaseDialect',
    'OpenGaussDialect',
    'register_kingbase_dialect',
    'register_opengauss_dialect',
]
