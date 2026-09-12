"""内容 API（v2.2.0，只读）：核心端点 + 插件贡献端点，统一鉴权/缓存/CORS。
v2.6.3：新增 auth 子模块，提供 JWT 登录/刷新/登出端点。"""
from flask import Blueprint

api_bp = Blueprint('api', __name__)

from . import views  # noqa: E402,F401
from . import auth   # noqa: E402,F401  v2.6.3 JWT 鉴权端点
