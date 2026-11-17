"""v3.2.3 角色体系（站点维度）回归测试。

覆盖：
  - 预设角色：新增 site_admin，收回审核员的全局 site:manage
  - 权限求值：has_permission(site_id=...) 只认全局角色 + 本站角色
  - 站点可见性：can_access_site / accessible_sites 纳入站点级角色
  - 站点管理员：仅能在授权站点内添加/管理账号，不能进入角色配置
  - 一人多站多角色：超级管理员可为同一账号分配多个站点角色
  - 迁移 0015：user_roles.site_id 与站点化唯一约束
"""
import importlib

import pytest
import sqlalchemy as sa

from app.extensions import db

pytestmark = pytest.mark.sites

DEFAULT_SITE_ID = 0


# ============================================================
# 辅助
# ============================================================

def _mk_site(app, slug):
    from app.models.site import Site
    with app.app_context():
        site = Site(name=f'站点-{slug}', slug=slug)
        db.session.add(site)
        db.session.commit()
        return site.id


def _role_id(code):
    from app.models.rbac import Role
    role = Role.query.filter_by(code=code, is_deleted=False).first()
    assert role is not None, f'预设角色缺失：{code}'
    return role.id


def _mk_user(app, username, assignments):
    """创建账号并绑定 [(role_code, site_id_or_None), ...]。"""
    from app.models.rbac import UserRole
    from app.models.user import User
    with app.app_context():
        user = User(username=username, is_deleted=False)
        user.set_password('Abcdef123456!')
        db.session.add(user)
        db.session.flush()
        for code, sid in assignments:
            db.session.add(UserRole(
                user_id=user.id, role_id=_role_id(code), site_id=sid))
        db.session.commit()
        return user.id


def _login(client, uid):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True


def _set_site(client, sid):
    with client.session_transaction() as sess:
        sess['admin_site_id'] = sid


def _post_create(client, username, **extra):
    data = {
        'username': username,
        'password': 'Abcdef123456!',
        'confirm_password': 'Abcdef123456!',
        'is_active_flag': 'on',
    }
    data.update(extra)
    return client.post('/admin/users/create', data=data, follow_redirects=False)


@pytest.fixture(autouse=True)
def _clean_rbac3(app):
    yield
    from app.models.rbac import (
        UserColumnPermission, UserRole, UserSitePermission,
    )
    from app.models.site import Site
    from app.models.user import User
    with app.app_context():
        uids = [u.id for u in User.query.filter(
            User.username.like('rbac3-%')).all()]
        if uids:
            UserRole.query.filter(UserRole.user_id.in_(uids)).delete(
                synchronize_session=False)
            UserSitePermission.query.filter(
                UserSitePermission.user_id.in_(uids)).delete(
                synchronize_session=False)
            UserColumnPermission.query.filter(
                UserColumnPermission.user_id.in_(uids)).delete(
                synchronize_session=False)
            User.query.filter(User.id.in_(uids)).delete(
                synchronize_session=False)
        Site.query.filter(Site.slug.like('rbac3-%')).delete(
            synchronize_session=False)
        db.session.commit()


# ============================================================
# A 预设角色与权限
# ============================================================

def test_site_admin_preset_permissions(app):
    """站点管理员拥有站点内全部管理权，但不含平台级 site:manage/备份。"""
    from app.models.rbac import (
        PRESET_ROLES, PRESET_ROLE_PERMISSIONS, Role, RolePermission,
        ROLE_CONTENT_AUDITOR, ROLE_SITE_ADMIN,
    )
    assert ROLE_SITE_ADMIN in PRESET_ROLES
    codes = set(PRESET_ROLE_PERMISSIONS[ROLE_SITE_ADMIN])
    assert {'system:settings', 'system:user_manage', 'content:publish',
            'builder:publish', 'form:manage'} <= codes
    assert 'site:manage' not in codes
    assert 'system:backup' not in codes

    # v3.2.3：审核员不再拥有全局站点管理，只能访问被分配站点
    assert 'site:manage' not in set(PRESET_ROLE_PERMISSIONS[ROLE_CONTENT_AUDITOR])

    with app.app_context():
        role = Role.query.filter_by(code=ROLE_SITE_ADMIN).first()
        stored = {rp.permission_code for rp in RolePermission.query.filter_by(
            role_id=role.id).all()}
        assert 'system:user_manage' in stored
        assert 'site:manage' not in stored


# ============================================================
# B 权限求值与站点可见性
# ============================================================

def test_has_permission_scoped_by_site(app):
    sid_a = _mk_site(app, 'rbac3-a')
    sid_b = _mk_site(app, 'rbac3-b')
    uid = _mk_user(app, 'rbac3-editor', [('content_editor', sid_a)])

    from app.models.user import User
    with app.app_context():
        u = User.query.get(uid)
        assert u.has_permission('content:edit', site_id=sid_a)
        assert not u.has_permission('content:edit', site_id=sid_b)
        # site_id=None：按全部角色判断（菜单/入口可见性）
        assert u.has_permission('content:edit')
        assert u.site_scoped_role_sites() == {sid_a}
        assert u.site_role_ids(sid_b) == set()


