"""自定义表单插件：前台路由蓝本。

路由：
  /form/<slug>   表单展示与提交（与核心版路径一致，老站书签不失效）

模板解析：themes/<当前主题>/form.html（企业可覆盖）/ form_closed.html，
由核心 theme_template() 解析；插件蓝本的 template_folder 同时把后台
管理页模板（admin/form/*）接入 Jinja 搜索路径。

守卫：未启用插件时 /form/<slug> 返回 404（不暴露存在性）。
"""
import time
from functools import wraps

from flask import (
    Blueprint, render_template, redirect, url_for, request,
    flash, abort, session, current_app,
)

from app.extensions import db
from app.models.setting import Setting
from app.plugin_system import plugin_enabled
from app.utils.themes import theme_template
from app.utils.uploads import save_upload_file

from .models import Form, FormField, FormSubmission, FormSubmissionValue

form_frontend = Blueprint('form_frontend', __name__,
                          template_folder='templates')


def _gate(view):
    """插件启用守卫：未启用 → 404。"""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('form'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


@form_frontend.route('/form/<slug>', methods=['GET', 'POST'])
@_gate
def form_submit(slug):
    form = Form.query.filter_by(slug=slug, is_deleted=False).first_or_404()
    if not form.is_open:
        return render_template(theme_template('form_closed'), form=form,
                               nav=_build_nav(), seo=_seo()), 403

    nav = _build_nav()
    fields = form.fields.filter_by(is_deleted=False).order_by(FormField.sort_order.asc()).all()

    if request.method == 'POST':
        if form.submit_interval > 0:
            cache_key = f'form_submit_{form.id}_{request.remote_addr}'
            last = session.get(cache_key, 0)
            now = int(time.time())
            if now - last < form.submit_interval:
                flash(f'提交过于频繁，请 {form.submit_interval - (now - last)} 秒后再试', 'danger')
                return redirect(url_for('.form_submit', slug=slug))

        # 图形验证码
        captcha = (request.form.get('captcha') or '').strip().lower()
        session_captcha = (session.get('form_captcha') or '').lower()
        session.pop('form_captcha', None)
        if not session_captcha or captcha != session_captcha:
            flash('验证码错误，请重新输入', 'danger')
            return redirect(url_for('.form_submit', slug=slug))

        # 校验必填
        errors = []
        for f in fields:
            val = request.form.get(f'field_{f.id}') or ''
            file_obj = request.files.get(f'field_{f.id}')
            if f.is_required and not val and not (file_obj and file_obj.filename):
                errors.append(f'{f.label} 为必填项')

        for f in fields:
            val = (request.form.get(f'field_{f.id}') or '').strip()
            if not val:
                continue
            if f.field_type == 'email' and '@' not in val:
                errors.append(f'{f.label} 格式不正确')
            elif f.field_type == 'phone' and not val.isdigit():
                errors.append(f'{f.label} 必须为数字')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return redirect(url_for('.form_submit', slug=slug))

        # 保存提交
        sub = FormSubmission(
            form_id=form.id,
            ip=request.remote_addr or '',
            user_agent=request.user_agent.string[:255] if request.user_agent else '',
        )
        db.session.add(sub)
        db.session.flush()

        fields_list = []  # 用于通知模块：(label, value)
        for f in fields:
            value = None
            if f.field_type == 'file':
                file_obj = request.files.get(f'field_{f.id}')
                if file_obj and file_obj.filename:
                    allowed = f.allowed_exts.split(',') if f.allowed_exts else None
                    rel, url, err = save_upload_file(
                        file_obj, sub_dir=f'form/{form.slug}',
                        allowed_exts=allowed, max_size=f.max_size
                    )
                    if err:
                        flash(f'字段 {f.label} 上传失败：{err}', 'danger')
                        db.session.rollback()
                        return redirect(url_for('.form_submit', slug=slug))
                    value = url
            elif f.field_type == 'checkbox':
                values = request.form.getlist(f'field_{f.id}')
                value = '|||'.join(values)
            else:
                value = request.form.get(f'field_{f.id}') or ''

            if value is not None:
                v = FormSubmissionValue(submission_id=sub.id, field_id=f.id, value=value)
                db.session.add(v)
                fields_list.append((f.label, value))

        db.session.commit()
        if form.submit_interval > 0:
            session[cache_key] = int(time.time())

        # 消息通知推送（异常不影响用户提交成功提示）
        if Setting.get('form_notify_enable') == 'on':
            try:
                from .notify import notify_form_submission
                submit_page = request.referrer or url_for('.form_submit',
                                                          slug=slug, _external=True)
                notify_form_submission(form, sub, fields_list, submit_page=submit_page)
            except Exception:
                current_app.logger.exception('notify form submission failed')

        flash(form.success_message, 'success')
        return redirect(url_for('.form_submit', slug=slug))

    return render_template(
        theme_template('form'), form=form, fields=fields,
        nav=nav, seo=_seo()
    )


def _build_nav():
    """复用核心前台导航构建（启用栏目 + 插件菜单项），保持主题布局一致。"""
    from app.frontend.views import _build_nav as _nav
    return _nav()


def _seo():
    """复用核心前台 SEO 信息（站点级）。"""
    from app.frontend.views import _seo as _s
    return _s()
