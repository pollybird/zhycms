"""v3.2.12 Webhook 事件订阅回归测试。

覆盖：订阅唯一约束、密钥加密存储、事件发射（含回滚不产生事件）、
投递成功/重试/终态失败、签名、禁跟随重定向、SSRF、限速、并发抢占、
错误截断、幂等标识稳定、后台权限。
"""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.setting import Setting
from app.models.webhook import WebhookEvent, WebhookSubscription
from app.services import webhook as wh
from app.services.webhook import (
    _claim, _rate_ok, create_test_event, deliver_due_events, emit,
    retry_event, sign,
)


@pytest.fixture(autouse=True)
def _clean_webhook(app):
    from app.extensions import cache
    with app.app_context():
        WebhookEvent.query.delete()
        WebhookSubscription.query.delete()
        Setting.set('webhook_allow_http', 'off')
        Setting.set('webhook_allow_private', 'off')
        db.session.commit()
        # SQLite 删除后订阅 id 会复用，清空限流计数避免跨用例串扰
        cache.clear()
        wh._LOCAL_WINDOWS.clear()
    yield
    with app.app_context():
        db.session.rollback()


def _sub(url='https://example.com/hook', events='webhook.test', site_id=0,
         secret='s3cr3t'):
    sub = WebhookSubscription(site_id=site_id, url=url, events=events)
    sub.set_secret(secret)
    db.session.add(sub)
    db.session.commit()
    return sub


def _event(sub=None):
    return create_test_event(sub or _sub())


def _mock_post(monkeypatch, responder):
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None,
                  allow_redirects=None, **kwargs):
        calls.append({'url': url, 'data': data, 'headers': headers,
                      'timeout': timeout, 'allow_redirects': allow_redirects})
        return responder(url, data, headers)

    monkeypatch.setattr(wh.requests, 'post', fake_post)
    return calls


def _force_due(event):
    event.next_retry_at = datetime.now() - timedelta(seconds=1)
    db.session.commit()


# ============================================================
# 订阅与密钥
# ============================================================

def test_webhook_subscription_unique_per_site(app):
    with app.app_context():
        _sub()
        db.session.add(WebhookSubscription(
            site_id=0, url='https://example.com/hook', events='webhook.test'))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_webhook_secret_encrypted_at_rest(app):
    with app.app_context():
        sub = _sub(secret='plain-secret-value')
        raw = db.session.execute(text(
            'SELECT secret_enc FROM webhook_subscriptions WHERE id=:id'),
            {'id': sub.id}).scalar()
        assert 'plain-secret-value' not in raw
        assert raw.startswith('gAAAAA')
        assert sub.secret == 'plain-secret-value'
        assert 'plain-secret-value' not in sub.secret_mask


# ============================================================
# 事件发射
# ============================================================

def _make_article(status='draft'):
    import uuid
    from app.models.column import Column
    from app.models.article import Article
    slug = 'wh-col-' + uuid.uuid4().hex[:8]
    col = Column(name='Webhook 栏目', slug=slug, type='article', site_id=0)
    db.session.add(col)
    db.session.flush()
    article = Article(column_id=col.id, site_id=0, title='Webhook 文章',
                      status=status)
    db.session.add(article)
    db.session.commit()
    return article


def test_emit_article_published(app):
    from app.models.user import User
    from app.services.workflow_service import transition_article, ACTION_PUBLISH
    with app.app_context():
        _sub(events='article.published')
        article = _make_article()
        admin = User.query.filter_by(username='admin').first()
        result = transition_article(article, ACTION_PUBLISH, user=admin)
        assert result.ok
        events = WebhookEvent.query.filter_by(
            event_type='article.published', site_id=0).all()
        assert len(events) == 1
        payload = json.loads(events[0].payload_json)
        assert payload['data']['article_id'] == article.id
        assert payload['data']['title'] == 'Webhook 文章'
        assert payload['data']['url']
        assert 'password' not in events[0].payload_json
        assert 'secret' not in events[0].payload_json


def test_emit_after_rollback_not_created(app, monkeypatch):
    from app.models.user import User
    from app.services import workflow_service as ws
    with app.app_context():
        _sub(events='article.published')
        article = _make_article()
        admin = User.query.filter_by(username='admin').first()

        def boom(*args, **kwargs):
            raise RuntimeError('snapshot failure')

        monkeypatch.setattr(ws.ArticleVersion, 'snapshot', boom)
        result = ws.transition_article(article, ws.ACTION_PUBLISH, user=admin)
        assert not result.ok
        assert db.session.get(type(article), article.id).status == 'draft'
        assert WebhookEvent.query.count() == 0


