"""异常处理测试：403/404/500 三协议分发。"""
import pytest


@pytest.mark.errors
class TestErrorHandlers:

    def test_frontend_404(self, client):
        """前台 404 返回主题模板。"""
        resp = client.get('/nonexistent-page-12345')
        assert resp.status_code == 404
        assert 'text/html' in resp.content_type

    def test_admin_404_returns_html(self, admin_client):
        """后台不存在的页面返回 404。"""
        resp = admin_client.get('/admin/articles/99999/edit')
        assert resp.status_code == 404
        assert 'text/html' in resp.content_type

    def test_api_404_returns_json(self, client):
        """API 404 返回 JSON。"""
        resp = client.get('/api/v1/articles/999999')
        assert resp.status_code == 404
        assert 'application/json' in resp.content_type
        data = resp.get_json()
        assert data.get('code') == 404

    def test_403_when_no_permission(self, app):
        """已登录但无权限返回 403（独立验证）。"""
        from app.extensions import db
        from app.models.user import User

        with app.app_context():
            user = User(username='noperm_err', is_super=False, is_deleted=False)
            user.set_password('nopass')
            db.session.add(user)
            db.session.commit()
            uid = str(user.id)

            with app.test_client() as c:
                with c.session_transaction() as sess:
                    sess['_user_id'] = uid
                    sess['_fresh'] = True
                resp = c.get('/admin/users')
                assert resp.status_code == 403
                assert 'text/html' in resp.content_type
