"""后台账号管理回归测试。

背景：users/form.html 模板字段名曾与 user_service 全面脱节
（password2 vs confirm_password 等），导致两次密码一致仍提示
"两次输入的密码不一致"、新增账号恒为禁用、角色无法分配。
"""
import pytest

from app.models.user import User


@pytest.mark.auth
class TestUserManage:

    def test_create_page_renders(self, admin_client):
        resp = admin_client.get('/admin/users/create')
        assert resp.status_code == 200
        assert b'confirm_password' in resp.data

    def test_create_user_password_match(self, admin_client, app):
        """两次密码一致时应创建成功（回归：曾误报不一致）。"""
        resp = admin_client.post('/admin/users/create', data={
            'username': 'creator_test',
            'password': 'abc12345',
            'confirm_password': 'abc12345',
            'nickname': '测试账号',
            'email': 't@example.com',
            'is_active_flag': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            user = User.query.filter_by(username='creator_test').first()
            assert user is not None
            assert user.is_active_flag is True
            assert user.nickname == '测试账号'
            assert user.check_password('abc12345')

    def test_create_user_password_mismatch(self, admin_client, app):
        """两次密码不一致时应拒绝创建。"""
        resp = admin_client.post('/admin/users/create', data={
            'username': 'mismatch_test',
            'password': 'abc12345',
            'confirm_password': 'abc99999',
            'is_active_flag': 'on',
        }, follow_redirects=True)
        assert '两次输入的密码不一致'.encode() in resp.data

        with app.app_context():
            assert User.query.filter_by(username='mismatch_test').first() is None

    def test_create_user_assign_role(self, admin_client, app):
        """role_ids[] 应正确绑定角色。"""
        from app.extensions import db
        from app.models.rbac import Role, UserRole

        with app.app_context():
            role = Role(code='test_um_role', name='测试角色', is_system=False)
            db.session.add(role)
            db.session.commit()
            rid = role.id

        resp = admin_client.post('/admin/users/create', data={
            'username': 'role_bind_test',
            'password': 'abc12345',
            'confirm_password': 'abc12345',
            'role_ids[]': str(rid),
            'is_active_flag': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            user = User.query.filter_by(username='role_bind_test').first()
            assert user is not None
            assert rid in user.role_ids
            assert UserRole.query.filter_by(user_id=user.id, role_id=rid).first()

    def test_edit_page_renders_with_context(self, admin_client, app):
        """编辑页应携带 RBAC 上下文正常渲染。"""
        from app.extensions import db
        from app.models.user import User

        with app.app_context():
            user = User(username='edit_render_test', is_deleted=False)
            user.set_password('abc12345')
            db.session.add(user)
            db.session.commit()
            uid = user.id

        resp = admin_client.get(f'/admin/users/{uid}/edit')
        assert resp.status_code == 200
        assert b'nickname' in resp.data

    def test_reset_password(self, admin_client, app):
        """重置密码应读取 new_password 字段并生效。"""
        from app.extensions import db
        from app.models.user import User

        with app.app_context():
            user = User(username='reset_pwd_test', is_deleted=False)
            user.set_password('old12345')
            db.session.add(user)
            db.session.commit()
            uid = user.id

        resp = admin_client.post(f'/admin/users/{uid}/reset-password',
                                 data={'new_password': 'new12345'},
                                 follow_redirects=False)
        assert resp.status_code == 302

        with app.app_context():
            assert User.query.get(uid).check_password('new12345')

    def test_non_super_cannot_grant_super(self, app):
        """非超管操作者（含 user_manage 权限）不能授予超管标志（防提权）。"""
        from app.extensions import db
        from app.models.rbac import Role, RolePermission, UserRole
        from app.models.user import User

        with app.app_context():
            role = Role(code='test_um_mgr', name='账号管理员', is_system=False)
            db.session.add(role)
            db.session.flush()
            RolePermission.ensure_for_role(role.id, ['system:user_manage'])
            manager = User(username='um_manager', is_deleted=False)
            manager.set_password('abc12345')
            db.session.add(manager)
            db.session.flush()
            db.session.add(UserRole(user_id=manager.id, role_id=role.id))
            db.session.commit()
            manager_id = str(manager.id)

        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess['_user_id'] = manager_id
                sess['_fresh'] = True
            resp = c.post('/admin/users/create', data={
                'username': 'escalation_test',
                'password': 'abc12345',
                'confirm_password': 'abc12345',
                'is_super': 'on',
                'is_active_flag': 'on',
            }, follow_redirects=True)
            assert resp.status_code == 200

        with app.app_context():
            user = User.query.filter_by(username='escalation_test').first()
            assert user is not None
            assert user.is_super is False
