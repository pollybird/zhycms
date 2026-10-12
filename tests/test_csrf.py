"""CSRF 同步 Token 防护测试（v3.1.1，GitCode issue #1 H2）。

覆盖：
  - 前台页面渲染 csrf-token meta 且写入 Session
  - 已建立 Session Token 后，无 Token/错误 Token 的 POST → 403
  - 表单字段 _csrf_token 与请求头 X-CSRF-Token 均可通校验
  - /api/* 豁免（头鉴权无 Cookie CSRF 风险）
  - Session 尚无 Token 的首个匿名 POST（如登录表单首次提交）放行
"""
import re

import pytest

csrf = pytest.mark.csrf

# 从 meta 标签提取 Token
_META_RE = re.compile(r'name="csrf-token" content="([^"]+)"')


def _token_from_page(client):
    """GET 首页建立 Session Token，返回页面 meta 中的 Token。"""
    resp = client.get('/')
    assert resp.status_code == 200
    m = _META_RE.search(resp.get_data(as_text=True))
    assert m, '页面未渲染 csrf-token meta'
    return m.group(1)


@csrf
class TestCSRF:

    @pytest.fixture
    def raw_client(self, app):
        """裸客户端：无 conftest 的自动 Token 附加，用于验证校验行为。"""
        return app.test_client()

    def test_meta_renders_and_token_stable(self, raw_client):
        """首页渲染 csrf-token meta，且同会话内 Token 稳定复用。"""
        t1 = _token_from_page(raw_client)
        t2 = _token_from_page(raw_client)
        assert t1 and t1 == t2

    def test_post_without_token_403(self, raw_client):
        """Session 已有 Token 的 POST 缺失字段/头 → 403。"""
        _token_from_page(raw_client)
        resp = raw_client.post('/admin/login', data={'username': 'x', 'password': 'y'})
        assert resp.status_code == 403

    def test_post_with_wrong_token_403(self, raw_client):
        """错误 Token → 403。"""
        _token_from_page(raw_client)
        resp = raw_client.post('/admin/login', data={
            'username': 'x', 'password': 'y', '_csrf_token': 'wrong'})
        assert resp.status_code == 403

    def test_post_with_form_token_passes(self, raw_client):
        """表单字段携带正确 Token → CSRF 放行（登录校验另行失败）。"""
        token = _token_from_page(raw_client)
        resp = raw_client.post('/admin/login', data={
            'username': 'nosuch', 'password': 'nope', '_csrf_token': token})
        assert resp.status_code != 403

    def test_post_with_header_token_passes(self, raw_client):
        """X-CSRF-Token 头携带正确 Token → CSRF 放行。"""
        token = _token_from_page(raw_client)
        resp = raw_client.post('/admin/login',
                               data={'username': 'nosuch', 'password': 'nope'},
                               headers={'X-CSRF-Token': token})
        assert resp.status_code != 403

    def test_first_anonymous_post_allowed(self, raw_client):
        """Session 尚无 Token 的首个 POST（如登录表单首次提交）放行。"""
        resp = raw_client.post('/admin/login', data={'username': 'x', 'password': 'y'})
        assert resp.status_code != 403

    def test_api_post_exempt_from_csrf(self, raw_client):
        """/api/* 使用头鉴权，无 Cookie CSRF 风险，豁免校验。"""
        resp = raw_client.post('/api/v1/auth/login',
                               json={'username': 'nosuch', 'password': 'nope'})
        assert resp.status_code != 403

    def test_get_requests_unaffected(self, raw_client):
        """GET 请求不做 CSRF 校验。"""
        assert raw_client.get('/').status_code == 200
        assert raw_client.get('/admin/login').status_code == 200

    # ---- v3.1.1a 回归：独立模板（不继承 base）的表单页 ----

    def test_login_page_renders_csrf_meta(self, raw_client):
        """登录页为独立模板，必须渲染 csrf-token meta（否则二次提交 403）。"""
        resp = raw_client.get('/admin/login')
        assert resp.status_code == 200
        assert _META_RE.search(resp.get_data(as_text=True)), \
            'login.html 未渲染 csrf-token meta'

    def test_login_retry_not_blocked_by_csrf(self, raw_client):
        """复现线上 bug：验证码输错一次（产生 Session Token）后，
        再次提交登录必须仍可携带 Token 通过 CSRF 校验。"""
        resp = raw_client.get('/admin/login')
        token = _META_RE.search(resp.get_data(as_text=True)).group(1)

        # 第一次提交：验证码错误（服务端渲染登录页，同时把 Token 写入 Session）
        resp1 = raw_client.post('/admin/login', data={
            'username': 'admin', 'password': 'x', 'captcha': '0000',
            '_csrf_token': token})
        assert resp1.status_code != 403

        # 第二次提交（此前独立登录页无 meta + 无注入脚本，必然 403）
        resp2 = raw_client.post('/admin/login', data={
            'username': 'admin', 'password': 'x', 'captcha': '0000',
            '_csrf_token': token})
        assert resp2.status_code != 403

    def test_setup_page_contains_csrf_meta(self):
        """初始化页同为独立模板，模板必须包含 csrf meta 与脚本。"""
        html = open('app/admin/templates/admin/setup.html',
                    encoding='utf-8').read()
        assert 'csrf-token' in html and 'js/csrf.js' in html
