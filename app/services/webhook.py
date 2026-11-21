"""Webhook 事件订阅与投递服务（v3.2.12）。

职责：
  - emit()：业务事务提交后调用，只落库事件行，不做任何网络调用；
  - deliver_due_events()：由 10 秒调度任务或 ``python -m app.services.webhook --once``
    驱动，抢占式领取到期事件并投递；
  - sign()：HMAC-SHA256 签名，接收方按 ``t=<unix>,v1=<hex>`` 复算校验。

投递语义：at-least-once。重试保持同一 replay_id（X-ZhyCMS-Delivery），
消费方应据此幂等；建议同时校验签名时间戳偏差 ≤ 5 分钟。
"""
import hmac
import json
import time
import uuid
from collections import deque
from datetime import datetime, timedelta
from hashlib import sha256

import requests
from flask import current_app
from sqlalchemy import text

from ..extensions import db
from ..models.audit import OP_OTHER, MODULE_OTHER
from ..models.setting import Setting
from ..models.webhook import WebhookEvent, WebhookSubscription
from ..utils.helpers import audit_log
from ..utils.url_safety import assert_safe_external_url

# 支持的事件类型（值用于后台多选展示）
EVENT_TYPES = {
    'article.published': '文章发布',
    'article.archived': '文章归档',
    'form.submitted': '表单提交',
    'backup.completed': '站点备份完成',
    'site.status_changed': '站点启停',
    'ssl.expiring': '证书临期/过期',
    'webhook.test': '测试事件',
}

MAX_ATTEMPTS = 3
RETRY_DELAYS = (1, 10, 60)  # 秒，第 n 次失败后延迟 RETRY_DELAYS[n-1]
RATE_PER_SECOND = 5         # 每订阅每秒最多投递次数
REQUEST_TIMEOUT = 5
ERROR_BODY_LIMIT = 2048     # last_error 最多保留的响应/错误文本长度

# 进程内限流滑窗（Redis 不可用时的单进程兜底）
_LOCAL_WINDOWS = {}
_RATE_FALLBACK_WARNED = False


# ============================================================
# 事件发射
# ============================================================

def emit(event_type, site_id, payload):
    """为当前站点订阅了该事件类型的启用订阅各插入一条投递记录。

    返回插入条数；任何异常仅记录日志，不影响主业务。
    调用方须在业务事务提交之后调用本函数。
    """
    try:
        subs = WebhookSubscription.query.filter_by(
            site_id=site_id or 0, enabled=True).all()
        subs = [s for s in subs if s.subscribes(event_type)]
        if not subs:
            return 0
        now = datetime.now()
        events = []
        for sub in subs:
            replay_id = uuid.uuid4().hex
            body = json.dumps({
                'event': event_type,
                'site_id': site_id or 0,
                'replay_id': replay_id,
                'created_at': now.isoformat(),
                'data': payload,
            }, ensure_ascii=False)
            events.append(WebhookEvent(
                subscription_id=sub.id, site_id=site_id or 0,
                event_type=event_type, payload_json=body,
                status=WebhookEvent.STATUS_PENDING,
                next_retry_at=now, replay_id=replay_id))
        db.session.add_all(events)
        db.session.commit()
        return len(events)
    except Exception as e:
        db.session.rollback()
        current_app.logger.warning('Webhook 事件发射失败（%s）：%s', event_type, e)
        return 0


def create_test_event(subscription):
    """后台「发送测试」：为单个订阅生成 webhook.test 事件（异步投递）。"""
    payload = {'message': 'ZhyCMS Webhook 测试',
               'timestamp': datetime.now().isoformat()}
    replay_id = uuid.uuid4().hex
    now = datetime.now()
    body = json.dumps({'event': 'webhook.test', 'site_id': subscription.site_id,
                       'replay_id': replay_id, 'created_at': now.isoformat(),
                       'data': payload}, ensure_ascii=False)
    event = WebhookEvent(
        subscription_id=subscription.id, site_id=subscription.site_id,
        event_type='webhook.test', payload_json=body,
        status=WebhookEvent.STATUS_PENDING, next_retry_at=now,
        replay_id=replay_id)
    db.session.add(event)
    db.session.commit()
    return event


