from flask import Blueprint

# 后台主蓝本（需要登录鉴权）
admin_bp = Blueprint('admin', __name__, template_folder='templates')

# 登录鉴权蓝本（独立注册，便于控制登录路由无需鉴权）
admin_auth_bp = Blueprint('admin_auth', __name__, template_folder='templates')

# 导入子模块以注册路由
from . import auth  # noqa: E402,F401
from . import dashboard  # noqa: E402,F401
from . import column  # noqa: E402,F401
from . import article  # noqa: E402,F401
from . import fragment  # noqa: E402,F401
# 自定义表单 v2.3.0 起转为内置插件 plugins/form，后台路由由插件注册到 admin_bp
from . import setting  # noqa: E402,F401
from . import upload  # noqa: E402,F401
# 模块1 RBAC：用户与角色管理
from . import users  # noqa: E402,F401
# 模块2 审计日志
from . import audit  # noqa: E402,F401
# 模块4 备份运维
from . import backup  # noqa: E402,F401
# v2.2.0 插件管理
from . import plugins  # noqa: E402,F401
# v2.2.0 主题管理
from . import themes   # noqa: E402,F401
# v2.2.0 危险操作二次确认验证码（卸载插件/删除主题共用）
from . import confirm  # noqa: E402,F401
