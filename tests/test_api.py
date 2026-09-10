"""REST API 测试：响应结构、Token 鉴权。"""
import pytest


@pytest.mark.api
class TestAPI:

    def test_api_site_info(self, client):
        """站点信息 API 可访问。"""
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