def test_can_access_site_and_accessible_sites(app):
    sid_a = _mk_site(app, 'rbac3-a')
    sid_b = _mk_site(app, 'rbac3-b')
    uid = _mk_user(app, 'rbac3-auditor', [('content_auditor', sid_a)])

    from app.models.user import User
    from app.sites import accessible_sites, can_access_site
    with app.app_context():
        u = User.query.get(uid)
        assert can_access_site(u, sid_a)
        assert not can_access_site(u, sid_b)
        assert [s.id for s in accessible_sites(u)] == [sid_a]


def test_global_role_keeps_all_site_access(app):
    """存量全局角色（site_id IS NULL）保持全站可见。"""
    sid_a = _mk_site(app, 'rbac3-a')
    uid = _mk_user(app, 'rbac3-global', [('content_auditor', None)])

    from app.models.user import User
    from app.sites import can_access_site
    with app.app_context():
        u = User.query.get(uid)
        assert can_access_site(u, DEFAULT_SITE_ID)
        assert can_access_site(u, sid_a)


# ============================================================
# C 站点管理员的账号管理边界
# ============================================================

def test_site_admin_creates_user_in_own_site(app, client):
    sid_a = _mk_site(app, 'rbac3-a')
    admin_uid = _mk_user(app, 'rbac3-siteadmin', [('site_admin', sid_a)])
    _login(client, admin_uid)
    _set_site(client, sid_a)

    with app.app_context():
        editor_rid = _role_id('content_editor')
    resp = _post_create(client, 'rbac3-new', **{
        f'site_role_{sid_a}': str(editor_rid)})
    assert resp.status_code == 302

    from app.models.rbac import UserRole
    from app.models.user import User
    with app.app_context():
        new_user = User.query.filter_by(username='rbac3-new').first()
        assert new_user is not None
        links = UserRole.query.filter_by(user_id=new_user.id).all()
        assert len(links) == 1
        assert links[0].site_id == sid_a
        assert links[0].role.code == 'content_editor'


def test_site_admin_cannot_assign_out_of_scope_site_or_super(app, client):
    sid_a = _mk_site(app, 'rbac3-a')
    sid_b = _mk_site(app, 'rbac3-b')
    admin_uid = _mk_user(app, 'rbac3-siteadmin', [('site_admin', sid_a)])
    _login(client, admin_uid)
    _set_site(client, sid_a)

    with app.app_context():
        editor_rid = _role_id('content_editor')
        super_rid = _role_id('super_admin')
        auditor_rid = _role_id('content_auditor')
    resp = _post_create(client, 'rbac3-evil', **{
        f'site_role_{sid_a}': str(super_rid),   # 不可授予超管
        f'site_role_{sid_b}': str(editor_rid),  # 无权限站点
        f'site_role_{DEFAULT_SITE_ID}': str(auditor_rid),  # 未授权站点
    })
    assert resp.status_code == 302

    from app.models.rbac import UserRole
    from app.models.user import User
    with app.app_context():
        new_user = User.query.filter_by(username='rbac3-evil').first()
        assert new_user is not None
        assert UserRole.query.filter_by(user_id=new_user.id).count() == 0


def test_site_admin_form_hides_platform_controls_and_roles_403(app, client):
    sid_a = _mk_site(app, 'rbac3-a')
    sid_b = _mk_site(app, 'rbac3-b')
    admin_uid = _mk_user(app, 'rbac3-siteadmin', [('site_admin', sid_a)])
    _login(client, admin_uid)
    _set_site(client, sid_a)

    resp = client.get('/admin/users/create')
    assert resp.status_code == 200
    assert b'name="role_ids[]"' not in resp.data
    assert f'name="site_role_{sid_a}"'.encode() in resp.data
    assert f'name="site_role_{sid_b}"'.encode() not in resp.data

    assert client.get('/admin/roles').status_code == 403


def test_site_admin_cannot_access_plugin_management(app, client):
    """插件安装/启停/卸载为平台级功能，站点管理员不可访问。"""
    sid_a = _mk_site(app, 'rbac3-a')
    admin_uid = _mk_user(app, 'rbac3-siteadmin', [('site_admin', sid_a)])
    _login(client, admin_uid)
    _set_site(client, sid_a)

    assert client.get('/admin/plugins').status_code == 403


def test_admin_menu_separates_site_and_global_settings(app, admin_client):
    """v3.2.4：侧边栏将「站点设置」与「全局设置」分区，不再混在「系统设置」。"""
    resp = admin_client.get('/admin/')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '站点设置' in html
    assert '全局设置' in html
    assert '系统设置' not in html


