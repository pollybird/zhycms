"""站点 SSL 证书到期检查（只读）。

只读取 Let's Encrypt 证书文件并计算剩余天数，不发起网络请求、不调用
certbot、不修改服务器配置。证书根目录可通过 `SSL_CERT_ROOT` 配置，
便于自定义部署与测试。
"""
import logging
import os
import ssl
from datetime import datetime, time

from flask import current_app

from ..models.setting import Setting

logger = logging.getLogger(__name__)

STATUS_OK = 'ok'
STATUS_EXPIRING = 'expiring'
STATUS_EXPIRED = 'expired'
STATUS_MISSING = 'missing'
STATUS_INVALID = 'invalid'

DEFAULT_WARN_DAYS = 10
MAX_WARN_DAYS = 90

# 审计 detail 中用于识别证书巡检事件的标记，供同日去重查询使用
AUDIT_EVENT = 'ssl_expiry'


def _cert_root():
    return current_app.config.get(
        'SSL_CERT_ROOT', '/etc/letsencrypt/live') or '/etc/letsencrypt/live'


def get_warn_days():
    """剩余天数告警阈值：默认 10，非法值回退 10，范围 1-90。"""
    try:
        days = int(Setting.get('ssl_expiry_warn_days', str(DEFAULT_WARN_DAYS)))
    except (TypeError, ValueError):
        return DEFAULT_WARN_DAYS
    if days < 1:
        return 1
    if days > MAX_WARN_DAYS:
        return MAX_WARN_DAYS
    return days


def check_site_certificate(site, base_domain=None, warn_days=None):
    """检查单个站点主主机名的证书状态。

    返回 {site_id, host, configured, expires_at, days_left, status, error}。
    无域名/子域、证书缺失或解析失败均降级为状态值，不抛异常。
    """
    from .site_deploy import site_hostnames

    hosts = site_hostnames(site, base_domain)
    host = hosts[0] if hosts else None
    result = {
        'site_id': getattr(site, 'id', None),
        'site_name': getattr(site, 'name', '') or '',
        'host': host,
        'configured': False,
        'expires_at': None,
        'days_left': None,
        'status': STATUS_MISSING,
        'error': None,
    }
    if not host:
        return result

    cert_path = os.path.join(_cert_root(), host, 'cert.pem')
    if not os.path.isfile(cert_path):
        return result

    result['configured'] = True
    try:
        decoded = ssl._ssl._test_decode_cert(cert_path)
        raw = decoded.get('notAfter')
        expires = datetime.strptime(raw, '%b %d %H:%M:%S %Y %Z')
    except (OSError, ValueError, AttributeError, TypeError) as e:
        result['status'] = STATUS_INVALID
        result['error'] = str(e)
        logger.warning('读取证书 %s 失败：%s', cert_path, e)
        return result

    days_left = (expires - datetime.now()).days
    result['expires_at'] = expires.strftime('%Y-%m-%d %H:%M:%S')
    result['days_left'] = days_left
    limit = warn_days if warn_days is not None else get_warn_days()
    if days_left < 0:
        result['status'] = STATUS_EXPIRED
    elif days_left <= limit:
        result['status'] = STATUS_EXPIRING
    else:
        result['status'] = STATUS_OK
    return result


def check_expiring_certificates(warn_days=None, sites=None):
    """批量检查站点证书，逐站隔离异常。

    返回 {checked, warn_days, results, expiring, expired, missing, invalid, errors}。
    """
    from ..models.site import Site
    from ..models.setting import Setting

    limit = warn_days if warn_days is not None else get_warn_days()
    base_domain = Setting.get('site_url') or ''
    if sites is None:
        sites = Site.active_sites()

    results = []
    errors = []
    for site in sites:
        try:
            results.append(check_site_certificate(
                site, base_domain=base_domain, warn_days=limit))
        except Exception as e:
            errors.append({'site_id': getattr(site, 'id', None), 'error': str(e)})
            logger.warning('站点 %s 证书检查失败：%s',
                           getattr(site, 'id', '?'), e)

    def _pick(status):
        return [r for r in results if r['status'] == status]

    return {
        'checked': len(results),
        'warn_days': limit,
        'results': results,
        'expiring': _pick(STATUS_EXPIRING),
        'expired': _pick(STATUS_EXPIRED),
        'missing': _pick(STATUS_MISSING),
        'invalid': _pick(STATUS_INVALID),
        'errors': errors,
    }


