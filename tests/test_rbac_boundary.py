"""RBAC 栏目级权限边界测试（v2.6.2 W1）。

覆盖 permission_required 装饰器的栏目专属权限路径：
- 权限矩阵：{有/无 content:edit} × {有/无栏目授权}
- column_id_arg 的 kwargs / query 参数两条取值路径
- any_of 备用权限放行
- 被禁用账号登出跳转、超管绕过
- can_access_column / column_flag 模型方法
"""
import uuid

import pytest
from werkzeug.exceptions import Forbidden

from tests.factories import make_user, make_column

boundary = pytest.mark.boundary


def _login(client, uid):
    """把指定 user id 注入 session（绕验证码，同 conftest admin_client 手法）。"""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True
    return client


def _editor(columns=None, perm_role='content_editor',
            can_review=False, can_publish=False):
    """在当前 app context 创建角色用户并可选授权栏目；返回 user.id。

    注意：columns 中的 UserColumnPermission 需要调用方持有栏目 id
    （本函数内 commit），栏目对象须在同一 app context 内先建好。
    """
    from app.extensions import db
    from app.models.rbac import Role, UserColumnPermission

    user = make_user(username='ed_' + uuid.uuid4().hex[:8],
                     role=Role.get_by_code(perm_role))
    for cid in (columns or []):
        db.session.add(UserColumnPermission(
            user_id=user.id, column_id=cid,
            can_review=can_review, can_publish=can_publish))
    db.session.commit()
    return user.id


@boundary
class TestColumnAccessModel:
    """can_access_column / get_allowed_column_ids 模型层边界。"""

    def test_super_allows_any_column(self, app):
        """超管不限制栏目。"""
        from app.models.user import User
        with app.app_context():
            admin = User.query.filter_by(username='admin').first()
            assert admin.can_access_column(99999) is True

    def test_all_columns_perm_allows_any_column(self, app):
        """content_manage:all_columns 全局权限不限制栏目（审核员预设含此权限）。"""
        from app.extensions import db
        from app.models.rbac import Role
        with app.app_context():
            user = make_user(username='ac_' + uuid.uuid4().hex[:8],
                             role=Role.get_by_code('content_auditor'))
            db.session.commit()
            assert user.can_access_column(99999) is True

    def test_editor_without_grant_denied_any_column(self, app):
        """编辑有 content:edit 但未绑定任何栏目 → 任何栏目都拒绝。"""
        from app.extensions import db
        from app.models.rbac import Role
        with app.app_context():
            user = make_user(username='ed_' + uuid.uuid4().hex[:8],
                             role=Role.get_by_code('content_editor'))
            db.session.commit()
            assert user.get_allowed_column_ids() == set()
            assert user.can_access_column(1) is False

    def test_editor_grant_isolated_per_column(self, app):
        """编辑仅授权栏目 A：A 放行、B 拒绝。"""
        from app.extensions import db
        from app.models.rbac import Role, UserColumnPermission
        with app.app_context():
            col_a = make_column(name='授权栏目', slug='g-' + uuid.uuid4().hex[:8])
            col_b = make_column(name='未授权栏目', slug='n-' + uuid.uuid4().hex[:8])
            user = make_user(username='ed_' + uuid.uuid4().hex[:8],
                             role=Role.get_by_code('content_editor'))
            db.session.add(UserColumnPermission(
                user_id=user.id, column_id=col_a.id))
            db.session.commit()
            assert user.can_access_column(col_a.id) is True
            assert user.can_access_column(col_b.id) is False


@boundary
class TestColumnFlag:
    """栏目级 can_review / can_publish 标志优先级。"""

    def test_row_flag_overrides_role(self, app):
        """存在授权行时按行标志判定（可覆盖角色默认）。"""
        from app.extensions import db
        from app.models.rbac import Role, UserColumnPermission
        with app.app_context():
            col = make_column(name='审核栏目', slug='r-' + uuid.uuid4().hex[:8])
            user = make_user(username='ed_' + uuid.uuid4().hex[:8],
                             role=Role.get_by_code('content_editor'))
            db.session.add(UserColumnPermission(
                user_id=user.id, column_id=col.id,
                can_review=True, can_publish=False))
            db.session.commit()
            assert user.column_flag('can_review', col.id) is True
            assert user.column_flag('can_publish', col.id) is False

    def test_no_row_falls_back_to_role_perm(self, app):
        """无授权行时回退角色全局权限判定（编辑无 all_columns → False）。"""
        from app.extensions import db
        from app.models.rbac import Role
        with app.app_context():
            col = make_column(name='回退栏目', slug='f-' + uuid.uuid4().hex[:8])
            user = make_user(username='ed_' + uuid.uuid4().hex[:8],
                             role=Role.get_by_code('content_editor'))
            db.session.commit()
            assert user.column_flag('can_review', col.id) is False


