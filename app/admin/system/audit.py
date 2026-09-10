"""模块2：全量操作审计日志 —— 后台列表查看、关键词搜索、时间筛选、日志导出、定时清理。"""
import io
import csv
from datetime import datetime, timedelta

from flask import (
    render_template, redirect, url_for, request, flash, abort, send_file, current_app
)
from flask_babel import gettext as _gettext
from flask_login import current_user

from ...extensions import db
from ...models.audit import (
    AuditLog, OP_TYPE_CHOICES,
    MODULE_USER, MODULE_ROLE, MODULE_COLUMN, MODULE_ARTICLE, MODULE_FRAGMENT,
    MODULE_FORM, MODULE_FORM_SUBMISSION, MODULE_SETTING,
    MODULE_AUDIT, MODULE_BACKUP, MODULE_UPLOAD, MODULE_OTHER,
    OP_LOGIN, OP_LOGOUT, OP_CREATE, OP_UPDATE, OP_DELETE, OP_PUBLISH, OP_ARCHIVE,
    OP_REVIEW_PASS, OP_REVIEW_REJECT, OP_BATCH, OP_ROLLBACK, OP_CONFIG_CHANGE,
    OP_USER_MANAGE, OP_BACKUP_CREATE, OP_BACKUP_RESTORE, OP_EXPORT, OP_UPLOAD, OP_OTHER,
)
from ...models.setting import Setting
from ...utils.helpers import permission_required, audit_log
from .. import admin_bp


MODULE_CHOICES = [
    (MODULE_USER, '用户管理'),
    (MODULE_ROLE, '角色权限'),
    (MODULE_COLUMN, '栏目管理'),
    (MODULE_ARTICLE, '文章管理'),
    (MODULE_FRAGMENT, '碎片管理'),
    # 友情链接模块已迁至 friend_link 插件（audit_modules 声明，启用后出现在筛选下拉）
    (MODULE_FORM, '表单配置'),
    (MODULE_FORM_SUBMISSION, '表单提交'),
    (MODULE_SETTING, '系统设置'),
    (MODULE_AUDIT, '审计日志'),
    (MODULE_BACKUP, '备份运维'),
    (MODULE_UPLOAD, '文件上传'),
    (MODULE_OTHER, '其他'),
]

OP_TYPE_LABELS = dict(OP_TYPE_CHOICES)
MODULE_LABELS = dict(MODULE_CHOICES)


@admin_bp.route('/audit-logs')
@permission_required('system:audit_log')
def audit_index():
    page = max(int(request.args.get('page', 1)), 1)
    keyword = (request.args.get('keyword') or '').strip()
    module = request.args.get('module', '')
    op_type = request.args.get('op_type', '')
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    username = (request.args.get('username') or '').strip()

    query = AuditLog.query
    if keyword:
        like = f'%{keyword}%'
        query = query.filter(db.or_(
            AuditLog.detail.like(like),
            AuditLog.target_name.like(like),
            AuditLog.username.like(like),
            AuditLog.ip.like(like),
        ))
    if username:
        query = query.filter(AuditLog.username.like(f'%{username}%'))
    if module:
        query = query.filter_by(module=module)
    if op_type:
        query = query.filter_by(op_type=op_type)
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(AuditLog.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(AuditLog.created_at < dt_to)
        except ValueError:
            pass

    pagination = query.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=30, error_out=False
    )
    # 总条数概览
    total_count = query.order_by(None).count()
    # 详情人性化翻译用的 ID→名称映射
    from ...models.rbac import Role
    from ...models.column import Column
    audit_maps = {
        'roles': {r.id: r.name for r in Role.query.all()},
        'columns': {c.id: c.name for c in Column.query.filter_by(is_deleted=False).all()},
    }
    # v2.2.0：模块筛选下拉追加启用插件的审计模块（如 product→产品管理）
    try:
        from ...plugin_system import plugin_audit_modules
        module_choices = list(MODULE_CHOICES) + list(plugin_audit_modules())
    except Exception:
        module_choices = MODULE_CHOICES
    return render_template(
        'admin/audit/index.html',
        logs=pagination.items, pagination=pagination,
        keyword=keyword, module=module, op_type=op_type,
        date_from=date_from, date_to=date_to, username=username,
        module_choices=module_choices, op_type_choices=OP_TYPE_CHOICES,
        total_count=total_count, audit_maps=audit_maps,
    )


