"""内容 API 的站点级 JWT 签发/校验（v3.2.6）。

flask-jwt-extended 的签名密钥是应用级配置，无法按站点区分；而内容 API
需要每个站点独立配置鉴权方式与密钥，故这里直接用 PyJWT 按当前站点
（由 Host/前台站点上下文解析）读取 ``jwt_secret_key`` 完成 HS256 签发与校验。

兼容性：
- 站点未单独配置密钥时，默认站点沿用应用级密钥以兼容存量 token；
  其他站点以应用级密钥 + 站点 id 派生独立密钥，避免跨站令牌混用；
- 生成的 payload 与 flask-jwt-extended 兼容（sub/type/iat/nbf/exp/jti），
  存量 token 在密钥一致时仍可继续使用；
- 沿用 Redis ``jti`` 黑名单实现登出即时失效。
"""
import hashlib
import hmac
import logging
import time
import uuid

import jwt as pyjwt
from flask import current_app, has_app_context

from ..models.setting import Setting
from . import jwt_blocklist

logger = logging.getLogger(__name__)

ALGORITHM = 'HS256'

_ACCESS_DEFAULT_MINUTES = 15
_REFRESH_DEFAULT_DAYS = 7


def _int_setting(key, default):
    try:
        return int(Setting.get(key, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _current_site_id():
    try:
        from ..sites import current_site_id
        return current_site_id()
    except Exception as e:  # 无站点上下文时按默认站点处理
        logger.debug('读取当前站点失败，使用默认站点：%s', e)
        return 0


def _site_secret(site_id):
    """读取站点显式配置的 JWT 密钥，不回退到默认站点。

    默认站点的密钥即全局配置；其他站点必须单独配置，未配置时由调用方派生。
    """
    if not site_id:
        return (Setting.get('jwt_secret_key') or '').strip()
    cache_map = Setting._request_cache_map()
    if cache_map is not None:
        site_map = cache_map.get(site_id) or {}
        raw = site_map.get('jwt_secret_key')
        if not raw:
            return ''
        if Setting._is_sensitive_key('jwt_secret_key'):
            raw = Setting._resolve_sensitive(
                'jwt_secret_key', raw, site_map, site_id=site_id)
        return (raw or '').strip()
    item = Setting.query.filter_by(key='jwt_secret_key', site_id=site_id).first()
    if item is None or not (item.value or '').strip():
        return ''
    return (Setting.get_for_site('jwt_secret_key', site_id) or '').strip()


def _fallback_secret(site_id):
    """未配置站点密钥时的回退值。

    默认站点继续使用应用级密钥，保证升级前签发的 token 仍有效；
    其余站点基于应用级密钥与站点 id 派生，确保不同站点的 token 互不通用。
    """
    base = (current_app.config.get('JWT_SECRET_KEY')
            or current_app.config['SECRET_KEY'])
    if not site_id:
        return base
    return hmac.new(
        str(base).encode('utf-8'),
        f'zhycms:jwt:site:{site_id}'.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def jwt_secret():
    """当前站点的 JWT 签名密钥；站点未配置时按站点派生回退密钥。"""
    if not has_app_context():
        return (current_app.config.get('JWT_SECRET_KEY')
                or current_app.config['SECRET_KEY'])
    site_id = _current_site_id()
    return _site_secret(site_id) or _fallback_secret(site_id)


def access_expires_seconds():
    """access token 有效期（秒）。"""
    minutes = max(_int_setting('jwt_access_expires_minutes',
                               _ACCESS_DEFAULT_MINUTES), 1)
    return minutes * 60


def _refresh_expires_seconds():
    days = max(_int_setting('jwt_refresh_expires_days',
                            _REFRESH_DEFAULT_DAYS), 1)
    return days * 86400


def create_token(identity, token_type='access', additional_claims=None):
    """按当前站点密钥签发 access/refresh token。"""
    now = int(time.time())
    expires = access_expires_seconds() if token_type == 'access' else _refresh_expires_seconds()
    payload = {
        'sub': str(identity),
        'type': token_type,
        'iat': now,
        'nbf': now,
        'exp': now + expires,
        'jti': uuid.uuid4().hex,
    }
    payload.update(additional_claims or {})
    return pyjwt.encode(payload, jwt_secret(), algorithm=ALGORITHM)


def decode_token(token, expected_type=None):
    """按当前站点密钥校验 token，返回 claims；失败抛 PyJWT 异常。"""
    claims = pyjwt.decode(token, jwt_secret(), algorithms=[ALGORITHM])
    if expected_type and claims.get('type') != expected_type:
        raise pyjwt.InvalidTokenError('token type mismatch')
    jti = claims.get('jti')
    if jti and jwt_blocklist.is_revoked(jti):
        raise pyjwt.InvalidTokenError('token revoked')
    return claims
