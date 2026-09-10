from flask import Blueprint

# 后台主蓝本（需要登录鉴权）
admin_bp = Blueprint('admin', __name__, template_folder='templates')

# 登录鉴权蓝本（独立注册，便于控制登录路由无需鉴权）
admin_auth_bp = Blueprint('admin_auth', __name__, template_folder='templates')

# ---- 顶层模块（鉴权 / 首页 / 媒体 / 插件 / 二次确认）----
from . import auth  # noqa: E402,F401
from . import dashboard  # noqa: E402,F401
from . import upload  # noqa: E402,F401
from . import plugins  # noqa: E402,F401
from . import confirm  # noqa: E402,F401

# ---- v2.6.1：内容管理域（栏目 / 文章 / 碎片）----
from . import content  # noqa: E402,F401

# ---- v2.6.1：系统管理域（设置 / 用户 / 审计 / 备份 / 主题）----
from . import system  # noqa: E402,F401
