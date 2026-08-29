"""通用工具函数与模板过滤器注册 + RBAC 权限装饰器 + 审计日志快捷方法。"""
from functools import wraps
import json
from datetime import datetime

from flask import request, redirect, url_for, abort, flash, current_app
from flask_login import current_user


# ============================================================
# 后台通用鉴权
# ============================================================

def admin_required(func):
    """后台登录鉴权装饰器（旧名保留，兼容）；实际做登录 + 账号启用状态校验。"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('admin_auth.login', next=request.path))
        # 账号被禁用则踢下线
        u = current_user
        if getattr(u, 'is_deleted', False) or (hasattr(u, 'is_active_flag') and not u.is_active_flag):
            from flask_login import logout_user
            logout_user()
            flash('账号已被禁用，请联系超级管理员', 'warning')
            return redirect(url_for('admin_auth.login'))
        return func(*args, **kwargs)
    return wrapper


def permission_required(perm_code, column_id_arg=None):
    """RBAC 权限校验装饰器。

    - perm_code: 权限点 code，见 app.models.rbac.PERMISSION_DEFS
    - column_id_arg: 若校验「栏目专属权限」，传入函数参数中的栏目 ID 形参名（字符串）；
      装饰器会从 kwargs 或 request.form/args 中尝试读取该值并调用 current_user.can_access_column()
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('admin_auth.login', next=request.path))
            u = current_user
            if getattr(u, 'is_deleted', False) or (hasattr(u, 'is_active_flag') and not u.is_active_flag):
                from flask_login import logout_user
                logout_user()
                flash('账号已被禁用', 'warning')
                return redirect(url_for('admin_auth.login'))

            # 超级管理员直接放行
            if getattr(u, 'is_super', False):
                return func(*args, **kwargs)

            # 校验权限
            if not u.has_permission(perm_code):
                abort(403)

            # 栏目专属权限校验（content_* 类路由需要）
            if column_id_arg:
                cid = kwargs.get(column_id_arg)
                if cid is None:
                    cid = request.values.get(column_id_arg)
                if cid is not None:
                    try:
                        cid_int = int(cid)
                    except (TypeError, ValueError):
                        cid_int = None
                    if cid_int is not None and not u.can_access_column(cid_int):
                        abort(403)

            return func(*args, **kwargs)
        return wrapper
    return decorator


# ============================================================
# 登录日志
# ============================================================

def log_login(username, result, message='', user_id=None, city=None):
    """记录登录日志（模块5：扩展 user_id 与 city 字段）。"""
    from ..extensions import db
    from ..models.user import LoginLog
    log = LoginLog(
        username=username,
        user_id=user_id,
        ip=request.remote_addr or '',
        city=city,
        user_agent=request.user_agent.string[:255] if request.user_agent else '',
        result=result,
        message=message,
    )
    db.session.add(log)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


# ============================================================
# 审计日志快捷方法（供各模块调用）
# ============================================================

def audit_log(op_type, module, target_id=None, target_name=None, detail=None):
    """写入一条审计日志。参数定义见 models.audit.AuditLog.record。"""
    from ..models.audit import AuditLog
    try:
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False, default=str)
        AuditLog.record(
            op_type=op_type, module=module,
            target_id=target_id, target_name=target_name, detail=detail,
        )
    except Exception:
        current_app.logger.exception('write audit log failed')


# ============================================================
# 缓存清除（模块8：内容变更时自动清相关页面缓存）
# ============================================================

def clear_content_cache(column_id=None, article_id=None):
    """内容新增/修改/删除/发布后，清除前台首页、栏目页、文章页相关缓存。"""
    from ..extensions import cache
    from ..models.setting import Setting
    if Setting.get('cache_enable') != 'on':
        return
    keys = []
    # 首页
    keys.append('frontend/index')
    if column_id:
        keys.append(f'frontend/column/{column_id}')
    if article_id:
        keys.append(f'frontend/article/{article_id}')
    for k in keys:
        try:
            cache.delete(k)
        except Exception:
            pass
    # 简单起见，直接清整站缓存（覆盖 sitemap 等关联）
    try:
        cache.clear()
    except Exception:
        pass


# ============================================================
# 模板过滤器
# ============================================================

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

    @app.template_filter('status_label')
    def status_label(value):
        """工作流状态转中文字典。"""
        from ..models.workflow import STATUS_CHOICES
        for k, v in STATUS_CHOICES:
            if k == value:
                return v
        return value or ''

    @app.template_filter('filesize')
    def filesize(num):
        """字节数转可读大小。"""
        try:
            num = int(num or 0)
        except (TypeError, ValueError):
            return '0 B'
        step = 1024
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if num < step:
                return f'{num:.1f} {unit}' if unit != 'B' else f'{num} {unit}'
            num /= step
        return f'{num:.1f} PB'

    @app.template_filter('op_type_label')
    def op_type_label(code):
        from ..models.audit import OP_TYPE_CHOICES
        for k, v in OP_TYPE_CHOICES:
            if k == code:
                return v
        return code or ''
