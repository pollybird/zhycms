"""v3.2.4 后台密码复杂度可配置回归测试。

覆盖：
  - 默认策略保持 v3.1.10 严格规则（12 位 + 大小写 + 数字 + 特殊字符）
  - 读取自定义策略并据此校验
  - 最低位数的下限/上限收敛（6-64）
  - 仅超级管理员可调整，站点管理员提交不生效
  - 安全设置页仅超管可见密码复杂度卡片
"""
import pytest

from app.extensions import db

pytestmark = pytest.mark.sites

POLICY_KEYS = (
    'password_min_length',
    'password_require_upper',
    'password_require_lower',
    'password_require_digit',
    'password_require_special',
)

DEFAULTS = {
    'password_min_length': '12',
    'password_require_upper': 'on',
    'password_require_lower': 'on',
    'password_require_digit': 'on',
    'password_require_special': 'on',
}


def _set_policy(app, **values):
    from app.models.setting import Setting
    with app.app_context():
        for key, value in values.items():
            Setting.set(key, str(value))
        db.session.commit()


@pytest.fixture(autouse=True)
def _restore_policy(app):
    from app.models.setting import Setting
    with app.app_context():
        saved = {key: Setting.get(key, DEFAULTS[key]) for key in POLICY_KEYS}
    yield
    with app.app_context():
        for key, value in saved.items():
            Setting.set(key, value)
        db.session.commit()


@pytest.fixture(autouse=True)
def _clean_users(app):
    yield
    from app.models.rbac import UserRole
    from app.models.user import User
    with app.app_context():
        uids = [u.id for u in User.query.filter(
            User.username.like('pwcfg-%')).all()]
        if uids:
            UserRole.query.filter(UserRole.user_id.in_(uids)).delete(
                synchronize_session=False)
            User.query.filter(User.id.in_(uids)).delete(
                synchronize_session=False)
            db.session.commit()


def _mk_admin_with_role(app, username, role_code, site_id=None):
    from app.models.rbac import Role, UserRole
    from app.models.user import User
    with app.app_context():
        role = Role.query.filter_by(code=role_code, is_deleted=False).first()
        user = User(username=username, is_deleted=False)
        user.set_password('Abcdef123456!')
        db.session.add(user)
        db.session.flush()
        db.session.add(UserRole(user_id=user.id, role_id=role.id,
                                site_id=site_id))
        db.session.commit()
        return user.id


def _login(client, uid):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True


# ============================================================
# 策略求值
# ============================================================

def test_default_policy_is_strict(app):
    from app.utils.password_policy import get_password_policy, validate_password
    with app.app_context():
        policy = get_password_policy()
        assert policy['min_length'] == 12
        assert policy['require_upper'] and policy['require_lower']
        assert policy['require_digit'] and policy['require_special']

        assert validate_password('Abcdef123456!')[0]
        assert not validate_password('Abcdef1!')[0]          # 不足 12 位
        assert not validate_password('abcdef123456!')[0]     # 缺大写
        assert not validate_password('ABCDEF123456!')[0]     # 缺小写
        assert not validate_password('Abcdefghijk!')[0]      # 缺数字
        assert not validate_password('Abcdef123456')[0]      # 缺特殊字符


def test_custom_relaxed_policy(app):
    _set_policy(app, password_min_length=8, password_require_upper='off',
                password_require_lower='off', password_require_digit='off',
                password_require_special='off')
    from app.utils.password_policy import get_password_policy, validate_password
    with app.app_context():
        policy = get_password_policy()
        assert policy['min_length'] == 8
        assert not any(policy[key] for key in (
            'require_upper', 'require_lower', 'require_digit',
            'require_special'))
        assert validate_password('abcdefgh')[0]
        assert not validate_password('abcdefg')[0]


def test_clamped_min_length(app):
    _set_policy(app, password_min_length=3)
    from app.utils.password_policy import get_password_policy
    with app.app_context():
        assert get_password_policy()['min_length'] == 6

    _set_policy(app, password_min_length=200)
    with app.app_context():
        assert get_password_policy()['min_length'] == 64


# ============================================================
# 设置页与权限
# ============================================================

def test_super_can_update_policy(app, admin_client):
    resp = admin_client.post('/admin/settings/security', data={
        'admin_prefix': 'admin',
        'login_max_fail': '5',
        'login_lock_minutes': '10',
        'password_min_length': '8',
        # 四个复选框均不勾选 → off
    }, follow_redirects=False)
    assert resp.status_code in (302, 303)

    from app.models.setting import Setting
    with app.app_context():
        assert Setting.get('password_min_length') == '8'
        for key in ('password_require_upper', 'password_require_lower',
                    'password_require_digit', 'password_require_special'):
            assert Setting.get(key) == 'off'


def test_super_weak_length_warns(app, admin_client):
    resp = admin_client.post('/admin/settings/security', data={
        'admin_prefix': 'admin',
        'login_max_fail': '5',
        'login_lock_minutes': '10',
        'password_min_length': '6',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert '低于 8 位'.encode() in resp.data

    from app.models.setting import Setting
    with app.app_context():
        assert Setting.get('password_min_length') == '6'


def test_non_super_cannot_update_policy(app, client):
    uid = _mk_admin_with_role(app, 'pwcfg-siteadmin', 'site_admin', site_id=None)
    _login(client, uid)

    resp = client.post('/admin/settings/security', data={
        'admin_prefix': 'admin',
        'login_max_fail': '5',
        'login_lock_minutes': '10',
        'password_min_length': '6',
        'password_require_special': 'off',
    }, follow_redirects=False)
    assert resp.status_code in (302, 303)

    from app.models.setting import Setting
    with app.app_context():
        assert Setting.get('password_min_length') == '12'
        assert Setting.get('password_require_special') == 'on'


def test_policy_card_only_visible_to_super(app, client):
    super_resp = client.get('/admin/settings/security')
    # client 尚未登录 → 重定向到登录页
    assert super_resp.status_code in (301, 302, 303)

    uid = _mk_admin_with_role(app, 'pwcfg-siteadmin', 'site_admin', site_id=None)
    _login(client, uid)
    non_super = client.get('/admin/settings/security')
    assert non_super.status_code == 200
    assert b'type="number" name="password_min_length"' not in non_super.data
    assert b'confirmWeakPassword' not in non_super.data
