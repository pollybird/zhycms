"""系统设置：网站全局、SEO、上传配置、个人资料、密码、登录日志。"""
from datetime import datetime

from flask import (
    render_template, redirect, url_for, request, flash, abort
)
from flask_login import current_user

from ..extensions import db
from ..models.user import User, LoginLog
from ..models.setting import Setting
from ..utils.helpers import admin_required
from ..utils.uploads import save_upload_file
from ..utils.themes import list_themes
from ..utils.admin_prefix import load_admin_prefix, validate_prefix, save_admin_prefix
from . import admin_bp


# ============ 网站设置 ============

@admin_bp.route('/settings/site', methods=['GET', 'POST'])
@admin_required
def setting_site():
    if request.method == 'POST':
        Setting.set('site_name', (request.form.get('site_name') or '').strip())
        Setting.set('site_subtitle', (request.form.get('site_subtitle') or '').strip())
        Setting.set('site_status', request.form.get('site_status') or 'open')
        Setting.set('site_close_reason', (request.form.get('site_close_reason') or '').strip())
        Setting.set('footer_copyright', (request.form.get('footer_copyright') or '').strip())
        Setting.set('site_theme', (request.form.get('site_theme') or 'default').strip())

        # LOGO
        logo_file = request.files.get('site_logo')
        if logo_file and logo_file.filename:
            rel, url, err = save_upload_file(logo_file, sub_dir='site',
                                             allowed_exts=['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'])
            if err:
                flash(f'LOGO 上传失败：{err}', 'danger')
            else:
                Setting.set('site_logo', url)
        elif request.form.get('site_logo_remove') == 'on':
            Setting.set('site_logo', '')

        db.session.commit()
        flash('网站设置已保存', 'success')
        return redirect(url_for('admin.setting_site'))

    return render_template('admin/setting/site.html', settings=Setting.get_dict(), themes=list_themes())


@admin_bp.route('/settings/seo', methods=['GET', 'POST'])
@admin_required
def setting_seo():
    if request.method == 'POST':
        Setting.set('seo_title', (request.form.get('seo_title') or '').strip())
        Setting.set('seo_keywords', (request.form.get('seo_keywords') or '').strip())
        Setting.set('seo_description', (request.form.get('seo_description') or '').strip())
        db.session.commit()
        flash('SEO 默认配置已保存', 'success')
        return redirect(url_for('admin.setting_seo'))
    return render_template('admin/setting/seo.html', settings=Setting.get_dict())


@admin_bp.route('/settings/upload', methods=['GET', 'POST'])
@admin_required
def setting_upload():
    if request.method == 'POST':
        try:
            max_size = int(request.form.get('upload_max_size') or 0)
            # KB 转 Byte
            Setting.set('upload_max_size', str(max_size * 1024))
        except ValueError:
            flash('文件大小必须是数字', 'danger')
            return redirect(url_for('admin.setting_upload'))

        Setting.set('upload_allowed_exts', (request.form.get('upload_allowed_exts') or '').strip())
        db.session.commit()
        flash('上传配置已保存', 'success')
        return redirect(url_for('admin.setting_upload'))

    settings = Setting.get_dict()
    # 转回 KB 显示
    try:
        settings['upload_max_size_kb'] = int(settings.get('upload_max_size', 0)) // 1024
    except ValueError:
        settings['upload_max_size_kb'] = 10240
    return render_template('admin/setting/upload.html', settings=settings)


# ============ 后台安全（自定义后台路由前缀）============

@admin_bp.route('/settings/security', methods=['GET', 'POST'])
@admin_required
def setting_security():
    """管理员可自定义后台路由前缀，避免后台地址被轻易猜测。

    前缀落盘到 instance/admin_config.json，因 Flask 蓝本前缀只在启动时注册一次，
    修改后需重启服务方能生效。
    """
    if request.method == 'POST':
        ok, result = validate_prefix(request.form.get('admin_prefix'))
        if not ok:
            flash(result, 'danger')
            return redirect(url_for('admin.setting_security'))

        save_admin_prefix(result)
        flash(f'后台路由已保存为 /{result}，请重启服务后使用新地址 /{result}/login 访问后台。'
              f'旧地址将失效，请牢记新地址。', 'success')
        return redirect(url_for('admin.setting_security'))

    return render_template('admin/setting/security.html',
                           admin_prefix=load_admin_prefix())


# ============ 个人资料 / 密码 ============

@admin_bp.route('/profile', methods=['GET', 'POST'])
@admin_required
def profile():
    if request.method == 'POST':
        user = current_user
        user.nickname = (request.form.get('nickname') or '').strip()
        user.email = (request.form.get('email') or '').strip()
        db.session.commit()
        flash('个人资料已更新', 'success')
        return redirect(url_for('admin.profile'))
    return render_template('admin/setting/profile.html', user=current_user)


@admin_bp.route('/password', methods=['GET', 'POST'])
@admin_required
def password():
    if request.method == 'POST':
        user = current_user
        old_pwd = request.form.get('old_password') or ''
        new_pwd = request.form.get('new_password') or ''
        confirm_pwd = request.form.get('confirm_password') or ''

        if not user.check_password(old_pwd):
            flash('原密码错误', 'danger')
            return redirect(url_for('admin.password'))
        if len(new_pwd) < 6:
            flash('新密码长度不能少于 6 位', 'danger')
            return redirect(url_for('admin.password'))
        if new_pwd != confirm_pwd:
            flash('两次输入的新密码不一致', 'danger')
            return redirect(url_for('admin.password'))

        user.set_password(new_pwd)
        db.session.commit()
        flash('密码修改成功', 'success')
        return redirect(url_for('admin.password'))
    return render_template('admin/setting/password.html')


# ============ 登录日志 ============

@admin_bp.route('/logs')
@admin_required
def logs():
    page = max(int(request.args.get('page', 1)), 1)
    pagination = LoginLog.query.order_by(LoginLog.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template('admin/setting/logs.html', logs=pagination.items, pagination=pagination)
