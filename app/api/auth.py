"""API 鉴权端点（v2.6.3）：JWT 登录 / 刷新 / 登出。

与后台 flask-login 完全独立，专为 Headless / API 场景设计。
- login：用户名 + 密码 → access_token（15min）+ refresh_token（7d）
- refresh：refresh_token → 新 access_token
- logout：v3.1.9 起在 Redis 可用时将 jti 写入黑名单实现服务端即时失效；
  无 Redis 时仍为无状态 JWT，由客户端删除 token，服务端最长残留至过期（默认 15 分钟）。
"""
import time

from flask import request, jsonify
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt,
)

from ..extensions import limiter
from ..models.user import User
from ..models.setting import Setting
from ..utils import jwt_blocklist
from . import api_bp
from .views import api_ok, api_err


def _login_limit():
    """登录端点限流值（每 IP 每分钟），从 Setting 读取。"""
    return f"{Setting.get('api_rate_limit_login', '5')} per minute"


@api_bp.route('/auth/login', methods=['POST'])
@limiter.limit(_login_limit)
def api_login():
    """用户名密码登录，签发 JWT。"""
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return api_err(400, '用户名和密码不能为空')

    user = User.query.filter_by(username=username).first()
    if user is None or not user.check_password(password):
        return api_err(401, '用户名或密码错误')

    # 仅允许启用的用户通过 API 登录
    if not getattr(user, 'is_active', True):
        return api_err(403, '账号已被禁用')

    # flask-jwt-extended 要求 identity 为字符串；额外信息放 additional_claims
    identity = str(user.id)
    additional_claims = {'username': user.username, 'uid': user.id}
    access_token = create_access_token(identity=identity, additional_claims=additional_claims)
    refresh_token = create_refresh_token(identity=identity, additional_claims=additional_claims)

    return api_ok({
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
        'expires_in': _access_expires_seconds(),
    })


@api_bp.route('/auth/refresh', methods=['POST'])
@jwt_required(refresh=True)
def api_refresh():
    """用 refresh_token 换取新的 access_token。"""
    identity = get_jwt_identity()
    # 从 refresh token 的 claims 中取回 username/uid，写入新 access token
    claims = get_jwt()
    additional_claims = {
        'username': claims.get('username', ''),
        'uid': claims.get('uid'),
    }
    access_token = create_access_token(identity=identity, additional_claims=additional_claims)
    return api_ok({
        'access_token': access_token,
        'token_type': 'Bearer',
        'expires_in': _access_expires_seconds(),
    })


@api_bp.route('/auth/logout', methods=['POST'])
@jwt_required(optional=True)
def api_logout():
    """登出。

    v3.1.9 VULN-007：携带 token 时尝试把 jti 写入 Redis 黑名单，实现服务端
    即时失效；无 Redis 或未携带 token 时保持原有语义（客户端自行删除 token）。
    使用 optional=True 以兼容无 token 的登出调用，不破坏既有客户端。
    """
    claims = get_jwt() or {}
    jti = claims.get('jti')
    exp = claims.get('exp')
    if jti and jwt_blocklist.is_enabled():
        remaining = int(exp - time.time()) if exp else None
        if jwt_blocklist.revoke(jti, remaining):
            return api_ok({'message': '已登出，当前 token 已立即失效'})
    return api_ok({'message': '已登出，请在客户端清除本地 token'})


def _access_expires_seconds():
    """返回 access token 过期秒数（用于 expires_in 字段）。"""
    from flask import current_app
    expires = current_app.config.get('JWT_ACCESS_TOKEN_EXPIRES', 15 * 60)
    if hasattr(expires, 'total_seconds'):
        return int(expires.total_seconds())
    return int(expires)
