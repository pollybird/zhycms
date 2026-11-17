"""API 鉴权端点（v2.6.3）：JWT 登录 / 刷新 / 登出。

与后台 flask-login 完全独立，专为 Headless / API 场景设计。
- login：用户名 + 密码 → access_token（默认 15min）+ refresh_token（默认 7d）
- refresh：refresh_token → 新 access_token
- logout：v3.1.9 起在 Redis 可用时将 jti 写入黑名单实现服务端即时失效；
  无 Redis 时仍为无状态 JWT，由客户端删除 token，服务端最长残留至过期。

v3.2.6：改为按站点签发/校验（app.utils.api_jwt），不同站点可配置不同密钥。
"""
import time

import jwt as pyjwt
from flask import request

from ..extensions import limiter
from ..models.user import User
from ..models.setting import Setting
from ..utils import jwt_blocklist
from ..utils.api_jwt import create_token, decode_token, access_expires_seconds
from . import api_bp
from .views import api_ok, api_err


def _login_limit():
    """登录端点限流值（每 IP 每分钟），从 Setting 读取。"""
    return f"{Setting.get('api_rate_limit_login', '5')} per minute"


def _bearer_token():
    header = request.headers.get('Authorization', '') or ''
    if header.lower().startswith('bearer '):
        return header[7:].strip()
    return ''


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

    identity = str(user.id)
    additional_claims = {'username': user.username, 'uid': user.id}
    access_token = create_token(identity, 'access', additional_claims)
    refresh_token = create_token(identity, 'refresh', additional_claims)

    return api_ok({
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
        'expires_in': access_expires_seconds(),
    })


@api_bp.route('/auth/refresh', methods=['POST'])
def api_refresh():
    """用 refresh_token 换取新的 access_token。"""
    token = _bearer_token()
    if not token:
        return api_err(401, '缺少访问令牌')
    try:
        claims = decode_token(token, expected_type='refresh')
    except pyjwt.PyJWTError:
        return api_err(401, '令牌无效或已过期')

    identity = claims.get('sub')
    additional_claims = {
        'username': claims.get('username', ''),
        'uid': claims.get('uid'),
    }
    access_token = create_token(identity, 'access', additional_claims)
    return api_ok({
        'access_token': access_token,
        'token_type': 'Bearer',
        'expires_in': access_expires_seconds(),
    })


@api_bp.route('/auth/logout', methods=['POST'])
def api_logout():
    """登出。

    v3.1.9 VULN-007：携带 token 时尝试把 jti 写入 Redis 黑名单，实现服务端
    即时失效；无 Redis 或未携带 token 时保持原有语义（客户端自行删除 token）。
    使用可选鉴权以兼容无 token 的登出调用，不破坏既有客户端。
    """
    token = _bearer_token()
    claims = {}
    if token:
        try:
            claims = decode_token(token)
        except pyjwt.PyJWTError:
            claims = {}
    jti = claims.get('jti')
    exp = claims.get('exp')
    if jti and jwt_blocklist.is_enabled():
        remaining = int(exp - time.time()) if exp else None
        if jwt_blocklist.revoke(jti, remaining):
            return api_ok({'message': '已登出，当前 token 已立即失效'})
    return api_ok({'message': '已登出，请在客户端清除本地 token'})
