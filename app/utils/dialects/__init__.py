"""数据库方言扩展包。

v3.3.0 信创适配：内置 openGauss 轻量方言，避免默认镜像引入额外依赖。
"""
from .opengauss import OpenGaussDialect, register_opengauss_dialect

__all__ = ['OpenGaussDialect', 'register_opengauss_dialect']
