"""前台会员会话与访问控制。

独立于后台管理员的 Flask-Login 会话（session['_user_id']）：
会员登录态使用独立 session 键，两套登录互不影响。
"""
from functools import wraps

from flask import session, g, request, redirect, url_for, flash
from flask_babel import gettext as _gettext

from app.extensions import db
from .models import Member

SESSION_KEY = 'member_id'


def login_member(member, remember=False):
    """建立前台会员登录态。"""
    session[SESSION_KEY] = member.id
    session.permanent = bool(remember)


def logout_member():
    session.pop(SESSION_KEY, None)


def current_member():
    """返回当前登录会员（请求级缓存）；未登录/已禁用/已删除返回 None。"""
    if not session.get(SESSION_KEY):
        return None
    if hasattr(g, '_member'):
        return g._member
    member = db.session.get(Member, session[SESSION_KEY])
    if member is None or member.is_deleted or not member.is_enabled:
        session.pop(SESSION_KEY, None)
        g._member = None
        return None
    g._member = member
    return member


def is_authenticated():
    return current_member() is not None


def login_url():
    """登录页地址（供核心前台守卫跳转）。"""
    return url_for('member_frontend.login')


def member_required(view):
    """前台会员登录守卫：未登录跳登录页并回跳。"""
    @wraps(view)
    def wrapper(*args, **kwargs):
        member = current_member()
        if member is None:
            flash(_gettext('请先登录后再访问该页面'), 'warning')
            return redirect(url_for('member_frontend.login', next=request.path))
        return view(*args, **kwargs)
    return wrapper
