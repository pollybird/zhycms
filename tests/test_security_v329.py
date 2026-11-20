"""账号状态、会员内容隔离、短信验证码与上传安全回归测试。"""
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta

import pytest

from app.extensions import cache, db, limiter
from app.models.setting import Setting


pytestmark = pytest.mark.security


def _uniq(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


@pytest.fixture(autouse=True)
def _clean_security_data(app):
    keys = (
        'api_rate_limit_login', 'enabled_plugins', 'member_sms_rate_limit',
        'member_sms_max_attempts', 'member_login_sms_enable',
        'member_auto_register_sms',
    )
    with app.app_context():
        cache.clear()
        previous = {}
        for key in keys:
            row = Setting.query.filter_by(key=key).first()
            previous[key] = row.value if row is not None else None
    yield
    from app.models.article import Article
    from app.models.column import Column
    from app.models.user import User
    from plugins.member.models import Member, MemberSmsCode

    with app.app_context():
        users = User.query.filter(User.username.like('sec329-%')).all()
        for user in users:
            db.session.delete(user)
        articles = Article.query.filter(Article.title.like('sec329-%')).all()
        for article in articles:
            db.session.delete(article)
        Column.query.filter(Column.slug.like('sec329-%')).delete(
            synchronize_session=False)
        Member.query.filter(Member.username.like('sec329-%')).delete(
            synchronize_session=False)
        MemberSmsCode.query.filter(MemberSmsCode.phone.like('139329%')).delete(
            synchronize_session=False)
        for key, value in previous.items():
            if value is None:
                Setting.query.filter_by(key=key).delete(synchronize_session=False)
            else:
                Setting.set(key, value)
        db.session.commit()
        cache.clear()
        limiter.reset()


def _make_user(username, *, active=True, deleted=False):
    from app.models.user import User

    user = User(username=username, is_super=False, is_deleted=deleted,
                is_active_flag=active)
    user.set_password('Sec329Pass!')
    db.session.add(user)
    db.session.commit()
    return user


def test_api_login_rejects_disabled_and_deleted_accounts(app, client):
    with app.app_context():
        disabled = _make_user('sec329-disabled', active=False)
        deleted = _make_user('sec329-deleted', deleted=True)
        assert disabled.id and deleted.id

    for username in ('sec329-disabled', 'sec329-deleted'):
        resp = client.post('/api/v1/auth/login', json={
            'username': username, 'password': 'Sec329Pass!',
        })
        assert resp.status_code == 401
        assert resp.get_json()['data'] is None


def test_api_login_counts_failures_and_locks_account(app, client):
    with app.app_context():
        Setting.set('api_rate_limit_login', '100')
        user = _make_user('sec329-lock')
        uid = user.id
        db.session.commit()

    for _ in range(5):
        resp = client.post('/api/v1/auth/login', json={
            'username': 'sec329-lock', 'password': 'wrong-password',
        })
        assert resp.status_code in (401, 403)

    resp = client.post('/api/v1/auth/login', json={
        'username': 'sec329-lock', 'password': 'Sec329Pass!',
    })
    assert resp.status_code == 403

    from app.models.user import User
    with app.app_context():
        locked = db.session.get(User, uid)
        assert locked.is_locked
        assert locked.login_fail_count >= 5


def test_existing_tokens_stop_working_after_account_disabled(app, client):
    with app.app_context():
        user = _make_user('sec329-token-revoke')
        uid = user.id

    tokens = client.post('/api/v1/auth/login', json={
        'username': 'sec329-token-revoke', 'password': 'Sec329Pass!',
    }).get_json()['data']

    from app.models.user import User
    with app.app_context():
        user = db.session.get(User, uid)
        user.is_active_flag = False
        db.session.commit()

    access = client.get('/api/v1/site', headers={
        'Authorization': f"Bearer {tokens['access_token']}",
    })
    refresh = client.post('/api/v1/auth/refresh', headers={
        'Authorization': f"Bearer {tokens['refresh_token']}",
    })
    assert access.status_code == 401
    assert refresh.status_code == 401


def test_member_only_content_is_not_exposed_by_content_api(app, client):
    from app.models.article import Article
    from app.models.column import Column
    from app.models.workflow import STATUS_PUBLISHED

    slug = _uniq('sec329-member')
    with app.app_context():
        column = Column(site_id=0, name='会员栏目', slug=slug, type='list',
                        member_only=True)
        db.session.add(column)
        db.session.flush()
        article = Article(site_id=0, column_id=column.id,
                          title=_uniq('sec329-article'), content='会员正文',
                          status=STATUS_PUBLISHED,
                          published_at=datetime.now())
        db.session.add(article)
        db.session.commit()
        article_id = article.id

    columns = client.get('/api/v1/columns').get_json()['data']
    assert all(item['slug'] != slug for item in columns)
    assert client.get(f'/api/v1/columns/{slug}').status_code == 404
    assert client.get(f'/api/v1/columns/{slug}/articles').status_code == 404
    assert client.get(f'/api/v1/articles/{article_id}').status_code == 404


def test_sms_code_uses_server_secret_and_locks_after_failures(app):
    from plugins.member.models import MemberSmsCode
    from plugins.member.sms import verify_code

    phone = '13932900001'
    with app.app_context():
        expected = hmac.new(
            str(app.config.get('ZHYCMS_ENC_KEY') or app.config['SECRET_KEY']).encode(),
            f'{phone}:123456'.encode(), hashlib.sha256).hexdigest()
        assert MemberSmsCode.hash_code(phone, '123456') == expected
        assert MemberSmsCode.hash_code(phone, '123456') != hashlib.sha256(
            f'{phone}:123456'.encode()).hexdigest()

        row = MemberSmsCode(
            phone=phone, purpose='reset',
            code_hash=MemberSmsCode.hash_code(phone, '123456'),
            expires_at=datetime.now() + timedelta(minutes=5), used=False)
        db.session.add(row)
        db.session.commit()
        row_id = row.id

        for expected_count in range(1, 5):
            assert verify_code(phone, '000000', purpose='reset') is False
            current = db.session.get(MemberSmsCode, row_id)
            assert current.fail_count == expected_count
            assert current.used is False

        assert verify_code(phone, '000000', purpose='reset') is False
        current = db.session.get(MemberSmsCode, row_id)
        assert current.used is True
        assert verify_code(phone, '123456', purpose='reset') is False


def test_forgot_password_does_not_reveal_unregistered_phone(app, client):
    with app.app_context():
        Setting.set('enabled_plugins', 'member')
        db.session.commit()

    resp = client.post('/forgot-password', data={
        'phone': '13932900002', 'code': '123456',
        'password': 'new-password', 'password_confirm': 'new-password',
    }, environ_base={'REMOTE_ADDR': '10.32.9.10'})
    text = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert '验证码错误或已失效' in text
    assert '该手机号尚未注册' not in text


def test_sms_login_does_not_reveal_unregistered_phone(app, client):
    from plugins.member.models import MemberSmsCode

    phone = '13932900004'
    with app.app_context():
        Setting.set('enabled_plugins', 'member')
        Setting.set('member_login_sms_enable', 'on')
        Setting.set('member_auto_register_sms', 'off')
        db.session.add(MemberSmsCode(
            phone=phone, purpose='login',
            code_hash=MemberSmsCode.hash_code(phone, '123456'),
            expires_at=datetime.now() + timedelta(minutes=5), used=False))
        db.session.commit()

    resp = client.post('/login', data={
        'login_type': 'sms', 'phone': phone, 'code': '123456',
    }, environ_base={'REMOTE_ADDR': '10.32.9.12'})
    text = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert '验证码错误或已失效' in text
    assert '该手机号尚未注册' not in text


def test_member_sms_login_endpoint_is_rate_limited(app, client):
    with app.app_context():
        Setting.set('enabled_plugins', 'member')
        Setting.set('member_sms_rate_limit', '10')
        db.session.commit()

    responses = []
    for _ in range(11):
        responses.append(client.post('/login', data={
            'login_type': 'sms', 'phone': '13932900003', 'code': '000000',
        }, environ_base={'REMOTE_ADDR': '10.32.9.11'}))
    assert [r.status_code for r in responses[:10]] == [200] * 10
    assert responses[-1].status_code == 429


def test_svg_sanitizer_removes_active_content_and_external_links():
    from app.utils.uploads import _sanitize_svg

    payload = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" onload="alert(1)">
      <script>alert(1)</script>
      <foreignObject><body xmlns="http://www.w3.org/1999/xhtml"><a href="javascript:alert(1)">x</a></body></foreignObject>
      <a href="javascript:alert(1)"><rect width="10" height="10"/></a>
      <image href="https://evil.example/x.png"/>
      <use href="https://evil.example/x.svg#x"/>
      <rect id="ok" x="1" y="1" width="8" height="8" fill="red"/>
    </svg>'''
    result = _sanitize_svg(payload).decode('utf-8')
    lowered = result.lower()
    assert '<script' not in lowered
    assert 'foreignobject' not in lowered
    assert 'onload' not in lowered
    assert 'javascript:' not in lowered
    assert '<image' not in lowered
    assert '<a ' not in lowered
    assert 'https://evil.example' not in lowered
    assert 'id="ok"' in result
    assert 'fill="red"' in result


def test_svg_sanitizer_rejects_doctype_and_entity_declarations():
    from app.utils.uploads import _sanitize_svg

    payload = b'<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><svg><text>&xxe;</text></svg>'
    with pytest.raises(ValueError):
        _sanitize_svg(payload)


def test_admin_logout_rejects_get(admin_client):
    assert admin_client.get('/admin/logout').status_code == 405
