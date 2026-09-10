"""认证与 RBAC 测试。"""
import pytest


@pytest.mark.auth
class TestAuthRBAC:

    def test_admin_dashboard_accessible_when_logged_in(self, admin_client):
        """超管登录后可访问后台首页。"""
        resp = admin_client.get('/admin/')
        assert resp.status_code == 200

    def test_logout(self, admin_client):
        """登出后跳转登录页。"""
        resp = admin_client.get('/admin/logout', follow_redirects=False)
        assert resp.status_code == 302

    def test_unauthenticated_admin_redirects(self, client):
        """未登录后台跳转登录。"""
        resp = client.get('/admin/')
        assert resp.status_code == 302
        assert '/login' in resp.headers.get('Location', '')

    def test_403_for_no_permission(self, app):
        """无权限用户访问受限页面返回 403（独立验证）。"""
        from app.extensions import db
        from app.models.user import User

        with app.app_context():
            user = User(username='noperm_user', is_super=False, is_deleted=False)
            user.set_password('nopass')
            db.session.add(user)
            db.session.commit()
            uid = str(user.id)

            # 用 test_client 在 app_context 内发起请求，避免 session 跨用例污染
            with app.test_client() as c:
                with c.session_transaction() as sess:
                    sess['_user_id'] = uid
                    sess['_fresh'] = True
                resp = c.get('/admin/users')
                assert resp.status_code == 403
