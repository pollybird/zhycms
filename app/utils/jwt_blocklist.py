"""JWT 服务端吊销（v3.1.9 VULN-007）。

无状态 JWT 默认无法主动失效，登出后 token 在过期前仍可重放。
本模块基于 Redis 维护 ``jti`` 黑名单：

- 有 Redis（``REDIS_URL`` 可达）：登出写入 ``zhycms:jwt:blacklist:<jti>``，
  TTL 为 token 剩余有效期，到期自动清理；
- 无 Redis：不启用黑名单，依赖短期 access token（默认 15 分钟）；
- Redis 运行期故障：查询/写入均降级放行或跳过，只告警，不抛 500。
"""
import logging

from flask import current_app

logger = logging.getLogger(__name__)

KEY_PREFIX = 'zhycms:jwt:blacklist:'


def _client():
    """返回启动时注入的 Redis 客户端；未启用黑名单时为 None。"""
    return current_app.config.get('JWT_BLOCKLIST_REDIS')


def is_enabled():
    """当前是否启用服务端吊销。"""
    return _client() is not None


def revoke(jti, expires_in):
    """把 jti 写入黑名单，expires_in 为剩余秒数。返回是否写入成功。"""
    client = _client()
    if client is None or not jti:
        return False
    try:
        ttl = max(int(expires_in or 0), 1)
        client.setex(KEY_PREFIX + str(jti), ttl, '1')
        return True
    except Exception as e:  # noqa: BLE001 Redis 故障不得影响登出接口
        logger.warning('JWT 黑名单写入失败（已跳过）：%s', e)
        return False


def is_revoked(jti):
    """判断 jti 是否已被吊销；Redis 故障时降级放行并告警。"""
    client = _client()
    if client is None or not jti:
        return False
    try:
        return bool(client.exists(KEY_PREFIX + str(jti)))
    except Exception as e:  # noqa: BLE001 Redis 故障不得导致接口 500
        logger.warning('JWT 黑名单查询失败，本次降级放行：%s', e)
        return False