# ============================================================
# 签名
# ============================================================

def sign(secret, timestamp, body):
    """hex(hmac_sha256(secret, f"{t}.".encode() + body))。"""
    if isinstance(body, str):
        body = body.encode('utf-8')
    msg = str(timestamp).encode('utf-8') + b'.' + body
    return hmac.new(secret.encode('utf-8'), msg, sha256).hexdigest()


# ============================================================
# 投递
# ============================================================

def _allowed_schemes():
    if Setting.get('webhook_allow_http') == 'on':
        return ('https', 'http')
    return ('https',)


def validate_target_url(url):
    """发送/保存前校验目标地址：协议白名单 + 内网地址限制。"""
    if Setting.get('webhook_allow_private') == 'on':
        # 显式放行内网时仍限制协议与主机名格式
        from ..utils.url_safety import assert_http_url
        return assert_http_url(url, allow_private=True)
    return assert_safe_external_url(url, allowed_hosts=None,
                                    allow_schemes=_allowed_schemes())


def _rate_ok(subscription_id):
    """每订阅每秒最多 RATE_PER_SECOND 次；优先 Redis 计数，退化进程内滑窗。"""
    second = int(time.time())
    try:
        from ..extensions import cache
        key = f'zhycms:webhook:rl:{subscription_id}:{second}'
        cache.add(key, 0, timeout=3)
        count = cache.inc(key)
        if count is not None:
            return count <= RATE_PER_SECOND
    except Exception as e:
        global _RATE_FALLBACK_WARNED
        if not _RATE_FALLBACK_WARNED:
            _RATE_FALLBACK_WARNED = True
            current_app.logger.warning(
                'Webhook 限流共享计数不可用，改用进程内滑窗：%s', e)
    window = _LOCAL_WINDOWS.setdefault(subscription_id, deque())
    now = time.monotonic()
    while window and now - window[0] >= 1.0:
        window.popleft()
    if len(window) >= RATE_PER_SECOND:
        return False
    window.append(now)
    return True


def _claim(event_id):
    """抢占式领取：仅当事件仍为 pending 时置为 delivering，返回是否成功。"""
    result = db.session.execute(
        text("UPDATE webhook_events SET status='delivering' "
             "WHERE id=:id AND status='pending'"), {'id': event_id})
    db.session.commit()
    return result.rowcount == 1


def _final_failure_audit(event):
    try:
        audit_log(OP_OTHER, MODULE_OTHER, target_id=event.id,
                  target_name=event.event_type,
                  detail={'event': 'webhook_delivery_failed',
                          'subscription_id': event.subscription_id,
                          'replay_id': event.replay_id,
                          'attempts': event.attempts,
                          'last_error': (event.last_error or '')[:500]})
    except Exception as e:
        current_app.logger.warning('Webhook 失败审计写入失败：%s', e)


def _finish_failure(event, error, status_code=None):
    """统一失败处理：重试或终态 failed。"""
    event.attempts = (event.attempts or 0) + 1
    event.last_status_code = status_code
    event.last_error = (error or '')[:ERROR_BODY_LIMIT]
    if event.attempts < MAX_ATTEMPTS:
        delay = RETRY_DELAYS[event.attempts - 1]
        event.status = WebhookEvent.STATUS_PENDING
        event.next_retry_at = datetime.now() + timedelta(seconds=delay)
    else:
        event.status = WebhookEvent.STATUS_FAILED
    db.session.commit()
    if event.status == WebhookEvent.STATUS_FAILED:
        _final_failure_audit(event)


