"""运行形态自检（v3.2.10）。

多 worker / 多实例部署下，缓存、会话、限流、调度与浏览量合并都依赖
共享后端。本模块只做只读判断与告警，不主动连接 Redis、不改变业务行为；
需要强一致的部署可通过 ``ZHYCMS_REQUIRE_REDIS=1`` 要求启动时拒绝降级。
"""
import os

from flask import current_app


def _truthy(raw):
    return str(raw or '').strip().lower() in ('1', 'true', 'on', 'yes')


def worker_count():
    """读取 gunicorn / uwsgi 的 worker 数；无法判断时按单进程处理。"""
    raw = os.environ.get('GUNICORN_WORKERS') or os.environ.get('WEB_CONCURRENCY')
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def configure_redis_backends(app, redis_url):
    """按 Redis 可用性写入缓存 / 限流后端配置（供 create_app 调用）。"""
    app.config['ZHYCMS_REDIS_ACTIVE'] = bool(redis_url)
    app.config['RATELIMIT_STORAGE_URI'] = redis_url or 'memory://'
    app.config['CACHE_TYPE'] = 'RedisCache' if redis_url else 'SimpleCache'


def redis_active(app=None):
    app = app or current_app
    return bool(app.config.get('ZHYCMS_REDIS_ACTIVE'))


def scheduler_role(app=None):
    app = app or current_app
    return (app.config.get('ZHYCMS_RUNTIME_INFO') or {}).get('scheduler', 'unknown')


def set_scheduler_role(role, app=None):
    app = app or current_app
    info = dict(app.config.get('ZHYCMS_RUNTIME_INFO') or {})
    info['scheduler'] = role
    app.config['ZHYCMS_RUNTIME_INFO'] = info


def check_runtime(app):
    """汇总运行形态并写入 ``app.config['ZHYCMS_RUNTIME_INFO']``。

    多 worker 且未启用 Redis 时记录 ERROR 并设置告警文案；若显式要求
    ``ZHYCMS_REQUIRE_REDIS=1``，直接抛错拒绝启动，避免静默降级。
    """
    workers = worker_count()
    redis_ok = redis_active(app)
    cache_backend = 'redis' if app.config.get('CACHE_TYPE') == 'RedisCache' else 'simple'
    limiter_uri = str(app.config.get('RATELIMIT_STORAGE_URI') or 'memory://')
    limiter_backend = 'redis' if limiter_uri.startswith('redis') else 'memory'
    require_redis = _truthy(os.environ.get('ZHYCMS_REQUIRE_REDIS'))

    warnings = []
    if workers > 1 and not redis_ok:
        message = (
            f'检测到 {workers} 个 worker 但未启用 Redis：限流、缓存与调度锁'
            '为进程内语义，定时任务可能重复执行'
        )
        warnings.append(message)
        app.logger.error('%s。生产环境请配置 REDIS_URL', message)

    if require_redis and not redis_ok:
        raise RuntimeError(
            'ZHYCMS_REQUIRE_REDIS=1 但 Redis 不可用，拒绝以不可靠后端启动')

    redis_flavor = app.config.get('ZHYCMS_REDIS_FLAVOR')
    if not redis_flavor:
        redis_flavor = 'unknown' if redis_ok else 'disabled'

    info = {
        'workers': workers,
        'redis': redis_ok,
        'redis_flavor': redis_flavor,
        'cache_backend': cache_backend,
        'limiter_backend': limiter_backend,
        'scheduler': 'unknown',
        'warning': '；'.join(warnings),
    }
    app.config['ZHYCMS_RUNTIME_INFO'] = info
    app.config['ZHYCMS_RUNTIME_WARNING'] = info['warning']
    return info
