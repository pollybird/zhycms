"""内容管理域子包（栏目 / 文章 / 碎片）。

v2.6.1：从 app/admin/ 顶层按业务域重组。
路由仍全部挂在 admin_bp 上，endpoint 命名空间（admin.*）保持不变。
"""
from . import column  # noqa: F401
from . import article  # noqa: F401
from . import fragment  # noqa: F401
