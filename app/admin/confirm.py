"""危险操作（卸载插件 / 删除主题）二次确认：图形验证码。

前端流程：点击卸载/删除按钮 → 弹出警告模态框（含验证码图片，点击可刷新）
→ 输入验证码 → 提交 POST → 后端 verify_delete_captcha() 校验并消费。
验证码独立于登录验证码（session 键不同），互不干扰。
"""
from flask import make_response, request, session

from ..utils.captcha import generate_captcha
from ..utils.helpers import permission_required
from . import admin_bp

SESSION_KEY = 'delete_captcha'


@admin_bp.route('/captcha/delete-confirm')
@permission_required('system:settings')
def delete_captcha_image():
    """输出卸载/删除确认用验证码图片（每次请求生成新码）。"""
    code, png = generate_captcha()
    session[SESSION_KEY] = code
    resp = make_response(png)
    resp.headers['Content-Type'] = 'image/png'
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


def verify_delete_captcha():
    """校验并消费删除确认验证码。正确返回 None，错误返回提示信息。"""
    given = (request.form.get('captcha') or '').strip().lower()
    expected = (session.get(SESSION_KEY) or '').lower()
    session.pop(SESSION_KEY, None)  # 一次性：无论对错都作废，防重放
    if not expected:
        return '验证码已过期，请重新打开确认框操作'
    if not given or given != expected:
        return '验证码错误，请重试'
    return None
