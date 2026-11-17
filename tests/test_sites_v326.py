"""v3.2.6 站点级设置与日志可见性回归测试。

覆盖：
  - 审计/登录日志仅超管与站点管理员可见（审核员/只读查看员 403，仪表盘不渲染）
  - 站点管理员仅能看到自己 site_admin 授权站点的审计/登录日志（列表/导出/仪表盘）
  - 消息通知、编辑设置、内容 API 由全局改为站点级（写入互不影响）
  - Redis 缓存页仅超级管理员可见
  - 内容 API 的开关、静态令牌、JWT 密钥按站点生效
"""
import pytest

from app.extensions import db

pytestmark = pytest.mark.sites

SITE_TAG = 'v326-'
PWD = 'Abcdef123456!'


# ============================================================
# 辅助
# ============================================================

def _mk_site(app, slug, domain=None):
    from app.models.site import Site
    with app.app_context():
        site = Site(name=f'站点-{slug}', slug=slug, domain=domain)
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
        user.set_password(PWD)
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


def _mk_audit(app, site_id, marker):
    from app.models.audit import MODULE_ARTICLE, OP_UPDATE, AuditLog
    with app.app_context():
        db.session.add(AuditLog(
            site_id=site_id, username=f'{SITE_TAG}audit', nickname='',
            ip='127.0.0.1', op_type=OP_UPDATE, module=MODULE_ARTICLE,
            target_name=marker, detail=marker,
        ))
        db.session.commit()


def _mk_login_log(app, site_id, marker):
    from app.models.user import LoginLog
    with app.app_context():
        db.session.add(LoginLog(
            username=marker, site_id=site_id, ip='10.0.0.1',
            result='success', message='ok',
        ))
        db.session.commit()


@pytest.fixture(autouse=True)
def _clean_v326(app):
    """清理本文件创建的站点、账号、日志与站点级设置。"""
    yield
    from app.models.audit import AuditLog
    from app.models.rbac import UserRole
    from app.models.setting import Setting
    from app.models.site import Site
    from app.models.user import LoginLog, User
    with app.app_context():
        sids = [s.id for s in Site.query.filter(
            Site.slug.like(f'{SITE_TAG}%')).all()]
        uids = [u.id for u in User.query.filter(
            User.username.like(f'{SITE_TAG}%')).all()]
        if sids:
            AuditLog.query.filter(AuditLog.site_id.in_(sids)).delete(
                synchronize_session=False)
            LoginLog.query.filter(LoginLog.site_id.in_(sids)).delete(
                synchronize_session=False)
            Setting.query.filter(Setting.site_id.in_(sids)).delete(
                synchronize_session=False)
        if uids:
            UserRole.query.filter(UserRole.user_id.in_(uids)).delete(
                synchronize_session=False)
            LoginLog.query.filter(LoginLog.user_id.in_(uids)).delete(
                synchronize_session=False)
            User.query.filter(User.id.in_(uids)).delete(
                synchronize_session=False)
        Site.query.filter(Site.slug.like(f'{SITE_TAG}%')).delete(
            synchronize_session=False)
        db.session.commit()


# ============================================================
# A 日志可见性
# ============================================================

@pytest.mark.parametrize('role_code', ['content_auditor', 'readonly_viewer'])
def test_logs_forbidden_for_non_admin_roles(app, client, role_code):
    """审核员/只读查看员：日志页 403，仪表盘无日志区块与入口。"""
    sid = _mk_site(app, f'{SITE_TAG}role-a')
    uid = _mk_user(app, f'{SITE_TAG}user-{role_code}', [(role_code, sid)])
    _login(client, uid)
    _set_site(client, sid)

    assert client.get('/admin/audit-logs').status_code == 403
    assert client.get('/admin/logs').status_code == 403

    resp = client.get('/admin/')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '最近操作审计' not in html
    assert '最近登录日志' not in html
    assert '日志审计' not in html


