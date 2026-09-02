"""通用消息传输层（v2.3.0）：邮件 SMTP + 企业微信群机器人 Webhook。

本模块只负责「发送」——读取 notify_email_* / notify_wework_* 配置并执行投递，
不关心业务语义（表单提交、其它插件通知等均可复用）。

业务触发层（如 plugins/form/notify.py）负责：
  - 读取业务级开关（form_notify_enable / form_notify_channels）
  - 组装 subject / html_content / markdown_content
  - 调用本模块 send_email / send_wechat_webhook
"""
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

from flask import current_app

from ..models.setting import Setting


# ============================================================
# 邮件传输
# ============================================================

def send_email(subject, html_content, to_addrs, sender_display_name=None):
    """通过配置的 SMTP 发送一封 HTML 邮件。

    参数：
      subject:             邮件主题
      html_content:        HTML 正文
      to_addrs:            收件人列表 [addr, ...]
      sender_display_name: 发件人显示名（缺省取 notify_email_sender_name）

    返回 True/False。无 SMTP 配置或发送异常均返回 False 并记日志。
    """
    host = Setting.get('notify_email_smtp_host')
    if not host or not to_addrs:
        return False
    try:
        port = int(Setting.get('notify_email_smtp_port', '465'))
    except ValueError:
        port = 465
    use_ssl = Setting.get('notify_email_smtp_ssl') == 'on'
    # notify_email_smtp_user=SMTP 登录账号(邮箱地址)，notify_email_smtp_password=密码
    user = Setting.get('notify_email_smtp_user')
    pwd = Setting.get('notify_email_smtp_password')
    sender_name = sender_display_name or Setting.get('notify_email_sender_name') or '钟毓CMS通知'
    sender_address = Setting.get('notify_email_sender_address') or user or to_addrs[0]

    msg = MIMEText(html_content, 'html', 'utf-8')
    msg['From'] = formataddr((str(Header(sender_name, 'utf-8')), sender_address))
    msg['To'] = ', '.join(to_addrs)
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
            smtp.sendmail(sender_address, to_addrs, msg.as_string())
        return True
    except Exception as e:
        current_app.logger.warning(f'send email failed: {e}')
        return False


# ============================================================
# 企业微信群机器人 Webhook 传输
# ============================================================

def send_wechat_webhook(markdown_content, mentioned_mobiles=None):
    """向配置的企业微信群机器人 Webhook 发送一条 markdown 消息。

    参数：
      markdown_content:    markdown 正文
      mentioned_mobiles:   @ 手机号列表（可选）

    返回 True/False。无 Webhook 配置或发送异常均返回 False 并记日志。
    """
    webhook = Setting.get('notify_wework_webhook')
    if not webhook or 'qyapi.weixin.qq.com' not in webhook:
        return False
    try:
        import requests
    except ImportError:
        return False

    data = {
        'msgtype': 'markdown',
        'markdown': {'content': markdown_content},
    }
    if mentioned_mobiles:
        data['markdown']['mentioned_mobile_list'] = mentioned_mobiles
    try:
        resp = requests.post(webhook, json=data, timeout=10)
        body = resp.json() if resp.content else {}
        return str(body.get('errcode', '')) == '0'
    except Exception as e:
        current_app.logger.warning(f'send wework failed: {e}')
        return False
