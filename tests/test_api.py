"""REST API 测试：响应结构、Token 鉴权。

v3.1.1 H1（fail-closed）：未配置 api_token 时所有需鉴权端点返回 401，
不再匿名放行。conftest 的 client fixture 已为每用例预置
api_token='test-api-token' 并自动附加 X-API-Token 头。
"""
import pytest

from tests.conftest import TEST_API_TOKEN


@pytest.mark.api
class TestAPI:

    def test_api_site_info(self, client):
        """站点信息 API 可访问（携带有效令牌）。"""
        resp = client.get('/api/v1/site')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert 'code' in data

    def test_api_columns(self, client):
        """栏目列表 API 可访问。"""
        resp = client.get('/api/v1/columns')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None

    def test_api_error_json(self, client):
        """API 404 返回 JSON 错误包。"""
        resp = client.get('/api/v1/articles/999999')
        assert resp.status_code == 404
        data = resp.get_json()
        assert data is not None
        assert data.get('code') == 404


@pytest.mark.api
class TestAPITokenFailClosed:
    """v3.1.1 H1：API 未配置令牌时 fail-closed（默认拒绝）。"""

    def _set_token(self, app, value):
        from app.extensions import db
        from app.models.setting import Setting
        with app.app_context():
            Setting.set('api_token', value)
            db.session.commit()

    def test_unconfigured_token_rejects_anonymous(self, app):
        """未配置令牌 + 未携带头 → 401（修复前为匿名放行）。"""
        self._set_token(app, '')
        c = app.test_client()
        resp = c.get('/api/v1/site')
        assert resp.status_code == 401
        data = resp.get_json()
        assert data['code'] == 401

    def test_unconfigured_token_rejects_provided(self, app):
        """未配置令牌但携带了任意头 → 401（不因客户端提供了值而放行）。"""
        self._set_token(app, '')
        c = app.test_client()
        resp = c.get('/api/v1/site', headers={'X-API-Token': 'anything'})
        assert resp.status_code == 401
        assert resp.get_json()['code'] == 401

    def test_wrong_token_rejected(self, client):
        """配置令牌后错误/缺失头 → 401。"""
        resp = client.get('/api/v1/site', headers={'X-API-Token': 'wrong-token'})
        assert resp.status_code == 401

    def test_missing_header_rejected(self, app):
        """配置令牌后不带头 → 401（裸客户端无自动附加）。"""
        c = app.test_client()
        resp = c.get('/api/v1/site')
        assert resp.status_code == 401

    def test_valid_token_accepted(self, client):
        """正确令牌正常访问。"""
        resp = client.get('/api/v1/site', headers={'X-API-Token': TEST_API_TOKEN})
        assert resp.status_code == 200
        assert resp.get_json()['code'] == 0