def test_site_admin_menu_hides_platform_items(app, client):
    """站点管理员看到两类设置分区，但看不到平台级的站点/插件管理入口。"""
    sid_a = _mk_site(app, 'rbac3-a')
    admin_uid = _mk_user(app, 'rbac3-siteadmin', [('site_admin', sid_a)])
    _login(client, admin_uid)
    _set_site(client, sid_a)

    resp = client.get('/admin/')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '站点设置' in html and '全局设置' in html
    assert '插件管理' not in html
    assert '站点管理' not in html


def test_site_admin_cannot_edit_out_of_scope_user(app, client):
    sid_a = _mk_site(app, 'rbac3-a')
    sid_b = _mk_site(app, 'rbac3-b')
    admin_uid = _mk_user(app, 'rbac3-siteadmin', [('site_admin', sid_a)])
    other_uid = _mk_user(app, 'rbac3-other', [('content_editor', sid_b)])
    global_uid = _mk_user(app, 'rbac3-globaluser', [('readonly_viewer', None)])
    _login(client, admin_uid)
    _set_site(client, sid_a)

    assert client.get(f'/admin/users/{other_uid}/edit').status_code == 403
    assert client.get(f'/admin/users/{global_uid}/edit').status_code == 403


def test_site_admin_index_only_lists_own_scope(app, client):
    sid_a = _mk_site(app, 'rbac3-a')
    sid_b = _mk_site(app, 'rbac3-b')
    admin_uid = _mk_user(app, 'rbac3-siteadmin', [('site_admin', sid_a)])
    in_uid = _mk_user(app, 'rbac3-inscope', [('content_editor', sid_a)])
    _mk_user(app, 'rbac3-outscope', [('content_editor', sid_b)])
    _login(client, admin_uid)
    _set_site(client, sid_a)

    resp = client.get('/admin/users')
    assert resp.status_code == 200
    assert b'rbac3-inscope' in resp.data
    assert b'rbac3-outscope' not in resp.data
    assert b'rbac3-siteadmin' in resp.data


# ============================================================
# D 一人多站多角色（超级管理员分配）
# ============================================================

def test_super_admin_assigns_multi_site_roles(app, admin_client):
    sid_a = _mk_site(app, 'rbac3-a')
    sid_b = _mk_site(app, 'rbac3-b')
    with app.app_context():
        editor_rid = _role_id('content_editor')
        auditor_rid = _role_id('content_auditor')

    resp = _post_create(admin_client, 'rbac3-multi', **{
        f'site_role_{sid_a}': str(editor_rid),
        f'site_role_{sid_b}': str(auditor_rid),
    })
    assert resp.status_code == 302

    from app.models.rbac import UserRole
    from app.models.user import User
    with app.app_context():
        u = User.query.filter_by(username='rbac3-multi').first()
        links = {r.site_id: r.role.code for r in UserRole.query.filter_by(
            user_id=u.id).all()}
        assert links == {sid_a: 'content_editor', sid_b: 'content_auditor'}


def test_platform_form_keeps_global_role_card(app, admin_client):
    resp = admin_client.get('/admin/users/create')
    assert resp.status_code == 200
    assert b'name="role_ids[]"' in resp.data


def test_site_admin_editing_user_keeps_other_site_roles(app, client):
    """站点管理员保存账号时不得删除其看不到的其他站点授权。"""
    sid_a = _mk_site(app, 'rbac3-a')
    sid_b = _mk_site(app, 'rbac3-b')
    admin_uid = _mk_user(app, 'rbac3-siteadmin', [('site_admin', sid_a)])
    # 目标账号同时拥有 A/B 两站角色 → 不属于 A 站管理员的管理范围
    target_uid = _mk_user(app, 'rbac3-shared', [
        ('content_editor', sid_a), ('content_editor', sid_b)])
    _login(client, admin_uid)
    _set_site(client, sid_a)

    assert client.get(f'/admin/users/{target_uid}/edit').status_code == 403


# ============================================================
# E 迁移 0015
# ============================================================

def test_migration_0015_chain_and_schema(app):
    mod = importlib.import_module('migrations.versions.0015_v3_2_3_user_role_site')
    assert mod.revision == '0015'
    assert mod.down_revision == '0014'
    assert callable(mod.upgrade) and callable(mod.downgrade)

    with app.app_context():
        insp = sa.inspect(db.engine)
        columns = {c['name'] for c in insp.get_columns('user_roles')}
        assert 'site_id' in columns
        unique_names = {uc.get('name')
                        for uc in insp.get_unique_constraints('user_roles')}
        unique_names |= {ix['name'] for ix in insp.get_indexes('user_roles')
                         if ix.get('unique')}
        assert 'uq_user_role_site' in unique_names
        assert 'uq_user_role' not in unique_names
