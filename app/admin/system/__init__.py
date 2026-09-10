"""系统管理域子包（设置 / 用户 / 审计 / 备份 / 主题）。

v2.6.1：从 app/admin/ 顶层按业务域重组。
路由仍全部挂在 admin_bp 上，endpoint 命名空间（admin.*）保持不变。
"""
from . import setting  # noqa: F401
from . import users  # noqa: F401
from . import audit  # noqa: F401
from . import backup  # noqa: F401
from . import themes  # noqa: F401
