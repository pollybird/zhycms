"""短信验证码：下发（含频控）、校验，三种发送通道。

通道由后台「会员设置」配置：
  log     开发模式：验证码写入应用日志（默认，免配置即可联调）
  aliyun  阿里云短信 dysmsapi（RPC v1.0 HMAC-SHA1 签名，无需 SDK 依赖）
  webhook 通用 HTTP 接口：URL 支持 {phone}/{code} 占位符，GET/POST JSON
"""
import re
import base64
import hmac
import hashlib
import secrets
import urllib.parse
from datetime import datetime, timedelta

from flask import current_app

from app.extensions import db
from .models import MemberSmsCode
from . import settings as cfg

PHONE_RE = re.compile(r'^1[3-9]\d{9}$')

PURPOSE_LABELS = {
    'login': '登录',
    'reset': '重置密码',
    'bind': '绑定手机',
}


def valid_phone(phone):
    return bool(PHONE_RE.match(phone or ''))


def _int(key, default):
    try:
        return max(int(cfg.cfg(key)), 1)
    except (TypeError, ValueError):
        return default


def issue_code(phone, purpose='login', ip=''):
    """生成并发送验证码。返回 (ok: bool, error: str)。"""
    if not valid_phone(phone):
        return False, '手机号格式不正确'
    if purpose not in PURPOSE_LABELS:
        return False, '验证码用途无效'

    interval = _int('member_sms_send_interval', 60)
    daily_limit = _int('member_sms_daily_limit', 10)

    latest = MemberSmsCode.query.filter_by(phone=phone, purpose=purpose).order_by(
        MemberSmsCode.id.desc()).first()
    if latest and (datetime.now() - latest.created_at).total_seconds() < interval:
        wait = interval - int((datetime.now() - latest.created_at).total_seconds())
        return False, f'发送过于频繁，请 {wait} 秒后重试'

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = MemberSmsCode.query.filter(
        MemberSmsCode.phone == phone,
        MemberSmsCode.purpose == purpose,
        MemberSmsCode.created_at >= today_start,
    ).count()
    if sent_today >= daily_limit:
        return False, '今日发送次数已达上限，请明天再试'

    code = f'{secrets.randbelow(1000000):06d}'
    ttl = _int('member_sms_code_ttl', 300)
    row = MemberSmsCode(
        phone=phone,
        code_hash=MemberSmsCode.hash_code(phone, code),
        purpose=purpose,
        expires_at=datetime.now() + timedelta(seconds=ttl),
        ip=ip or '',
    )
    db.session.add(row)
    db.session.commit()

    try:
        _send(phone, code)
    except Exception as e:
        current_app.logger.exception('member sms send failed')
        return False, f'短信发送失败：{e}'
    return True, ''


def verify_code(phone, code, purpose='login', consume=True):
    """校验验证码：必须为该手机号+用途下最近一条、未使用、未过期。"""
    if not phone or not code:
        return False
    row = MemberSmsCode.query.filter_by(
        phone=phone, purpose=purpose, used=False
    ).order_by(MemberSmsCode.id.desc()).first()
    if row is None or row.is_expired:
        return False
    if not hmac.compare_digest(row.code_hash, MemberSmsCode.hash_code(phone, str(code).strip())):
        return False
    if consume:
        row.used = True
        db.session.commit()
    return True


# ============================================================
# 发送通道
# ============================================================

def _send(phone, code):
    provider = cfg.cfg('member_sms_provider') or 'log'
    if provider == 'aliyun':
        _send_aliyun(phone, code)
    elif provider == 'webhook':
        _send_webhook(phone, code)
    else:
        _send_log(phone, code)


def _send_log(phone, code):
    # 开发/测试环境：验证码直接进日志，不产生真实短信费用
    current_app.logger.info('[会员短信] phone=%s code=%s（日志通道，未真实发送）', phone, code)


def _percent_encode(s):
    # 阿里云 POP 签名要求 RFC3986：safe='~'
    return urllib.parse.quote(str(s), safe='~')


def _send_aliyun(phone, code):
    """阿里云短信 SendSms（RPC 风格，HMAC-SHA1 签名）。"""
    import requests

    key_id = cfg.cfg('member_sms_aliyun_key_id')
    key_secret = cfg.cfg('member_sms_aliyun_key_secret')
    sign_name = cfg.cfg('member_sms_aliyun_sign')
    template_code = cfg.cfg('member_sms_aliyun_template')
    if not all([key_id, key_secret, sign_name, template_code]):
        raise RuntimeError('阿里云短信参数未配置完整')

    params = {
        'AccessKeyId': key_id,
        'Action': 'SendSms',
        'Format': 'JSON',
        'RegionId': 'cn-hangzhou',
        'SignatureMethod': 'HMAC-SHA1',
        'SignatureNonce': secrets.token_hex(16),
        'SignatureVersion': '1.0',
        'Timestamp': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'Version': '2017-05-25',
        'PhoneNumbers': phone,
        'SignName': sign_name,
        'TemplateCode': template_code,
        'TemplateParam': '{"code":"%s"}' % code,
    }
    canonical = '&'.join(
        f'{_percent_encode(k)}={_percent_encode(v)}'
        for k, v in sorted(params.items())
    )
    string_to_sign = 'GET&%2F&' + _percent_encode(canonical)
    digest = hmac.new(
        (key_secret + '&').encode('utf-8'),
        string_to_sign.encode('utf-8'), hashlib.sha1
    ).digest()
    params['Signature'] = base64.b64encode(digest).decode('utf-8')

    resp = requests.get('https://dysmsapi.aliyuncs.com/', params=params, timeout=10)
    data = resp.json()
    if data.get('Code') != 'OK':
        raise RuntimeError(data.get('Message') or data.get('Code') or '阿里云返回异常')


def _send_webhook(phone, code):
    """通用 HTTP 短信接口：URL 中 {phone}/{code} 占位符替换。"""
    import requests

    url_tpl = cfg.cfg('member_sms_webhook_url')
    if not url_tpl:
        raise RuntimeError('通用短信接口地址未配置')
    url = url_tpl.replace('{phone}', phone).replace('{code}', code)
    method = (cfg.cfg('member_sms_webhook_method') or 'GET').upper()
    if method == 'POST':
        resp = requests.post(url, json={'phone': phone, 'code': code}, timeout=10)
    else:
        resp = requests.get(url, timeout=10)
    if resp.status_code >= 400:
        raise RuntimeError(f'接口返回 HTTP {resp.status_code}')
