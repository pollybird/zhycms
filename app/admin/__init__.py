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
from . import friend_link  # noqa: E402,F401
from . import form  # noqa: E402,F401
from . import setting  # noqa: E402,F401
from . import upload  # noqa: E402,F401
