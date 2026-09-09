"""招聘插件：后台管理（岗位 CRUD + 求职申请处理）。

路由挂在核心 admin_bp 上（endpoint 归入 admin.*）；未启用插件时全部 404，
菜单本就隐藏。权限：recruit:manage 单权限点管理岗位与申请。
"""
from datetime import datetime
from functools import wraps

from flask import (render_template, redirect, url_for, request, flash, abort,
                   send_file, current_app)

from flask_babel import gettext as _gettext
from app.extensions import db
from app.admin import admin_bp
from app.models.audit import OP_CREATE, OP_UPDATE, OP_DELETE, OP_BATCH
from app.utils.helpers import permission_required, audit_log
from app.utils.i18n_content import get_available_locales, get_default_locale

from .models import RecruitJob, RecruitApplication, RecruitJobTranslation
from .frontend_routes import resume_abs_path

AUDIT_MODULE = 'recruit'


# ============================================================
# 守卫与小工具
# ============================================================

def _gate(view):
    """插件启用守卫：未启用 → 404。"""
    @wraps(view)
    def wrapper(*args, **kwargs):
        from app.plugin_system import plugin_enabled
        if not plugin_enabled('recruit'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def _to_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _parse_deadline(raw):
    """解析 datetime-local 输入（YYYY-MM-DDTHH:MM）；空返回 None（长期有效）。

    非法输入抛 ValueError，由调用方 flash 提示。
    """
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError(raw)


# ============================================================
# 岗位管理
# ============================================================

@admin_bp.route('/recruit/jobs')
@_gate
@permission_required('recruit:manage')
def recruit_job_index():
    page = max(_to_int(request.args.get('page'), 1), 1)
    keyword = (request.args.get('keyword') or '').strip()
    status = request.args.get('status', '')

    query = RecruitJob.query.filter_by(is_deleted=False)
    if keyword:
        query = query.filter(RecruitJob.title.like(f'%{keyword}%'))
    if status == 'open':
        query = query.filter((RecruitJob.deadline.is_(None))
                             | (RecruitJob.deadline > datetime.now()))
    elif status == 'expired':
        query = query.filter(RecruitJob.deadline.isnot(None),
                             RecruitJob.deadline <= datetime.now())
    elif status == 'disabled':
        query = query.filter_by(is_enabled=False)

    pagination = query.order_by(
        RecruitJob.sort_order.desc(), RecruitJob.id.desc()
    ).paginate(page=page, per_page=15, error_out=False)
    return render_template('recruit/index.html',
                           jobs=pagination.items, pagination=pagination,
                           keyword=keyword, status=status)


@admin_bp.route('/recruit/jobs/create', methods=['GET', 'POST'])
@_gate
@permission_required('recruit:manage')
def recruit_job_create():
    if request.method == 'POST':
        job = _save_job(None)
        if job is None:
            return redirect(url_for('admin.recruit_job_create'))
        return redirect(url_for('admin.recruit_job_edit', jid=job.id))
    return render_template('recruit/form.html', job=None,
                           trans_locales=[l for l in get_available_locales()
                                          if l != get_default_locale()],
                           default_locale=get_default_locale())


@admin_bp.route('/recruit/jobs/<int:jid>/edit', methods=['GET', 'POST'])
@_gate
@permission_required('recruit:manage')
def recruit_job_edit(jid):
    job = RecruitJob.query.get_or_404(jid)
    if job.is_deleted:
        abort(404)
    if request.method == 'POST':
        if _save_job(job) is None:
            return redirect(url_for('admin.recruit_job_edit', jid=jid))
        return redirect(url_for('admin.recruit_job_edit', jid=jid))
    return render_template('recruit/form.html', job=job,
                           trans_locales=[l for l in get_available_locales()
                                          if l != get_default_locale()],
                           default_locale=get_default_locale())


def _save_job(job):
    """岗位表单保存（新增/编辑共用）。失败 flash 并返回 None。"""
    from flask_login import current_user

    is_new = job is None
    if is_new:
        job = RecruitJob()

    title = (request.form.get('title') or '').strip()
    if not title:
        flash(_gettext('岗位名称必填'), 'danger')
        return None
    try:
        deadline = _parse_deadline(request.form.get('deadline'))
    except ValueError:
        flash(_gettext('招聘截止时间格式不正确'), 'danger')
        return None

    job.title = title
    job.department = (request.form.get('department') or '').strip()[:100] or None
    job.location = (request.form.get('location') or '').strip()[:200] or None
    job.salary = (request.form.get('salary') or '').strip()[:100] or None
    job.headcount = max(_to_int(request.form.get('headcount'), 1), 0)
    job.description = request.form.get('description') or ''
    job.deadline = deadline
    job.is_enabled = (request.form.get('is_enabled') == 'on')
    job.sort_order = _to_int(request.form.get('sort_order'), 0)
    if is_new:
        job.created_by = current_user.id
        db.session.add(job)
        db.session.flush()   # 先取 id，翻译表外键依赖

    # v2.5.0：保存各语种翻译（非默认语言）
    _save_job_translations(job)

    db.session.commit()

    audit_log(OP_CREATE if is_new else OP_UPDATE, AUDIT_MODULE,
              job.id, job.title,
              {'action': '岗位', 'deadline': job.deadline.strftime('%Y-%m-%d %H:%M')
               if job.deadline else '长期有效'})
    # v2.5.2：同步全站搜索索引（下架时提供者返回 None，自动移出索引）
    from app.utils.search import reindex_object
    reindex_object('recruit_job', job.id)
    flash(_gettext('岗位已保存'), 'success')
    return job


def _save_job_translations(job):
    """保存岗位各语种翻译（v2.5.0；v2.5.2 增加部门/地点/薪资）。

    表单字段命名：{field}_{locale}，如 title_en / description_en / department_en。
    非默认语言且岗位名称非空 → upsert 翻译记录；名称为空 → 删除该翻译（fallback 默认语言）。
    department/location/salary 翻译留空即回退主表默认语言字段。
    """
    default_locale = get_default_locale()
    locales = [l for l in get_available_locales() if l != default_locale]
    if not locales:
        return

    existing = {tr.locale: tr for tr in job.translations}

    for loc in locales:
        tr_title = (request.form.get(f'title_{loc}') or '').strip()
        if not tr_title:
            # 空名称：删除该翻译（fallback 默认语言）
            if loc in existing:
                db.session.delete(existing[loc])
            continue
        tr = existing.get(loc)
        if tr is None:
            tr = RecruitJobTranslation(job_id=job.id, locale=loc)
            db.session.add(tr)
        tr.title = tr_title
        tr.description = request.form.get(f'description_{loc}') or ''
        tr.department = (request.form.get(f'department_{loc}')
                         or '').strip()[:100] or None
        tr.location = (request.form.get(f'location_{loc}')
                       or '').strip()[:200] or None
        tr.salary = (request.form.get(f'salary_{loc}')
                     or '').strip()[:100] or None


@admin_bp.route('/recruit/jobs/<int:jid>/delete', methods=['POST'])
@_gate
@permission_required('recruit:manage')
def recruit_job_delete(jid):
    job = RecruitJob.query.get_or_404(jid)
    if job.is_deleted:
        abort(404)
    job.is_deleted = True
    db.session.commit()
    audit_log(OP_DELETE, AUDIT_MODULE, jid, job.title, {'action': '岗位'})
    from app.utils.search import unindex_object
    unindex_object('recruit_job', jid)
    flash(_gettext('岗位已删除（软删除，可由管理员在数据库恢复）'), 'success')
    return redirect(url_for('admin.recruit_job_index'))


@admin_bp.route('/recruit/jobs/batch', methods=['POST'])
@_gate
@permission_required('recruit:manage')
def recruit_job_batch():
    action = request.form.get('action')
    ids = [int(i) for i in request.form.getlist('ids[]') if i.isdigit()]
    if not ids:
        flash(_gettext('未选择岗位'), 'warning')
        return redirect(url_for('admin.recruit_job_index'))
    jobs = RecruitJob.query.filter(RecruitJob.id.in_(ids),
                                   RecruitJob.is_deleted == False).all()  # noqa: E712
    if action == 'enable':
        for j in jobs:
            j.is_enabled = True
    elif action == 'disable':
        for j in jobs:
            j.is_enabled = False
    elif action == 'delete':
        for j in jobs:
            j.is_deleted = True
    else:
        flash(_gettext('未知批量操作'), 'warning')
        return redirect(url_for('admin.recruit_job_index'))
    db.session.commit()
    audit_log(OP_BATCH, AUDIT_MODULE, None, None,
              {'action': f'批量{action}', 'count': len(jobs), 'module': '招聘岗位'})
    # v2.5.2：同步全站搜索索引（下架/删除移出，启用重建）
    from app.utils.search import reindex_object, unindex_object
    for j in jobs:
        if action in ('delete', 'disable'):
            unindex_object('recruit_job', j.id)
        else:
            reindex_object('recruit_job', j.id)
    flash(_gettext('批量操作完成'), 'success')
    return redirect(url_for('admin.recruit_job_index'))


# ============================================================
# 求职申请管理
# ============================================================

@admin_bp.route('/recruit/applications')
@_gate
@permission_required('recruit:manage')
def recruit_application_index():
    page = max(_to_int(request.args.get('page'), 1), 1)
    job_id = request.args.get('job_id', type=int)
    status = request.args.get('status', '')

    query = RecruitApplication.query
    if job_id:
        job = RecruitJob.query.get(job_id)
        if job is None or job.is_deleted:
            abort(404)
        query = query.filter_by(job_id=job_id)
    if status:
        query = query.filter_by(status=status)

    pagination = query.order_by(
        RecruitApplication.id.desc()
    ).paginate(page=page, per_page=20, error_out=False)
    jobs = RecruitJob.query.filter_by(is_deleted=False) \
        .order_by(RecruitJob.id.desc()).all()
    return render_template('recruit/applications.html',
                           apps=pagination.items, pagination=pagination,
                           jobs=jobs, filter_job_id=job_id, status=status)


@admin_bp.route('/recruit/applications/<int:aid>/resume')
@_gate
@permission_required('recruit:manage')
def recruit_application_resume(aid):
    """下载申请简历附件（download_name 用投递时的原始文件名）。"""
    app_row = RecruitApplication.query.get_or_404(aid)
    path = resume_abs_path(app_row)
    if path is None:
        flash(_gettext('简历文件不存在或已丢失'), 'warning')
        return redirect(url_for('admin.recruit_application_index'))
    return send_file(path, as_attachment=True,
                     download_name=app_row.resume_name or 'resume')


@admin_bp.route('/recruit/applications/<int:aid>/status', methods=['POST'])
@_gate
@permission_required('recruit:manage')
def recruit_application_status(aid):
    """标记申请处理状态。"""
    app_row = RecruitApplication.query.get_or_404(aid)
    new_status = request.form.get('status', '')
    if new_status not in RecruitApplication.STATUS_LABELS:
        flash(_gettext('未知状态'), 'warning')
        return redirect(url_for('admin.recruit_application_index'))
    old = app_row.status
    app_row.status = new_status
    db.session.commit()
    audit_log(OP_UPDATE, AUDIT_MODULE, aid, f'{app_row.name} → {app_row.job.title}',
              {'action': '申请状态', 'from': old, 'to': new_status})
    flash(_gettext('申请状态已更新为「{0}」').format(app_row.status_label()), 'success')
    return redirect(url_for('admin.recruit_application_index',
                            status=request.form.get('back_status') or None,
                            job_id=request.form.get('back_job_id', type=int) or None))


@admin_bp.route('/recruit/applications/<int:aid>/delete', methods=['POST'])
@_gate
@permission_required('recruit:manage')
def recruit_application_delete(aid):
    """删除申请记录（硬删除；简历文件保留于上传目录，可按需清理）。"""
    app_row = RecruitApplication.query.get_or_404(aid)
    name = app_row.name
    job_title = app_row.job.title if app_row.job else ''
    db.session.delete(app_row)
    db.session.commit()
    audit_log(OP_DELETE, AUDIT_MODULE, aid, name,
              {'action': '求职申请', 'job': job_title})
    flash(_gettext('申请记录已删除'), 'success')
    return redirect(url_for('admin.recruit_application_index'))