def _deliver(event):
    sub = db.session.get(WebhookSubscription, event.subscription_id)
    if sub is None or not sub.enabled:
        event.status = WebhookEvent.STATUS_FAILED
        event.last_error = '订阅已停用或删除'
        db.session.commit()
        return 'failed'

    if not _rate_ok(sub.id):
        # 限速不消耗重试次数，下一秒再投
        event.status = WebhookEvent.STATUS_PENDING
        event.next_retry_at = datetime.now() + timedelta(seconds=1)
        db.session.commit()
        return 'rate_limited'

    try:
        validate_target_url(sub.url)
    except ValueError as e:
        event.status = WebhookEvent.STATUS_FAILED
        event.last_error = f'目标地址未通过安全校验：{e}'[:ERROR_BODY_LIMIT]
        db.session.commit()
        _final_failure_audit(event)
        return 'failed'

    body = event.payload_json.encode('utf-8')
    timestamp = str(int(time.time()))
    headers = {
        'Content-Type': 'application/json',
        'X-ZhyCMS-Event': event.event_type,
        'X-ZhyCMS-Delivery': event.replay_id,
        'X-ZhyCMS-Signature': f't={timestamp},v1={sign(sub.secret, timestamp, body)}',
        'User-Agent': 'ZhyCMS-Webhook/1.0',
    }
    try:
        resp = requests.post(sub.url, data=body, headers=headers,
                             timeout=REQUEST_TIMEOUT, allow_redirects=False)
    except requests.RequestException as e:
        _finish_failure(event, f'请求异常：{e}')
        return 'retried' if event.status == WebhookEvent.STATUS_PENDING else 'failed'

    if 200 <= resp.status_code < 300:
        event.status = WebhookEvent.STATUS_SUCCESS
        event.last_status_code = resp.status_code
        event.last_error = None
        event.delivered_at = datetime.now()
        db.session.commit()
        return 'success'

    # 非 2xx（含 302，不跟随重定向）按失败处理，响应体截断保存
    _finish_failure(event, f'HTTP {resp.status_code}: {resp.text}',
                    status_code=resp.status_code)
    return 'retried' if event.status == WebhookEvent.STATUS_PENDING else 'failed'


def deliver_due_events(limit=20):
    """领取并投递到期事件，返回统计 {claimed, success, failed, retried}。"""
    now = datetime.now()
    due = WebhookEvent.query.filter(
        WebhookEvent.status == WebhookEvent.STATUS_PENDING,
        WebhookEvent.next_retry_at <= now,
    ).order_by(WebhookEvent.id.asc()).limit(limit).all()
    stats = {'claimed': 0, 'success': 0, 'failed': 0, 'retried': 0}
    for row in due:
        if not _claim(row.id):
            continue  # 已被其他 worker 抢占
        stats['claimed'] += 1
        event = db.session.get(WebhookEvent, row.id)
        result = _deliver(event)
        if result in stats:
            stats[result] += 1
    return stats


def retry_event(event_id, site_id=None):
    """后台手动重试：重置为 pending、attempts=0。"""
    query = WebhookEvent.query.filter_by(id=event_id)
    if site_id is not None:
        query = query.filter_by(site_id=site_id)
    event = query.first()
    if event is None:
        return None
    event.status = WebhookEvent.STATUS_PENDING
    event.attempts = 0
    event.next_retry_at = datetime.now()
    db.session.commit()
    return event


# ============================================================
# 外部 cron 入口：python -m app.services.webhook --once
# ============================================================

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='ZhyCMS Webhook 投递器')
    parser.add_argument('--once', action='store_true', help='投递一轮到期事件后退出')
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args(argv)
    if not args.once:
        parser.error('当前仅支持 --once（周期投递请使用内置调度器）')
    from .. import create_app
    app = create_app()
    with app.app_context():
        stats = deliver_due_events(limit=args.limit)
        print(json.dumps(stats, ensure_ascii=False))


if __name__ == '__main__':
    main()
