"""v3.3.0 信创适配：openAMDC 运行态识别单元测试。

覆盖：
  - INFO server 解析 openAMDC / Redis / unknown
  - 启动时 _resolve_redis_url 写入后端类型与版本
  - Redis 不可达时保持回退 SimpleCache 且不抛错
  - check_runtime 暴露 redis_flavor
  - healthz 详情模式输出 redis_flavor（openamdc / redis / disabled）
  - 后台 Redis 设置页展示后端类型与版本
"""
import json

import app as app_pkg
from app.services import redis_backend
from app.services.runtime_guard import check_runtime


class _FakeClient:
    def __init__(self, info=None, ping=True, info_error=None):
        self._info = info or {}
        self._ping = ping
        self._info_error = info_error

    def ping(self):
        if isinstance(self._ping, Exception):
            raise self._ping
        return self._ping

    def info(self, section=None):
        if self._info_error:
            raise self._info_error
        return dict(self._info)


class _NoSectionClient:
    """不支持 info(section=...) 的客户端，用于验证回退分支。"""

    def info(self):
        return {'redis_version': '7.2.4'}


class TestDescribe:
    def test_openamdc(self):
        client = _FakeClient({'openamdc_version': '1.0.0'})
        assert redis_backend.describe(client) == {
            'flavor': 'openamdc', 'version': '1.0.0'}
        assert redis_backend.detect_flavor(client) == 'openamdc'

    def test_redis(self):
        client = _FakeClient({'redis_version': '7.2.4'})
        assert redis_backend.describe(client) == {
            'flavor': 'redis', 'version': '7.2.4'}

    def test_openamdc_takes_priority(self):
        client = _FakeClient({
            'openamdc_version': '1.0.0', 'redis_version': '6.2.0'})
        assert redis_backend.detect_flavor(client) == 'openamdc'

    def test_unknown_without_version_fields(self):
        assert redis_backend.describe(_FakeClient({'tcp_port': '6379'})) == {
            'flavor': 'unknown', 'version': None}

    def test_info_without_section_support(self):
        assert redis_backend.detect_flavor(_NoSectionClient()) == 'redis'

    def test_info_exception_returns_unknown(self):
        client = _FakeClient(info_error=RuntimeError('boom'))
        assert redis_backend.describe(client) == {
            'flavor': 'unknown', 'version': None}


class TestResolveRedisUrl:
    def _restore(self, app, old_flavor, old_version):
        app.config['ZHYCMS_REDIS_FLAVOR'] = old_flavor
        app.config['ZHYCMS_REDIS_VERSION'] = old_version

    def test_openamdc_recorded(self, app, monkeypatch):
        old = (app.config.get('ZHYCMS_REDIS_FLAVOR'),
               app.config.get('ZHYCMS_REDIS_VERSION'))
        monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1:6390/0')
        monkeypatch.setattr(
            'redis.from_url',
            lambda *a, **kw: _FakeClient({'openamdc_version': '1.0.0'}))
        try:
            assert app_pkg._resolve_redis_url(app) == 'redis://127.0.0.1:6390/0'
            assert app.config['ZHYCMS_REDIS_FLAVOR'] == 'openamdc'
            assert app.config['ZHYCMS_REDIS_VERSION'] == '1.0.0'
        finally:
            self._restore(app, *old)

    def test_redis_recorded(self, app, monkeypatch):
        old = (app.config.get('ZHYCMS_REDIS_FLAVOR'),
               app.config.get('ZHYCMS_REDIS_VERSION'))
        monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
        monkeypatch.setattr(
            'redis.from_url',
            lambda *a, **kw: _FakeClient({'redis_version': '7.2.4'}))
        try:
            assert app_pkg._resolve_redis_url(app) is not None
            assert app.config['ZHYCMS_REDIS_FLAVOR'] == 'redis'
            assert app.config['ZHYCMS_REDIS_VERSION'] == '7.2.4'
        finally:
            self._restore(app, *old)

    def test_unreachable_falls_back(self, app, monkeypatch):
        old = (app.config.get('ZHYCMS_REDIS_FLAVOR'),
               app.config.get('ZHYCMS_REDIS_VERSION'))
        monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1:6391/0')
        monkeypatch.setattr(
            'redis.from_url',
            lambda *a, **kw: _FakeClient(ping=ConnectionError('refused')))
        try:
            assert app_pkg._resolve_redis_url(app) is None
            assert app.config['ZHYCMS_REDIS_FLAVOR'] is None
            assert app.config['ZHYCMS_REDIS_VERSION'] is None
        finally:
            self._restore(app, *old)

    def test_unconfigured_clears_flavor(self, app, monkeypatch):
        old = (app.config.get('ZHYCMS_REDIS_FLAVOR'),
               app.config.get('ZHYCMS_REDIS_VERSION'))
        monkeypatch.delenv('REDIS_URL', raising=False)
        try:
            assert app_pkg._resolve_redis_url(app) is None
            assert app.config['ZHYCMS_REDIS_FLAVOR'] is None
        finally:
            self._restore(app, *old)


