"""冒烟测试：应用启动、健康检查、首页、未登录跳转。"""
import pytest


@pytest.mark.smoke
class TestSmoke:

    def test_app_creates(self, app):
        assert app is not None
        assert app.config['TESTING'] is True

    def test_healthz(self, client):
        """Docker 健康检查端点不需登录。"""
        resp = client.get('/healthz')
        assert resp.status_code == 200

    def test_home_page(self, client):
        """首页 200 或 302（未初始化时跳转向导）。"""
        resp = client.get('/')
        assert resp.status_code in (200, 302)

    def test_admin_redirects_unauthenticated(self, client):
        """未登录访问后台应跳转登录页。"""
        resp = client.get('/admin/')
        assert resp.status_code == 302
        assert '/login' in resp.headers.get('Location', '')

    def test_404_page(self, client):
        """不存在的路径返回 404。"""
        resp = client.get('/this-page-does-not-exist-12345')
        assert resp.status_code == 404