def test_site_admin_sees_only_own_site_logs(app, client):
    """站点管理员仅能看到自己授权站点的审计/登录日志。"""
    sid_a = _mk_site(app, f'{SITE_TAG}log-a')
    sid_b = _mk_site(app, f'{SITE_TAG}log-b')
    _mk_audit(app, sid_a, 'v326-audit-marker-a')
    _mk_audit(app, sid_b, 'v326-audit-marker-b')
    _mk_login_log(app, sid_a, 'v326-login-marker-a')
    _mk_login_log(app, sid_b, 'v326-login-marker-b')

    uid = _mk_user(app, f'{SITE_TAG}siteadmin', [('site_admin', sid_a)])
    _login(client, uid)
    _set_site(client, sid_a)

    resp = client.get('/admin/audit-logs')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'v326-audit-marker-a' in html
    assert 'v326-audit-marker-b' not in html

    # 显式筛选 B 站点也不能越权拿到 B 的数据
    resp = client.get(f'/admin/audit-logs?site_id={sid_b}')
    assert resp.status_code == 200
    assert 'v326-audit-marker-b' not in resp.get_data(as_text=True)

    # 导出同样受站点范围限制
    resp = client.get('/admin/audit-logs/export')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'v326-audit-marker-a' in body
    assert 'v326-audit-marker-b' not in body

    resp = client.get('/admin/logs')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'v326-login-marker-a' in html
    assert 'v326-login-marker-b' not in html

    resp = client.get('/admin/')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'v326-audit-marker-a' in html
    assert 'v326-audit-marker-b' not in html
    assert 'v326-login-marker-a' in html
    assert 'v326-login-marker-b' not in html


# ============================================================
# B 站点级设置
# ============================================================

def test_site_level_settings_isolated(app):
    """通知/编辑器/内容 API 相关键为站点级，写入 A/B 互不影响。"""
    from app.models.setting import Setting

    for key in ('notify_email_receivers', 'form_notify_enable', 'api_enable',
                'api_auth_mode', 'api_token', 'jwt_secret_key',
                'editor_default_mode'):
        assert Setting._is_global_key(key) is False, key
    assert Setting._is_global_key('upload_max_size') is True
    assert Setting._is_global_key('password_min_length') is True

    sid_a = _mk_site(app, f'{SITE_TAG}cfg-a')
    sid_b = _mk_site(app, f'{SITE_TAG}cfg-b')
    with app.app_context():
        Setting.set_for_site('editor_default_mode', 'markdown', sid_a)
        Setting.set_for_site('editor_default_mode', 'ckeditor', sid_b)
        Setting.set_for_site('form_notify_enable', 'on', sid_a)
        Setting.set_for_site('form_notify_enable', '', sid_b)
        Setting.set_for_site('notify_email_receivers', 'a@example.com', sid_a)
        Setting.set_for_site('notify_email_receivers', 'b@example.com', sid_b)
        Setting.set_for_site('api_enable', 'on', sid_a)
        Setting.set_for_site('api_enable', 'off', sid_b)
        Setting.set_for_site('jwt_secret_key', 'jwt-secret-a', sid_a)
        Setting.set_for_site('jwt_secret_key', 'jwt-secret-b', sid_b)
        db.session.commit()

        assert Setting.get_for_site('editor_default_mode', sid_a) == 'markdown'
        assert Setting.get_for_site('editor_default_mode', sid_b) == 'ckeditor'
        assert Setting.get_for_site('form_notify_enable', sid_a) == 'on'
        assert Setting.get_for_site('form_notify_enable', sid_b) == ''
        assert Setting.get_for_site(
            'notify_email_receivers', sid_a) == 'a@example.com'
        assert Setting.get_for_site(
            'notify_email_receivers', sid_b) == 'b@example.com'
        assert Setting.get_for_site('api_enable', sid_a) == 'on'
        assert Setting.get_for_site('api_enable', sid_b) == 'off'
        assert Setting.get_for_site('jwt_secret_key', sid_a) == 'jwt-secret-a'
        assert Setting.get_for_site('jwt_secret_key', sid_b) == 'jwt-secret-b'


# ============================================================
# C Redis 仅超管
# ============================================================

