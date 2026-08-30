"""内容 API（v2.2.0，只读）：核心端点 + 插件贡献端点，统一鉴权/缓存/CORS。"""
from flask import Blueprint

api_bp = Blueprint('api', __name__)

from . import views  # noqa: E402,F401
