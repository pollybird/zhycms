"""管理后台首页：统计卡片 + 异常登录提醒 + 系统监控。
升级点：
  - 异常登录提醒横幅（首次加载后弹出，一次性 session 键）
  - 工作流待审核文章计数卡片
  - 系统监控基础数据（磁盘/数据库/运行时长）
"""
from flask import render_template, request, session, flash
from flask_login import current_user

from ..extensions import db
from ..models.user import LoginLog, User
from ..models.column import Column
from ..models.article import Article
from ..models.workflow import STATUS_REVIEW
from ..models.audit import AuditLog
from ..utils.helpers import admin_required
from ..utils.backup_utils import system_monitor_stats
from ..plugin_system import plugin_enabled
from . import admin_bp


from flask_babel import gettext as _gettext
def _pending_form_submissions():
    """待处理表单提交数（表单插件禁用时返回 0）。

    自定义表单 v2.3.0 起转为内置插件 plugins/form，表单模型不再属于核心，
    故此处按插件启用状态懒加载，禁用时仪表盘不展示该计数。
    """
    if not plugin_enabled('form'):
        return 0
    try:
        from plugins.form.models import FormSubmission
        return FormSubmission.query.filter_by(is_deleted=False, is_read=False).count()
    except Exception:
        return 0


@admin_bp.route('/')
@admin_required
def dashboard():
    # 异常登录提醒横幅（session 中一次性读取）
    abnormal = session.pop('login_abnormal_alert', None)
    if abnormal:
        city = abnormal.get('city') or '未知地区'
        ip = abnormal.get('ip') or '未知IP'
        tm = abnormal.get('time') or ''
        flash(_gettext('检测到本次登录可能为异地登录（城市：{0}，IP：{1}，时间：{2}）。若不是本人操作请立即修改密码并联系超级管理员。').format(city, ip, tm), 'warning')

    stats = {
        'users': User.query.filter_by(is_deleted=False).count(),
        'columns': Column.query.filter_by(is_deleted=False).count(),
        'articles': Article.query.filter_by(is_deleted=False).count(),
        'articles_pending_review': Article.query.filter_by(
            is_deleted=False, status=STATUS_REVIEW
        ).count(),
        'pending_submissions': _pending_form_submissions(),
        'recent_logs': LoginLog.query.order_by(LoginLog.created_at.desc()).limit(8).all(),
        'recent_audits': AuditLog.query.order_by(AuditLog.created_at.desc()).limit(10).all(),
    }
    # 仪表盘审计详情中文化的 ID→名称映射（与审计列表页同款）
    from ..models.rbac import Role
    dashboard_audit_maps = {
        'roles': {r.id: r.name for r in Role.query.all()},
        'columns': {c.id: c.name for c in Column.query.filter_by(is_deleted=False).all()},
    }
    try:
        monitor = system_monitor_stats()
    except Exception:
        monitor = None
    return render_template('admin/dashboard.html', stats=stats, monitor=monitor,
                           dashboard_audit_maps=dashboard_audit_maps)
