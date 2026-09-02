"""自定义表单插件：提交消息通知（触发层）。

设计（v2.3.0 §4.5）：配置在核心，触发在插件。
  - 传输层（SMTP 邮件 / 企业微信 Webhook 发送）位于核心 app.utils.notify_utils，
    读取 notify_email_* / notify_wework_* 配置，未来其它插件可复用；
  - 本模块只负责「表单提交」这一触发场景：读取 form_notify_* 配置，
    组装 subject/html/markdown，调用核心传输函数。
"""
from datetime import datetime

from flask import current_app, request

from app.models.setting import Setting
from app.utils.notify_utils import send_email, send_wechat_webhook


def notify_form_submission(form_obj, submission_obj, fields, submit_page=None):
    """把一次表单提交推送给管理员（按 Setting 配置的渠道）。

    内容：提交时间、字段数据、访客IP、提交页面。
    submit_page：调用方已取好的 Referer/外链，优先用它。
    返回成功推送数。
    """
    if Setting.get('form_notify_enable') != 'on':
        return 0
    channels_raw = Setting.get('form_notify_channels') or ''
    channels = [c.strip() for c in channels_raw.split(',') if c.strip()]
    if not channels:
        return 0

    payload = _build_payload(form_obj, submission_obj, fields, submit_page=submit_page)

    ok_count = 0
    for ch in channels:
        try:
            if ch == 'email':
                if _push_email(payload):
                    ok_count += 1
            elif ch == 'wework':
                if _push_wework(payload):
                    ok_count += 1
        except Exception:
            current_app.logger.exception(f'notify via {ch} failed')
    return ok_count


def _build_payload(form_obj, submission_obj, fields, submit_page=None):
    rows = []
    for f in fields:
        # fields 可能是调用方传的 [(label, value)] 对，也可能是 Field 模型对象
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


def _push_email(payload):
    """构建邮件正文并调用核心传输层发送。"""
    receivers_raw = Setting.get('notify_email_receivers')
    receivers = [r.strip() for r in (receivers_raw or '').split(',') if '@' in r]
    if not receivers:
        return False
    sender_name = Setting.get('notify_email_sender_name') or '钟毓CMS表单通知'

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

    return send_email(subject=subject, html_content=html, to_addrs=receivers,
                      sender_display_name=sender_name)


def _push_wework(payload):
    """构建企业微信 markdown 并调用核心传输层发送。"""
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
    markdown = '\n'.join(lines)

    mentioned = Setting.get('notify_wework_mentioned_mobiles') or ''
    mobiles = [m.strip() for m in mentioned.split(',') if m.strip()]
    return send_wechat_webhook(markdown_content=markdown, mentioned_mobiles=mobiles)
