"""通用工具函数与模板过滤器注册。"""
from functools import wraps

from flask import request, redirect, url_for
from flask_login import current_user


def admin_required(func):
    """后台登录鉴权装饰器。"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('admin_auth.login', next=request.path))
        return func(*args, **kwargs)
    return wrapper


def log_login(username, result, message=''):
    """记录登录日志。"""
    from ..extensions import db
    from ..models.user import LoginLog
    log = LoginLog(
        username=username,
        ip=request.remote_addr or '',
        user_agent=request.user_agent.string[:255] if request.user_agent else '',
        result=result,
        message=message,
    )
    db.session.add(log)
    db.session.commit()


def register_template_filters(app):
    @app.template_filter('datetime')
    def format_datetime(value, fmt='%Y-%m-%d %H:%M:%S'):
        if not value:
            return ''
        if isinstance(value, str):
            return value
        return value.strftime(fmt)

    @app.template_filter('date')
    def format_date(value, fmt='%Y-%m-%d'):
        if not value:
            return ''
        if isinstance(value, str):
            return value
        return value.strftime(fmt)

    @app.template_filter('truncate_text')
    def truncate_text(value, length=50):
        if not value:
            return ''
        text = str(value)
        return text[:length] + '...' if len(text) > length else text