# ============================================================
# 投递
# ============================================================

def test_deliver_success_marks_success(app, monkeypatch):
    with app.app_context():
        event = _event()
        _mock_post(monkeypatch, lambda *a: SimpleNamespace(
            status_code=200, text='ok'))
        stats = deliver_due_events()
        db.session.refresh(event)
        assert stats['success'] == 1
        assert event.status == WebhookEvent.STATUS_SUCCESS
        assert event.delivered_at is not None
        assert event.last_status_code == 200


def test_deliver_retries_then_fails(app, monkeypatch):
    from app.models.audit import AuditLog, MODULE_OTHER
    with app.app_context():
        event = _event()
        _mock_post(monkeypatch, lambda *a: SimpleNamespace(
            status_code=500, text='server error'))
        deliver_due_events()
        db.session.refresh(event)
        assert event.status == WebhookEvent.STATUS_PENDING
        assert event.attempts == 1
        assert 0 <= (event.next_retry_at - datetime.now()).total_seconds() <= 2

        _force_due(event)
        deliver_due_events()
        db.session.refresh(event)
        assert event.attempts == 2
        assert 9 <= (event.next_retry_at - datetime.now()).total_seconds() <= 11

        _force_due(event)
        deliver_due_events()
        db.session.refresh(event)
        assert event.status == WebhookEvent.STATUS_FAILED
        assert event.attempts == 3
        audit = AuditLog.query.filter_by(
            module=MODULE_OTHER, target_id=event.id).all()
        assert audit


def test_deliver_signature_valid(app, monkeypatch):
    with app.app_context():
        sub = _sub(secret='sign-me')
        event = _event(sub)
        calls = _mock_post(monkeypatch, lambda *a: SimpleNamespace(
            status_code=200, text='ok'))
        deliver_due_events()
        assert len(calls) == 1
        headers = calls[0]['headers']
        parts = dict(p.split('=', 1)
                     for p in headers['X-ZhyCMS-Signature'].split(','))
        expected = sign(sub.secret, parts['t'], calls[0]['data'])
        assert parts['v1'] == expected
        assert headers['X-ZhyCMS-Event'] == 'webhook.test'
        assert headers['X-ZhyCMS-Delivery'] == event.replay_id
        assert calls[0]['timeout'] == wh.REQUEST_TIMEOUT


def test_deliver_no_redirect_follow(app, monkeypatch):
    with app.app_context():
        event = _event()
        calls = _mock_post(monkeypatch, lambda *a: SimpleNamespace(
            status_code=302, text='redirect'))
        deliver_due_events()
        db.session.refresh(event)
        assert calls[0]['allow_redirects'] is False
        assert event.last_status_code == 302
        assert event.status == WebhookEvent.STATUS_PENDING
        assert event.attempts == 1


def test_deliver_rejects_private_url(app, admin_client, monkeypatch):
    with app.app_context():
        Setting.set('webhook_allow_http', 'on')
        db.session.commit()
        sub = _sub(url='http://127.0.0.1:9/hook')
        event = _event(sub)

        def forbidden(*a):
            raise AssertionError('不应向内网地址发起请求')

        _mock_post(monkeypatch, forbidden)
        deliver_due_events()
        db.session.refresh(event)
        assert event.status == WebhookEvent.STATUS_FAILED
        assert '安全校验' in event.last_error

        # 后台保存同样被拒绝
        admin_client.post('/admin/sites/webhooks/create', data={
            'url': 'http://192.168.1.10/hook', 'events': ['webhook.test'],
            'enabled': 'on'})
        assert WebhookSubscription.query.filter_by(
            url='http://192.168.1.10/hook').first() is None


def test_deliver_respects_rate_limit(app, monkeypatch):
    with app.app_context():
        fixed = 1700000000
        monkeypatch.setattr(wh, 'time', SimpleNamespace(
            time=lambda: fixed, monotonic=lambda: 1000.0))
        results = [_rate_ok('rate-test-sub') for _ in range(6)]
        assert results[:5] == [True] * 5
        assert results[5] is False