@admin_bp.route('/audit-logs/export')
@permission_required('system:audit_log')
def audit_export():
    """导出审计日志为 CSV（Excel 可直接打开，UTF-8 BOM）。"""
    keyword = (request.args.get('keyword') or '').strip()
    module = request.args.get('module', '')
    op_type = request.args.get('op_type', '')
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    username = (request.args.get('username') or '').strip()
    fmt = (request.args.get('format') or 'csv').lower()

    query = AuditLog.query
    if keyword:
        like = f'%{keyword}%'
        query = query.filter(db.or_(
            AuditLog.detail.like(like), AuditLog.target_name.like(like),
            AuditLog.username.like(like), AuditLog.ip.like(like),
        ))
    if username:
        query = query.filter(AuditLog.username.like(f'%{username}%'))
    if module:
        query = query.filter_by(module=module)
    if op_type:
        query = query.filter_by(op_type=op_type)
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(AuditLog.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(AuditLog.created_at < dt_to)
        except ValueError:
            pass

    # 最多导出 50,000 行，避免内存爆炸
    logs = query.order_by(AuditLog.created_at.desc()).limit(50000).all()

    if fmt == 'csv' or True:
        buf = io.StringIO()
        buf.write('\ufeff')  # UTF-8 BOM，Excel 正确识别中文
        writer = csv.writer(buf)
        writer.writerow(['操作时间', '账号', '昵称', '操作IP', '操作类型', '所属模块',
                         '目标ID', '目标名称', 'User-Agent', '操作详情'])
        for log in logs:
            writer.writerow([
                log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else '',
                log.username or '',
                log.nickname or '',
                log.ip or '',
                OP_TYPE_LABELS.get(log.op_type, log.op_type or ''),
                MODULE_LABELS.get(log.module, log.module or ''),
                log.target_id or '',
                log.target_name or '',
                (log.user_agent or '')[:200],
                (log.detail or '')[:5000],
            ])
        data = buf.getvalue().encode('utf-8')
        filename = f'audit_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        audit_log(OP_EXPORT, MODULE_AUDIT, None, None,
                  {'rows': len(logs), 'filename': filename, 'filters': {
                      'keyword': keyword, 'module': module, 'op_type': op_type,
                      'date_from': date_from, 'date_to': date_to, 'username': username
                  }})
        return send_file(
            io.BytesIO(data),
            mimetype='text/csv; charset=utf-8',
            as_attachment=True,
            download_name=filename,
        )


@admin_bp.route('/audit-logs/clean', methods=['POST'])
@permission_required('system:audit_log')
def audit_clean():
    """手动清理过期审计日志。"""
    keep_days_raw = request.form.get('keep_days') or ''
    try:
        keep_days = int(keep_days_raw)
    except (TypeError, ValueError):
        try:
            keep_days = int(Setting.get('audit_log_keep_days', '90'))
        except ValueError:
            keep_days = 90
    if keep_days <= 0:
        flash(_gettext('保留天数必须为正整数'), 'danger')
        return redirect(url_for('admin.audit_index'))
    count = AuditLog.clean_expired(keep_days=keep_days)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        count = 0
    flash(_gettext('已清理 {0} 天前的审计日志，共删除 {1} 条记录').format(keep_days, count), 'success')
    audit_log(OP_BATCH, MODULE_AUDIT, None, None,
              {'action': 'clean_expired', 'keep_days': keep_days, 'deleted_count': count})
    return redirect(url_for('admin.audit_index'))
