"""v3.2.10 多进程 / 多实例扩展回归测试。"""
import importlib.util
import json
import os

import pytest

from app.extensions import cache
from app.services import runtime_guard
from app.services.site_deploy import (
    render_site_block, render_upstream_block, resolve_upstream,
)

pytestmark = pytest.mark.security

_RUNTIME_KEYS = (
    'ZHYCMS_REDIS_ACTIVE', 'RATELIMIT_STORAGE_URI', 'CACHE_TYPE',
    'ZHYCMS_RUNTIME_INFO', 'ZHYCMS_RUNTIME_WARNING',
)


@pytest.fixture(autouse=True)
def _restore_runtime(app):
    saved = {key: app.config.get(key) for key in _RUNTIME_KEYS}
    yield
    with app.app_context():
        for key, value in saved.items():
            app.config[key] = value
        cache.delete('zhycms:sched:leader')
        cache.delete('zhycms:lock:view_flush')


def test_worker_count_reads_env(monkeypatch):
    monkeypatch.setenv('GUNICORN_WORKERS', '3')
    monkeypatch.delenv('WEB_CONCURRENCY', raising=False)
    assert runtime_guard.worker_count() == 3

    monkeypatch.setenv('GUNICORN_WORKERS', 'not-a-number')
    assert runtime_guard.worker_count() == 1


def test_configure_redis_backends(app):
    runtime_guard.configure_redis_backends(app, 'redis://127.0.0.1:6379/0')
    assert app.config['ZHYCMS_REDIS_ACTIVE'] is True
    assert app.config['RATELIMIT_STORAGE_URI'] == 'redis://127.0.0.1:6379/0'
    assert app.config['CACHE_TYPE'] == 'RedisCache'

    runtime_guard.configure_redis_backends(app, None)
    assert app.config['ZHYCMS_REDIS_ACTIVE'] is False
    assert app.config['RATELIMIT_STORAGE_URI'] == 'memory://'
    assert app.config['CACHE_TYPE'] == 'SimpleCache'


def test_runtime_guard_single_worker(app, monkeypatch):
    monkeypatch.delenv('GUNICORN_WORKERS', raising=False)
    monkeypatch.delenv('WEB_CONCURRENCY', raising=False)
    runtime_guard.configure_redis_backends(app, None)
    info = runtime_guard.check_runtime(app)
    assert info['workers'] == 1
    assert info['warning'] == ''
    assert info['limiter_backend'] == 'memory'


def test_runtime_guard_multi_worker_without_redis(app, monkeypatch):
    monkeypatch.setenv('GUNICORN_WORKERS', '4')
    runtime_guard.configure_redis_backends(app, None)
    info = runtime_guard.check_runtime(app)
    assert info['workers'] == 4
    assert info['redis'] is False
    assert '未启用 Redis' in info['warning']
    assert app.config['ZHYCMS_RUNTIME_WARNING'] == info['warning']


def test_runtime_guard_require_redis_fails(app, monkeypatch):
    monkeypatch.setenv('ZHYCMS_REQUIRE_REDIS', '1')
    runtime_guard.configure_redis_backends(app, None)
    with pytest.raises(RuntimeError):
        runtime_guard.check_runtime(app)


def test_runtime_guard_reports_redis_limiter(app):
    runtime_guard.configure_redis_backends(app, 'redis://127.0.0.1:6379/0')
    info = runtime_guard.check_runtime(app)
    assert info['limiter_backend'] == 'redis'
    assert info['cache_backend'] == 'redis'


def test_scheduler_leadership_is_exclusive(app):
    from app import _acquire_scheduler_leadership
    with app.app_context():
        token = _acquire_scheduler_leadership(app)
        assert token
        assert _acquire_scheduler_leadership(app) is None


def test_scheduler_disabled_by_env(app, monkeypatch):
    from app import _setup_scheduler
    monkeypatch.setenv('ZHYCMS_SCHEDULER_ENABLED', '0')
    assert _setup_scheduler(app) is None
    assert app.config['ZHYCMS_RUNTIME_INFO']['scheduler'] == 'disabled'


def test_scheduler_follower_skips_jobs(app, monkeypatch):
    from app import _setup_scheduler
    monkeypatch.delenv('ZHYCMS_SCHEDULER_ENABLED', raising=False)
    monkeypatch.setattr(runtime_guard, 'worker_count', lambda: 4)
    monkeypatch.setattr(runtime_guard, 'redis_active', lambda _app=None: True)
    with app.app_context():
        cache.set('zhycms:sched:leader', 'other-worker', timeout=90)
        assert _setup_scheduler(app) is None
    assert app.config['ZHYCMS_RUNTIME_INFO']['scheduler'] == 'follower'


def test_view_flush_lock_skips_concurrent(app, monkeypatch):
    from app.frontend import views as frontend_views

    called = []
    monkeypatch.setattr(frontend_views, '_flush_site_views',
                        lambda sid: called.append(sid))
    with app.app_context():
        cache.set('zhycms:lock:view_flush', '1', timeout=55)
        frontend_views._flush_view_counts()
    assert called == []


def test_view_flush_releases_lock(app, monkeypatch):
    from app.frontend import views as frontend_views
    from app.models.site import Site

    called = []
    monkeypatch.setattr(frontend_views, '_flush_site_views',
                        lambda sid: called.append(sid))
    monkeypatch.setattr(Site, 'active_sites', classmethod(lambda cls: []))
    with app.app_context():
        frontend_views._flush_view_counts()
        assert called == [0]
        assert cache.get('zhycms:lock:view_flush') is None


def test_nginx_multi_upstream_render():
    block = render_upstream_block(['127.0.0.1:5000', '127.0.0.1:5001'])
    assert 'upstream zhycms_backend' in block
    assert 'server 127.0.0.1:5000;' in block
    assert 'server 127.0.0.1:5001;' in block
    assert resolve_upstream(upstreams=['127.0.0.1:5000', '127.0.0.1:5001']) == 'zhycms_backend'

    class _Site:
        id = 0
        name = '默认站点'
        domain = None
        subdomain = None

        @property
        def is_default(self):
            return True

    content = render_site_block(
        _Site(), upstream='zhycms_backend', ssl=False, upload_max_mb=10)
    assert 'proxy_pass http://zhycms_backend;' in content
    assert 'server_name' in content


def test_healthz_default_lightweight(client):
    resp = client.get('/healthz')
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == '{"status":"ok"}'


def test_healthz_detail_fields(client):
    resp = client.get('/healthz?detail=1')
    assert resp.status_code == 200
    data = json.loads(resp.get_data(as_text=True))
    for key in ('status', 'database', 'redis', 'cache', 'limiter',
                'scheduler', 'workers', 'site', 'cms_version'):
        assert key in data
    assert data['site']['id'] == 0
    assert 'redis://' not in resp.get_data(as_text=True)


def test_bench_http_parse_args():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        'scripts', 'bench_http.py')
    spec = importlib.util.spec_from_file_location('bench_http', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    args = module.parse_args(['--url', 'http://127.0.0.1:5000/',
                              '--duration', '5', '--concurrency', '2'])
    assert args.url.endswith('/')
    assert args.concurrency == 2
    with pytest.raises(SystemExit):
        module.parse_args(['--url', 'http://127.0.0.1:5000/', '--duration', '0'])
