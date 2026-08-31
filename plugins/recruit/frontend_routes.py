"""招聘插件：前台路由蓝本。

路由：
  /jobs                    岗位列表（招聘中在前，已截止在后）
  /jobs/<int:jid>          岗位详情 + 申请表单（截止后仅展示提示）
  /jobs/<int:jid>/apply    提交求职申请（POST，验证码 + 截止时间 + 简历校验）
  /job-<int:jid>.html      岗位详情伪静态 URL（与 /product-{id}.html 同机制）

模板解析链：themes/<当前主题>/recruit_jobs.html / recruit_job_detail.html
（主题可覆盖）→ plugins/recruit/templates/recruit/...（插件兜底）。

申请表单不参与页面缓存（含验证码会话与 CSRF 交互），前台表单防滥用
沿用站点习惯：图形验证码（核心 /captcha 端点，session['form_captcha']）。
"""
import os
from datetime import datetime
from functools import wraps

from flask import (Blueprint, render_template, abort, redirect, request,
                   session, url_for, flash, current_app)

from app.extensions import db
from app.models.setting import Setting
from app.plugin_system import plugin_enabled
from app.utils.themes import theme_template, get_active_theme, THEMES_DIR
from app.utils.uploads import save_upload_file

from .models import RecruitJob, RecruitApplication
from .frontend import recruit_job_url

recruit_frontend = Blueprint('recruit_frontend', __name__,
                             template_folder='templates')

# 简历类型白名单：word / excel / pdf（从原始文件名提取后缀）
RESUME_EXTS = ['doc', 'docx', 'xls', 'xlsx', 'pdf']
RESUME_MAX_SIZE = 10 * 1024 * 1024   # 简历单文件上限 10MB（优先级低于后台设置）


# ============================================================
# 守卫 / 模板解析
# ============================================================

def _gate(view):
    """插件启用守卫：未启用 → 404（不暴露存在性）。"""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('recruit'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def _resolve_template(name):
    """主题有覆盖（recruit_jobs.html / recruit_job_detail.html）则用主题版，
    否则用插件自带模板。"""
    theme = get_active_theme()
    if os.path.isfile(os.path.join(THEMES_DIR, theme, name)):
        return theme_template(name)
    return f'recruit/{name.replace("recruit_", "")}'


def _base_ctx(seo_title, seo_description=''):
    from app.frontend.views import _build_nav
    return {
        'nav': _build_nav(),
        'seo': {'title': seo_title, 'keywords': '', 'description': seo_description},
    }


# ============================================================
# 路由
# ============================================================

@recruit_frontend.route('/jobs')
@_gate
def job_list():
    """岗位列表：招聘中排前，已截止排后。"""
    jobs = RecruitJob.query.filter(
        RecruitJob.is_deleted == False,   # noqa: E712
        RecruitJob.is_enabled == True,    # noqa: E712
    ).order_by(RecruitJob.sort_order.desc(), RecruitJob.id.desc()).all()
    open_jobs = [j for j in jobs if not j.is_expired()]
    closed_jobs = [j for j in jobs if j.is_expired()]
    ctx = _base_ctx('招贤纳士', '招聘岗位与在线求职申请')
    return render_template(_resolve_template('recruit_jobs.html'),
                           open_jobs=open_jobs, closed_jobs=closed_jobs,
                           **ctx)


def _get_open_job(jid):
    job = RecruitJob.query.get_or_404(jid)
    if job.is_deleted or not job.is_enabled:
        abort(404)
    return job


@recruit_frontend.route('/jobs/<int:jid>')
@_gate
def job_detail(jid):
    """岗位详情：开放申请时渲染表单，截止后仅展示提示。"""
    job = _get_open_job(jid)
    submitted = request.args.get('submitted') == '1'
    ctx = _base_ctx(job.title, (job.description or '')[:200])
    return render_template(_resolve_template('recruit_job_detail.html'),
                           job=job, is_open=job.is_open(),
                           submitted=submitted,
                           resume_exts=', '.join(RESUME_EXTS),
                           **ctx)


@recruit_frontend.route('/job-<int:jid>.html')
@_gate
def job_detail_rewrite(jid):
    """伪静态 /job-12.html（与 /product-{id}.html 同级静态前缀）。"""
    if Setting.get('seo_rewrite_enable') != 'on':
        abort(404)
    return job_detail(jid)


@recruit_frontend.route('/jobs/<int:jid>/apply', methods=['POST'])
@_gate
def job_apply(jid):
    """提交求职申请：验证码 → 截止时间 → 必填项 → 简历上传。"""
    job = _get_open_job(jid)
    if not job.is_open():
        flash('该岗位招聘已截止，无法继续投递', 'warning')
        return redirect(recruit_job_url(job))

    # 1. 图形验证码（与站点表单一致：核心 /captcha 端点 + form_captcha 会话键）
    given = (request.form.get('captcha') or '').strip().lower()
    expected = (session.get('form_captcha') or '').lower()
    session.pop('form_captcha', None)   # 一次性消费，防重放
    if not expected or given != expected:
        flash('验证码错误，请重试', 'danger')
        return redirect(recruit_job_url(job))

    # 2. 必填项
    name = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    if not name or not phone:
        flash('请填写姓名和联系电话', 'danger')
        return redirect(recruit_job_url(job))
    if len(name) > 64 or len(phone) > 32:
        flash('姓名或电话长度超限', 'danger')
        return redirect(recruit_job_url(job))

    # 3. 简历上传（word/excel/pdf；从原始文件名提取后缀）
    f = request.files.get('resume')
    resume_file = resume_name = None
    if f is not None and f.filename:
        rel, url, err = save_upload_file(f, sub_dir='recruit',
                                         allowed_exts=RESUME_EXTS,
                                         max_size=RESUME_MAX_SIZE)
        if err:
            flash(f'简历上传失败：{err}', 'danger')
            return redirect(recruit_job_url(job))
        resume_file, resume_name = rel, f.filename

    app_row = RecruitApplication(
        job_id=job.id,
        name=name,
        phone=phone,
        email=(request.form.get('email') or '').strip()[:128] or None,
        education=(request.form.get('education') or '').strip()[:64] or None,
        intro=(request.form.get('intro') or '').strip() or None,
        resume_file=resume_file,
        resume_name=resume_name,
        ip=request.remote_addr or '',
    )
    db.session.add(app_row)
    db.session.commit()

    flash('申请提交成功，我们会尽快与您联系！', 'success')
    return redirect(url_for('recruit_frontend.job_detail', jid=job.id,
                            submitted=1))


# ============================================================
# 简历下载（后台申请管理用）
# ============================================================

def resume_abs_path(app_row):
    """把申请记录中的简历存储路径换算为磁盘绝对路径；不存在返回 None。

    resume_file 形如 'uploads/recruit/20260830/uuid.pdf'（相对 static），
    剥去 'uploads/' 前缀后即 UPLOAD_FOLDER 下的相对路径。
    仅放行简历白名单后缀。
    """
    from werkzeug.security import safe_join

    rel = (app_row.resume_file or '').replace('\\', '/')
    if not rel.startswith('uploads/'):
        return None
    rel = rel[len('uploads/'):]           # recruit/20260830/uuid.pdf
    ext = rel.rsplit('.', 1)[1].lower() if '.' in rel else ''
    if ext not in RESUME_EXTS:
        return None
    joined = safe_join(current_app.config['UPLOAD_FOLDER'], rel)
    if joined and os.path.isfile(joined):
        return joined
    return None