def test_redis_page_super_admin_only(app, client):
    """站点管理员 403 且菜单无入口；超级管理员可访问。"""
    from app.models.user import User
    sid = _mk_site(app, f'{SITE_TAG}redis')
    uid = _mk_user(app, f'{SITE_TAG}redis-admin', [('site_admin', sid)])
    _login(client, uid)
    _set_site(client, sid)

    assert client.get('/admin/settings/redis').status_code == 403
    resp = client.get('/admin/')
    assert resp.status_code == 200
    assert 'Redis 缓存' not in resp.get_data(as_text=True)

    # 同一客户端切换为超级管理员后应可访问
    with app.app_context():
        admin_uid = User.query.filter_by(username='admin').first().id
    _login(client, admin_uid)
    _set_site(client, sid)
    assert client.get('/admin/settings/redis').status_code == 200


# ============================================================
# D 内容 API 站点级开关/鉴权/密钥
# ============================================================

@pytest.mark.api
class TestSiteLevelAPI:

    @pytest.fixture(autouse=True)
    def _reset_limiter(self, app):
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

    def _prepare(self, app):
        from app.models.setting import Setting
        from app.models.user import User
        sid_a = _mk_site(app, f'{SITE_TAG}api-a', domain='a.example.com')
        sid_b = _mk_site(app, f'{SITE_TAG}api-b', domain='b.example.com')
        with app.app_context():
            Setting.set_for_site('api_enable', 'on', sid_a)
            Setting.set_for_site('api_enable', 'off', sid_b)
            Setting.set_for_site('api_auth_mode', 'both', sid_a)
            Setting.set_for_site('api_auth_mode', 'both', sid_b)
            Setting.set_for_site('api_token', 'v326-token-a', sid_a)
            Setting.set_for_site('api_token', 'v326-token-b', sid_b)
            Setting.set_for_site(
                'jwt_secret_key', 'v326-jwt-secret-key-for-site-a-0123456789', sid_a)
            Setting.set_for_site(
                'jwt_secret_key', 'v326-jwt-secret-key-for-site-b-0123456789', sid_b)
            user = User(username=f'{SITE_TAG}api-user', is_deleted=False)
            user.set_password(PWD)
            db.session.add(user)
            db.session.commit()
        return sid_a, sid_b

    def test_api_switch_and_token_per_site(self, app, client):
        """api_enable/api_token 按 Host 解析的站点分别生效。"""
        from app.models.setting import Setting
        sid_a, sid_b = self._prepare(app)

        host_a = {'Host': 'a.example.com', 'X-API-Token': 'v326-token-a'}
        host_a_wrong = {'Host': 'a.example.com', 'X-API-Token': 'v326-token-b'}
        host_b = {'Host': 'b.example.com', 'X-API-Token': 'v326-token-b'}

        # A 站点开启且令牌正确 → 200；令牌错误 → 401
        assert client.get('/api/v1/site', headers=host_a).status_code == 200
        assert client.get('/api/v1/site', headers=host_a_wrong).status_code == 401
        # B 站点关闭 → 404（不因 A 开启而放行）
        assert client.get('/api/v1/site', headers=host_b).status_code == 404

        # 开启 B 后，各自令牌独立生效
        with app.app_context():
            Setting.set_for_site('api_enable', 'on', sid_b)
            db.session.commit()
        assert client.get('/api/v1/site', headers=host_b).status_code == 200
        assert client.get('/api/v1/site', headers={
            'Host': 'b.example.com', 'X-API-Token': 'v326-token-a'}).status_code == 401

    def test_jwt_secret_per_site(self, app, client):
        """按站点密钥签发；A 的 token 在 B 站点校验失败。"""
        from app.models.setting import Setting
        _, sid_b = self._prepare(app)
        with app.app_context():
            Setting.set_for_site('api_enable', 'on', sid_b)
            db.session.commit()

        resp = client.post('/api/v1/auth/login',
                           json={'username': f'{SITE_TAG}api-user', 'password': PWD},
                           headers={'Host': 'a.example.com'})
        assert resp.status_code == 200
        token = resp.get_json()['data']['access_token']

        resp = client.get('/api/v1/site', headers={
            'Host': 'a.example.com', 'Authorization': f'Bearer {token}'})
        assert resp.status_code == 200

        resp = client.get('/api/v1/site', headers={
            'Host': 'b.example.com', 'Authorization': f'Bearer {token}'})
        assert resp.status_code == 401