def _already_notified(site_id):
    """同站同日只提醒一次：先查缓存，缓存异常时查当天审计。"""
    today = datetime.now().date()
    cache_key = f'ssl-expiry:{site_id}:{today.strftime("%Y%m%d")}'
    try:
        from ..extensions import cache
        if cache.get(cache_key):
            return True
        cache.set(cache_key, 1, timeout=24 * 3600)
        return False
    except Exception as e:
        logger.debug('证书提醒缓存不可用，改用审计去重：%s', e)

    from ..models.audit import AuditLog, MODULE_SITE
    start = datetime.combine(today, time.min)
    try:
        return AuditLog.query.filter(
            AuditLog.module == MODULE_SITE,
            AuditLog.target_id == str(site_id),
            AuditLog.created_at >= start,
            AuditLog.detail.like(f'%{AUDIT_EVENT}%'),
        ).first() is not None
    except Exception as e:
        logger.debug('证书提醒审计去重查询失败：%s', e)
        return False


def _send_notifications(items):
    """按配置渠道发送提醒；未配置渠道时静默跳过。"""
    if not items:
        return
    if Setting.get('ssl_expiry_notify_enable', 'on') != 'on':
        return
    channels = {
        c.strip() for c in
        (Setting.get('ssl_expiry_notify_channels', 'email,wework') or '').split(',')
        if c.strip()
    }
    if not channels:
        return

    lines = []
    for r in items:
        days = r.get('days_left')
        if days is None:
            continue
        if days < 0:
            state = f'已过期 {-days} 天'
        else:
            state = f'剩余 {days} 天'
        lines.append(f'- {r.get("site_name") or r.get("site_id")}（{r.get("host")}）'
                     f'：{state}，到期时间 {r.get("expires_at") or "未知"}')
    if not lines:
        return

    if 'email' in channels:
        try:
            from ..utils.notify_utils import send_email
            receivers = [a.strip() for a in (
                Setting.get('notify_email_receivers') or '').split(',') if a.strip()]
            if receivers:
                send_email(
                    '[ZhyCMS] 站点证书即将到期',
                    '<p>以下站点证书剩余天数已达到告警阈值，请及时处理：</p>'
                    + '<br>'.join(lines),
                    receivers)
        except Exception as e:
            logger.warning('证书到期邮件提醒发送失败：%s', e)

    if 'wework' in channels:
        try:
            from ..utils.notify_utils import send_wechat_webhook
            send_wechat_webhook('**站点证书到期提醒**\n\n' + '\n'.join(lines))
        except Exception as e:
            logger.warning('证书到期企业微信提醒发送失败：%s', e)


def run_daily_check(sites=None, notify=True, warn_days=None):
    """每日巡检：告警临期/过期证书，写审计并按渠道提醒。

    同站同日只提醒一次；单个站点失败不影响其他站点。
    """
    from ..models.audit import AuditLog, OP_UPDATE, MODULE_SITE

    summary = check_expiring_certificates(warn_days=warn_days, sites=sites)
    alert_items = summary['expiring'] + summary['expired']
    notified = []
    for item in alert_items:
        site_id = item['site_id']
        logger.warning('站点 %s 证书 %s 状态=%s 剩余 %s 天',
                       site_id, item['host'], item['status'],
                       item['days_left'])
        if _already_notified(site_id):
            continue
        AuditLog.record(
            OP_UPDATE, MODULE_SITE, target_id=site_id,
            target_name=item.get('site_name') or item.get('host') or '',
            detail={
                'event': AUDIT_EVENT,
                'domain': item['host'],
                'expires_at': item['expires_at'],
                'days_left': item['days_left'],
                'status': item['status'],
            },
            site_id=site_id or 0,
        )
        notified.append(item)

    if notify and notified:
        _send_notifications(notified)
    summary['notified'] = notified
    return summary