@boundary
class TestRouteBoundary:
    """路由级边界：栏目专属权限 200/403。"""

    def test_editor_with_grant_lists_articles(self, app, client):
        """编辑 + 栏目授权 → 栏目文章列表 200。"""
        with app.app_context():
            col = make_column(name='列表栏目', slug='l-' + uuid.uuid4().hex[:8])
            from app.extensions import db
            db.session.commit()
            cid, uid = col.id, _editor(columns=[col.id])
        _login(client, uid)
        assert client.get(f'/admin/columns/{cid}/articles').status_code == 200

    def test_editor_without_grant_forbidden(self, app, client):
        """编辑有 content:edit 但无栏目授权 → 403。"""
        with app.app_context():
            col = make_column(name='无权栏目', slug='x-' + uuid.uuid4().hex[:8])
            from app.extensions import db
            db.session.commit()
            cid, uid = col.id, _editor(columns=None)
        _login(client, uid)
        assert client.get(f'/admin/columns/{cid}/articles').status_code == 403

    def test_editor_grant_does_not_leak_other_column(self, app, client):
        """编辑仅授权 A：访问 A 200、访问 B 403（栏目隔离）。"""
        with app.app_context():
            from app.extensions import db
            col_a = make_column(name='甲栏目', slug='a-' + uuid.uuid4().hex[:8])
            col_b = make_column(name='乙栏目', slug='b-' + uuid.uuid4().hex[:8])
            db.session.commit()
            aid, bid = col_a.id, col_b.id
            uid = _editor(columns=[col_a.id])
        _login(client, uid)
        assert client.get(f'/admin/columns/{aid}/articles').status_code == 200
        assert client.get(f'/admin/columns/{bid}/articles').status_code == 403

    def test_superuser_bypasses_column_check(self, app, admin_client):
        """超管无任何栏目授权也直接放行。"""
        with app.app_context():
            col = make_column(name='超管栏目', slug='s-' + uuid.uuid4().hex[:8])
            from app.extensions import db
            db.session.commit()
            cid = col.id
        assert admin_client.get(f'/admin/columns/{cid}/articles').status_code == 200

    def test_missing_content_edit_forbidden(self, app, client):
        """连 content:edit 都没有的用户（只读角色）→ 403。"""
        with app.app_context():
            col = make_column(name='只读栏目', slug='ro-' + uuid.uuid4().hex[:8])
            from app.extensions import db
            db.session.commit()
            cid, uid = col.id, _editor(perm_role='readonly_viewer')
        _login(client, uid)
        assert client.get(f'/admin/columns/{cid}/articles').status_code == 403


@boundary
class TestDecoratorPaths:
    """permission_required 装饰器取值路径（kwargs 缺省时回退 query 参数）。"""

    def _make_view(self):
        from app.utils.helpers import permission_required

        @permission_required('content:edit', column_id_arg='cid')
        def view(cid=None):  # noqa: 恒空实现，仅验证装饰器门控行为
            return 'ok'
        return view

    def test_column_id_from_query_param_denied(self, app):
        """cid 经 query 参数传入（kwargs 缺省路径）：未授权 → 403。"""
        from app.extensions import db
        from app.models.rbac import Role
        from flask_login import login_user
        with app.app_context():
            col = make_column(name='查询参数栏目', slug='q-' + uuid.uuid4().hex[:8])
            user = make_user(username='ed_' + uuid.uuid4().hex[:8],
                             role=Role.get_by_code('content_editor'))
            db.session.commit()
            view = self._make_view()
            with app.test_request_context(f'/?cid={col.id}'):
                login_user(user)
                with pytest.raises(Forbidden):
                    view()

    def test_column_id_from_query_param_allowed(self, app):
        """cid 经 query 参数传入：已授权栏目 → 放行。"""
        from app.extensions import db
        from app.models.rbac import Role, UserColumnPermission
        from flask_login import login_user
        with app.app_context():
            col = make_column(name='查询放行栏目', slug='qp-' + uuid.uuid4().hex[:8])
            user = make_user(username='ed_' + uuid.uuid4().hex[:8],
                             role=Role.get_by_code('content_editor'))
            db.session.add(UserColumnPermission(user_id=user.id, column_id=col.id))
            db.session.commit()
            view = self._make_view()
            with app.test_request_context(f'/?cid={col.id}'):
                login_user(user)
                assert view() == 'ok'


@boundary
class TestAnyOf:
    """any_of 备用权限：栏目列表页对内容编辑开放浏览。"""

    def test_editor_any_of_sees_only_granted_columns(self, app, client):
        """编辑（无 column:manage）经 any_of 进入栏目列表 → 200 且只见授权栏目。"""
        with app.app_context():
            from app.extensions import db
            col_a = make_column(name='可见栏目甲', slug='vis-' + uuid.uuid4().hex[:8])
            col_b = make_column(name='隐藏栏目乙', slug='hid-' + uuid.uuid4().hex[:8])
            db.session.commit()
            uid = _editor(columns=[col_a.id])
            name_a, name_b = col_a.name, col_b.name
        _login(client, uid)
        resp = client.get('/admin/columns')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert name_a in html
        assert name_b not in html

    def test_viewer_without_any_content_perm_forbidden(self, app, client):
        """只读角色（form:view）无任何 content 权限 → 栏目列表 403。"""
        with app.app_context():
            uid = _editor(perm_role='readonly_viewer')
        _login(client, uid)
        assert client.get('/admin/columns').status_code == 403


@boundary
class TestDisabledAccount:
    """被禁用/已删除账号：装饰器强制登出并跳转登录页。"""

    def test_disabled_user_logged_out(self, app, client):
        """is_active_flag=False 的账号访问后台 → 302 到登录页。"""
        from app.extensions import db
        with app.app_context():
            user = make_user(username='dis_' + uuid.uuid4().hex[:8])
            user.is_active_flag = False
            db.session.commit()
            uid = user.id
        _login(client, uid)
        resp = client.get('/admin/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers.get('Location', '')

    def test_deleted_user_logged_out(self, app, client):
        """is_deleted=True 的账号残留 session 同样被登出。"""
        from app.extensions import db
        with app.app_context():
            user = make_user(username='del_' + uuid.uuid4().hex[:8])
            user.is_deleted = True
            db.session.commit()
            uid = user.id
        _login(client, uid)
        resp = client.get('/admin/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers.get('Location', '')