def test_deliver_claims_event_once(app, monkeypatch):
    with app.app_context():
        event = _event()
        _mock_post(monkeypatch, lambda *a: SimpleNamespace(
            status_code=200, text='ok'))
        assert _claim(event.id) is True
        assert _claim(event.id) is False
        stats = deliver_due_events()
        assert stats['claimed'] == 0  # delivering 状态不会被重复领取


def test_webhook_events_payload_truncated(app, monkeypatch):
    with app.app_context():
        event = _event()
        _mock_post(monkeypatch, lambda *a: SimpleNamespace(
            status_code=500, text='x' * 10000))
        deliver_due_events()
        db.session.refresh(event)
        assert len(event.last_error) <= wh.ERROR_BODY_LIMIT


def test_replay_same_id_no_duplicate_business(app, monkeypatch):
    with app.app_context():
        event = _event()
        responses = iter([SimpleNamespace(status_code=500, text='boom'),
                          SimpleNamespace(status_code=200, text='ok')])
        calls = _mock_post(monkeypatch, lambda *a: next(responses))
        deliver_due_events()
        db.session.refresh(event)
        assert event.status == WebhookEvent.STATUS_PENDING
        retry_event(event.id)
        deliver_due_events()
        db.session.refresh(event)
        assert event.status == WebhookEvent.STATUS_SUCCESS
        ids = [c['headers']['X-ZhyCMS-Delivery'] for c in calls]
        assert ids == [event.replay_id, event.replay_id]
        payloads = [json.loads(c['data']) for c in calls]
        assert payloads[0]['replay_id'] == payloads[1]['replay_id']


# ============================================================
# 后台权限
# ============================================================

def test_webhook_admin_requires_permission(app, client):
    from app.models.user import User
    with app.app_context():
        user = User.query.filter_by(username='wh_plain').first()
        if user is None:
            user = User(username='wh_plain', is_super=False)
            user.set_password('pass12345')
            db.session.add(user)
            db.session.commit()
        uid = str(user.id)
    with client.session_transaction() as sess:
        sess['_user_id'] = uid
        sess['_fresh'] = True
    resp = client.get('/admin/sites/webhooks')
    assert resp.status_code == 403


def test_emit_only_matching_subscriptions(app):
    with app.app_context():
        _sub(url='https://example.com/a', events='article.published')
        _sub(url='https://example.com/b', events='form.submitted')
        disabled = _sub(url='https://example.com/c',
                        events='article.published')
        disabled.enabled = False
        db.session.commit()
        count = emit('article.published', 0, {'article_id': 1})
        assert count == 1
        assert WebhookEvent.query.count() == 1


def test_webhook_admin_flow(app, admin_client):
    """后台全链路：创建（密钥展示一次）→ 列表 → 测试 → 记录 → 重试 → 轮换 → 删除。"""
    resp = admin_client.post('/admin/sites/webhooks/create', data={
        'url': 'https://example.com/admin-flow',
        'events': ['webhook.test', 'article.published'],
        'enabled': 'on'}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        sub = WebhookSubscription.query.filter_by(
            url='https://example.com/admin-flow').first()
        assert sub is not None and sub.enabled
        sid = sub.id
        old_secret = sub.secret

    assert admin_client.get('/admin/sites/webhooks').status_code == 200
    assert admin_client.get(
        f'/admin/sites/webhooks/{sid}/edit').status_code == 200

    resp = admin_client.post(f'/admin/sites/webhooks/{sid}/test',
                             follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        event = WebhookEvent.query.filter_by(subscription_id=sid).one()
        event.status = WebhookEvent.STATUS_FAILED
        db.session.commit()
        eid = event.id

    assert admin_client.get('/admin/sites/webhooks/events').status_code == 200
    admin_client.post(f'/admin/sites/webhooks/events/{eid}/retry')
    with app.app_context():
        event = db.session.get(WebhookEvent, eid)
        assert event.status == WebhookEvent.STATUS_PENDING
        assert event.attempts == 0

    admin_client.post(f'/admin/sites/webhooks/{sid}/rotate')
    with app.app_context():
        sub = db.session.get(WebhookSubscription, sid)
        assert sub.secret != old_secret

    admin_client.post(f'/admin/sites/webhooks/{sid}/delete')
    with app.app_context():
        assert db.session.get(WebhookSubscription, sid) is None
        assert WebhookEvent.query.filter_by(subscription_id=sid).count() == 0