def test_check_runtime_reports_openamdc(app, monkeypatch):
    old_info = app.config.get('ZHYCMS_RUNTIME_INFO')
    old_warn = app.config.get('ZHYCMS_RUNTIME_WARNING')
    monkeypatch.setitem(app.config, 'ZHYCMS_REDIS_ACTIVE', True)
    monkeypatch.setitem(app.config, 'ZHYCMS_REDIS_FLAVOR', 'openamdc')
    try:
        info = check_runtime(app)
        assert info['redis'] is True
        assert info['redis_flavor'] == 'openamdc'
    finally:
        app.config['ZHYCMS_RUNTIME_INFO'] = old_info
        app.config['ZHYCMS_RUNTIME_WARNING'] = old_warn


def test_check_runtime_disabled_flavor(app, monkeypatch):
    old_info = app.config.get('ZHYCMS_RUNTIME_INFO')
    old_warn = app.config.get('ZHYCMS_RUNTIME_WARNING')
    monkeypatch.setitem(app.config, 'ZHYCMS_REDIS_ACTIVE', False)
    monkeypatch.setitem(app.config, 'ZHYCMS_REDIS_FLAVOR', None)
    try:
        info = check_runtime(app)
        assert info['redis'] is False
        assert info['redis_flavor'] == 'disabled'
    finally:
        app.config['ZHYCMS_RUNTIME_INFO'] = old_info
        app.config['ZHYCMS_RUNTIME_WARNING'] = old_warn


def _healthz(client):
    resp = client.get('/healthz?detail=1')
    assert resp.status_code == 200
    return json.loads(resp.get_data(as_text=True))


def test_healthz_openamdc_flavor(app, client, monkeypatch):
    monkeypatch.setitem(
        app.config, 'JWT_BLOCKLIST_REDIS',
        _FakeClient({'openamdc_version': '1.0.0'}))
    monkeypatch.setitem(app.config, 'ZHYCMS_REDIS_FLAVOR', 'openamdc')
    payload = _healthz(client)
    assert payload['redis'] == 'ok'
    assert payload['redis_flavor'] == 'openamdc'


def test_healthz_redis_flavor(app, client, monkeypatch):
    monkeypatch.setitem(
        app.config, 'JWT_BLOCKLIST_REDIS',
        _FakeClient({'redis_version': '7.2.4'}))
    monkeypatch.setitem(app.config, 'ZHYCMS_REDIS_FLAVOR', 'redis')
    payload = _healthz(client)
    assert payload['redis'] == 'ok'
    assert payload['redis_flavor'] == 'redis'


def test_healthz_disabled_flavor(app, client, monkeypatch):
    monkeypatch.setitem(app.config, 'JWT_BLOCKLIST_REDIS', None)
    monkeypatch.setitem(app.config, 'ZHYCMS_REDIS_FLAVOR', None)
    payload = _healthz(client)
    assert payload['redis'] == 'disabled'
    assert payload['redis_flavor'] == 'disabled'


def test_healthz_detects_flavor_when_config_missing(app, client, monkeypatch):
    monkeypatch.setitem(
        app.config, 'JWT_BLOCKLIST_REDIS',
        _FakeClient({'openamdc_version': '1.0.0'}))
    monkeypatch.setitem(app.config, 'ZHYCMS_REDIS_FLAVOR', None)
    payload = _healthz(client)
    assert payload['redis'] == 'ok'
    assert payload['redis_flavor'] == 'openamdc'


def test_admin_redis_page_shows_openamdc(app, admin_client, monkeypatch):
    monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1:6390/0')
    monkeypatch.setattr(
        'redis.from_url',
        lambda *a, **kw: _FakeClient({'openamdc_version': '1.0.0'}))
    resp = admin_client.get('/admin/settings/redis')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'openAMDC' in body
    assert '1.0.0' in body


def test_admin_redis_page_shows_redis(app, admin_client, monkeypatch):
    monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
    monkeypatch.setattr(
        'redis.from_url',
        lambda *a, **kw: _FakeClient({'redis_version': '7.2.4'}))
    resp = admin_client.get('/admin/settings/redis')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Redis' in body
    assert '7.2.4' in body
