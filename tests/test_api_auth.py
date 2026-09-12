"""REST API 鉴权测试（v2.6.3）：JWT 登录 / 刷新 / 双轨兼容 / 速率限制。"""
import pytest


@pytest.mark.api
class TestAPIAuth:

    @pytest.fixture(autouse=True)
    def _reset_limiter(self, app):
        """每个用例前重置速率限制计数器，避免跨用例污染。"""
        with app.app_context():
            from app.extensions import limiter
            try:
                limiter.reset()
            except Exception:
                pass
        yield
        with app.app_context():
            from app.extensions import limiter
            try:
                limiter.reset()
            except Exception:
                pass

    def _set_mode(self, app, mode):
        with app.app_context():
            from app.models.setting import Setting
            from app.extensions import db
            Setting.set('api_auth_mode', mode)
            db.session.commit()

    def test_login_success_returns_jwt(self, client, app):
        """正确用户名密码登录返回 access_token + refresh_token。"""
        with app.app_context():
            from app.models.user import User
            from app.extensions import db
            user = User(username='jwt_test_user', is_super=False, is_deleted=False)
            user.set_password('pass123456')
            db.session.add(user)
            db.session.commit()

        resp = client.post('/api/v1/auth/login',
                           json={'username': 'jwt_test_user', 'password': 'pass123456'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['code'] == 0
        assert 'access_token' in data['data']
        assert 'refresh_token' in data['data']
        assert data['data']['token_type'] == 'Bearer'

    def test_login_wrong_password(self, client):
        """错误密码返回 401。"""
        resp = client.post('/api/v1/auth/login',
                           json={'username': 'admin', 'password': 'wrong'})
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        """缺少用户名或密码返回 400。"""
        resp = client.post('/api/v1/auth/login', json={'username': 'admin'})
        assert resp.status_code == 400

    def test_jwt_access_protected_endpoint(self, client, app):
        """携带 JWT access_token 可访问受保护端点。"""
        self._set_mode(app, 'both')
        with app.app_context():
            from app.models.user import User
            from app.extensions import db
            user = User(username='jwt_protected_user', is_super=False, is_deleted=False)
            user.set_password('pass123456')
            db.session.add(user)
            db.session.commit()

        resp = client.post('/api/v1/auth/login',
                           json={'username': 'jwt_protected_user', 'password': 'pass123456'})
        access_token = resp.get_json()['data']['access_token']

        resp2 = client.get('/api/v1/columns',
                           headers={'Authorization': f'Bearer {access_token}'})
        assert resp2.status_code == 200

    def test_logout_returns_ok(self, client):
        """logout 端点返回成功（无状态 JWT 由客户端删除 token）。"""
        resp = client.post('/api/v1/auth/logout')
        assert resp.status_code == 200
        assert resp.get_json()['code'] == 0

    def test_both_mode_accepts_jwt_and_token(self, client, app):
        """both 模式：JWT 与 X-API-Token 均可访问受保护端点。"""
        self._set_mode(app, 'both')
        with app.app_context():
            from app.models.setting import Setting
            token = Setting.get('api_token')
            from app.models.user import User
            from app.extensions import db
            user = User(username='both_mode_user', is_super=False, is_deleted=False)
            user.set_password('pass123456')
            db.session.add(user)
            db.session.commit()

        # X-API-Token 方式
        if token:
            resp = client.get('/api/v1/columns', headers={'X-API-Token': token})
            assert resp.status_code == 200

        # JWT 方式
        resp_login = client.post('/api/v1/auth/login',
                                 json={'username': 'both_mode_user', 'password': 'pass123456'})
        access_token = resp_login.get_json()['data']['access_token']
        resp2 = client.get('/api/v1/columns',
                           headers={'Authorization': f'Bearer {access_token}'})
        assert resp2.status_code == 200

    def test_jwt_mode_rejects_token(self, client, app):
        """jwt 模式：X-API-Token 被拒绝，仅 JWT 可访问。"""
        self._set_mode(app, 'jwt')
        with app.app_context():
            from app.models.setting import Setting
            token = Setting.get('api_token')
            from app.models.user import User
            from app.extensions import db
            user = User(username='jwt_only_user', is_super=False, is_deleted=False)
            user.set_password('pass123456')
            db.session.add(user)
            db.session.commit()

        # X-API-Token 应被拒绝
        if token:
            resp = client.get('/api/v1/columns', headers={'X-API-Token': token})
            assert resp.status_code in (401, 403)

        # JWT 可访问
        resp_login = client.post('/api/v1/auth/login',
                                 json={'username': 'jwt_only_user', 'password': 'pass123456'})
        access_token = resp_login.get_json()['data']['access_token']
        resp2 = client.get('/api/v1/columns',
                           headers={'Authorization': f'Bearer {access_token}'})
        assert resp2.status_code == 200

        self._set_mode(app, 'both')

    def test_token_mode_rejects_jwt(self, client, app):
        """token 模式：JWT 被拒绝，仅 X-API-Token 可访问。"""
        self._set_mode(app, 'token')
        with app.app_context():
            from app.models.setting import Setting
            from app.extensions import db
            # 配置一个 api_token，确保 _check_api_token 不会免鉴权
            Setting.set('api_token', 'test-token-for-token-mode')
            db.session.commit()
            token = Setting.get('api_token')
            from app.models.user import User
            user = User(username='token_only_user', is_super=False, is_deleted=False)
            user.set_password('pass123456')
            db.session.add(user)
            db.session.commit()

        # 获取一个 JWT
        resp_login = client.post('/api/v1/auth/login',
                                 json={'username': 'token_only_user', 'password': 'pass123456'})
        access_token = resp_login.get_json()['data']['access_token']

        # JWT 应被拒绝（token 模式下走 _check_api_token，无 X-API-Token 头则 401）
        resp = client.get('/api/v1/columns',
                          headers={'Authorization': f'Bearer {access_token}'})
        assert resp.status_code in (401, 403)

        # X-API-Token 可访问
        resp2 = client.get('/api/v1/columns', headers={'X-API-Token': token})
        assert resp2.status_code == 200

        # 清理：恢复 api_token 为空，避免污染其他测试
        with app.app_context():
            from app.models.setting import Setting
            from app.extensions import db
            Setting.set('api_token', '')
            db.session.commit()
        self._set_mode(app, 'both')

    def test_login_rate_limit(self, client):
        """登录端点触发速率限制返回 429。"""
        statuses = set()
        for _ in range(20):
            resp = client.post('/api/v1/auth/login',
                               json={'username': 'nouser', 'password': 'nope'})
            statuses.add(resp.status_code)
        assert 429 in statuses
