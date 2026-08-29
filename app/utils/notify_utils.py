"""模块7：表单提交消息通知（邮件 + 企业微信 Webhook）。"""
import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

from flask import current_app, request
from ..models.setting import Setting


# ============================================================
# 入口：前台表单保存成功后调用
# ============================================================

def notify_form_submission(form_obj, submission_obj, fields, submit_page=None):
    """把一次表单提交推送给管理员（按 Setting 配置的渠道）。

    内容：提交时间、字段数据、访客IP、提交页面。
    submit_page：如果调用方（如 frontend/views.py）已经取好 Referer/外链，优先用它。
    """
    if Setting.get('form_notify_enable') != 'on':
        return
    channels_raw = Setting.get('form_notify_channels') or ''
    channels = [c.strip() for c in channels_raw.split(',') if c.strip()]
    if not channels:
        return

    payload = _build_payload(form_obj, submission_obj, fields, submit_page=submit_page)

    ok_count = 0
    for ch in channels:
        try:
            if ch == 'email':
                if _send_email(payload):
                    ok_count += 1
            elif ch == 'wework':
                if _send_wework(payload):
                    ok_count += 1
        except Exception:
            current_app.logger.exception(f'notify via {ch} failed')
    return ok_count


def _build_payload(form_obj, submission_obj, fields, submit_page=None):
    rows = []
    for f in fields:
        # fields 可能是 notify_utils 调用方传的 [(label, value)] 对，也可能是 Field 模型对象
        is_tuple = isinstance(f, (tuple, list)) and len(f) == 2
        label = f[0] if is_tuple else (getattr(f, 'label', None) or getattr(f, 'field_key', str(f)))
        if is_tuple:
            val = f[1] or ''
        else:
            val = submission_obj.get_value(f.id) if hasattr(submission_obj, 'get_value') else ''
            if getattr(f, 'field_type', None) == 'file' and val:
                try:
                    val = f'[文件] {request.url_root.rstrip("/")}{val}'
                except Exception:
                    pass
        rows.append((label, val or ''))
    if submit_page:
        page = submit_page
    else:
        try:
            page = request.headers.get('Referer', '') or (request.url_root.rstrip('/') +
                                                                f'/form/{form_obj.slug}')
        except Exception:
            page = f'/form/{form_obj.slug}'
    return {
        'form_name': form_obj.name,
        'submit_time': submission_obj.created_at.strftime('%Y-%m-%d %H:%M:%S') if getattr(submission_obj, 'created_at', None) else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'ip': getattr(submission_obj, 'ip', None) or (request.remote_addr if request else ''),
        'page': page,
        'fields': rows,
    }


# ============================================================
# 邮件通知
# ============================================================

def _send_email(payload):
    host = Setting.get('notify_email_smtp_host')
    if not host:
        return False
    try:
        port = int(Setting.get('notify_email_smtp_port', '465'))
    except ValueError:
        port = 465
    use_ssl = Setting.get('notify_email_smtp_ssl') == 'on'
    # 与 admin/setting.py setting_notify 保存字段保持一致：
    # notify_email_smtp_user=SMTP 登录账号(邮箱地址)，notify_email_smtp_password=密码
    # notify_email_sender_address=发件地址（一般等于登录邮箱），notify_email_sender_name=发件人显示名
    user = Setting.get('notify_email_smtp_user')
    pwd = Setting.get('notify_email_smtp_password')
    receivers_raw = Setting.get('notify_email_receivers')
    receivers = [r.strip() for r in (receivers_raw or '').split(',') if '@' in r]
    if not receivers:
        return False
    sender_name = Setting.get('notify_email_sender_name') or '钟毓CMS表单通知'
    sender_address = Setting.get('notify_email_sender_address') or user or receivers[0]
    subject = f'[表单提醒] {payload["form_name"]} 有新的提交'

    lines = [f'<h3>{subject}</h3>',
             f'<p><b>表单：</b>{payload["form_name"]}</p>',
             f'<p><b>提交时间：</b>{payload["submit_time"]}</p>',
             f'<p><b>访客 IP：</b>{payload["ip"]}</p>',
             f'<p><b>提交页面：</b><a href="{payload["page"]}">{payload["page"]}</a></p>',
             '<h4>字段数据</h4><table border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse;">']
    for k, v in payload['fields']:
        lines.append(f'<tr><td style="background:#f5f5f5;width:140px;">{k}</td><td>{v}</td></tr>')
    lines.append('</table>')
    html = '\n'.join(lines)

    msg = MIMEText(html, 'html', 'utf-8')
    msg['From'] = formataddr((str(Header(sender_name, 'utf-8')), sender_address))
    msg['To'] = ', '.join(receivers)
    msg['Subject'] = Header(subject, 'utf-8')

    try:
        if use_ssl:
            smtp = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            smtp = smtplib.SMTP(host, port, timeout=15)
            smtp.starttls()
        with smtp:
            if user and pwd:
                smtp.login(user, pwd)
            smtp.sendmail(sender_address, receivers, msg.as_string())
        return True
    except Exception as e:
        current_app.logger.warning(f'send email failed: {e}')
        return False


# ============================================================
# 企业微信群机器人 Webhook
# ============================================================

def _send_wework(payload):
    webhook = Setting.get('notify_wework_webhook')
    if not webhook or 'qyapi.weixin.qq.com' not in webhook:
        return False
    try:
        import requests
    except ImportError:
        return False

    lines = [f'## 📋 [{payload["form_name"]}] 有新的表单提交',
             f'- **提交时间**：{payload["submit_time"]}',
             f'- **访客IP**：{payload["ip"]}',
             f'- **提交页面**：[点击查看]({payload["page"]})',
             '### 字段数据：']
    for k, v in payload['fields']:
        # markdown 里限制换行
        vv = str(v).replace('\n', ' ').strip() or '-'
        if len(vv) > 80:
            vv = vv[:77] + '...'
        lines.append(f'- **{k}**：{vv}')
    mentioned = Setting.get('notify_wework_mentioned_mobiles') or ''
    mobiles = [m.strip() for m in mentioned.split(',') if m.strip()]

    data = {
        'msgtype': 'markdown',
        'markdown': {'content': '\n'.join(lines)},
    }
    if mobiles:
        data['markdown']['mentioned_mobile_list'] = mobiles
    try:
        resp = requests.post(webhook, json=data, timeout=10)
        body = resp.json() if resp.content else {}
        return str(body.get('errcode', '')) == '0'
    except Exception as e:
        current_app.logger.warning(f'send wework failed: {e}')
        return False
