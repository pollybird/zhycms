"""系统设置：网站全局、SEO、上传配置、个人资料、密码、登录日志。
升级点（对应模块5/6/7/8）：
  - 登录安全：登录失败次数/锁定时间/异地IP提醒 + 自定义后台路由即时生效
  - 上传安全：MIME二次校验、单文件MB限制、图片压缩质量/缩略图/去重开关
  - 消息通知：邮件 SMTP + 企业微信 Webhook 配置
  - SEO高级：伪静态开关、sitemap更新频率/优先级、robots自定义文本、默认图片ALT、缓存开关+TTL
  - 备份周期：直接复用 app/admin/backup.py 的 setting_backup_save POST 路由
"""
from datetime import datetime

from flask import (
    render_template, redirect, url_for, request, flash, abort, current_app,
    session,
)
from flask_babel import gettext as _gettext
from flask_login import current_user

from ..extensions import db
from ..models.user import User, LoginLog
from ..models.setting import Setting
from ..utils.helpers import admin_required, permission_required, audit_log, clear_content_cache
from ..utils.uploads import save_upload_file
from ..utils.themes import list_theme_templates
from ..utils.admin_prefix import load_admin_prefix, validate_prefix, save_admin_prefix
from ..models.audit import (
    OP_CONFIG_CHANGE, OP_UPDATE, MODULE_SETTING,
)
from . import admin_bp


# ============================================================
# 工具：触发后台动态路由即时生效（调用 app.__init__._register_dynamic_admin_rules）
# ============================================================

def _rebuild_admin_rules_now():
    """保存路由前缀后立刻重建，而不必等下一次请求。"""
    try:
        from app import _register_dynamic_admin_rules
        _register_dynamic_admin_rules(current_app._get_current_object())
    except Exception:
        current_app.logger.exception('rebuild dynamic admin rules failed')


def _onoff(name):
    return 'on' if request.form.get(name) == 'on' else 'off'


def _int_safe(name, default=0):
    try:
        return int(request.form.get(name) or default)
    except (TypeError, ValueError):
        return default


# ============ 网站设置（需要 system:settings）============

@admin_bp.route('/settings/site', methods=['GET', 'POST'])
@permission_required('system:settings')
def setting_site():
    if request.method == 'POST':
        changed = {}
        for key in ('site_name', 'site_subtitle', 'site_close_reason',
                    'footer_copyright', 'site_status'):
            val = (request.form.get(key) or '').strip()
            if key == 'site_status':
                val = val or 'open'
            old = Setting.get(key)
            if old != val:
                Setting.set(key, val)
                changed[key] = val

        # LOGO
        logo_file = request.files.get('site_logo')
        if logo_file and logo_file.filename:
            rel, url, err = save_upload_file(logo_file, sub_dir='site',
                                             allowed_exts=['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'])
            if err:
                flash(_gettext('LOGO 上传失败：{0}').format(err), 'danger')
            else:
                Setting.set('site_logo', url)
                changed['site_logo'] = url
        elif request.form.get('site_logo_remove') == 'on':
            Setting.set('site_logo', '')
            changed['site_logo'] = ''

        db.session.commit()
        clear_content_cache()
        flash(_gettext('网站设置已保存'), 'success')
        if changed:
            audit_log(OP_CONFIG_CHANGE, MODULE_SETTING, None, None,
                      {'category': 'site', 'changed_keys': list(changed.keys())})
        return redirect(url_for('admin.setting_site'))

    return render_template('admin/setting/site.html',
                           settings=Setting.get_dict())


# ============ SEO 默认 + SEO 高级（伪静态/sitemap/robots/缓存/图片ALT）============

@admin_bp.route('/settings/seo', methods=['GET', 'POST'])
@permission_required('system:settings')
def setting_seo():
    if request.method == 'POST':
        changed = {}
        for key in ('seo_title', 'seo_keywords', 'seo_description'):
            val = (request.form.get(key) or '').strip()
            if Setting.get(key) != val:
                Setting.set(key, val)
                changed[key] = val
        db.session.commit()
        clear_content_cache()
        flash(_gettext('SEO 默认配置已保存'), 'success')
        if changed:
            audit_log(OP_CONFIG_CHANGE, MODULE_SETTING, None, None,
                      {'category': 'seo', 'changed_keys': list(changed.keys())})
        return redirect(url_for('admin.setting_seo'))
    return render_template('admin/setting/seo.html', settings=Setting.get_dict())


@admin_bp.route('/settings/seo-advanced', methods=['GET', 'POST'])
@permission_required('system:settings')
def setting_seo_advanced():
    """SEO高级：伪静态开关、sitemap更新频率/优先级、robots自定义文本、缓存开关+TTL、图片默认ALT。"""
    if request.method == 'POST':
        changed = {}
        # 伪静态
        for key in ('seo_rewrite_enable',):
            val = _onoff(key)
            if Setting.get(key) != val:
                Setting.set(key, val)
                changed[key] = val
        # sitemap changefreq / priority
        for key in ('seo_sitemap_changefreq_column', 'seo_sitemap_changefreq_article',
                    'seo_sitemap_priority_column', 'seo_sitemap_priority_article'):
            val = (request.form.get(key) or '').strip()
            if Setting.get(key) != val:
                Setting.set(key, val)
                changed[key] = val
        # robots 自定义文本
        val = request.form.get('seo_robots_custom') or ''
        if Setting.get('seo_robots_custom') != val:
            Setting.set('seo_robots_custom', val)
            changed['seo_robots_custom'] = val
        # 默认图片 ALT
        val = (request.form.get('seo_image_alt_default') or '').strip()
        if Setting.get('seo_image_alt_default') != val:
            Setting.set('seo_image_alt_default', val)
            changed['seo_image_alt_default'] = val
        # 缓存
        for key in ('cache_enable',):
            val = _onoff(key)
            if Setting.get(key) != val:
                Setting.set(key, val)
                changed[key] = val
        for key in ('cache_ttl_index', 'cache_ttl_column', 'cache_ttl_article'):
            val = str(max(0, _int_safe(key, default=600)))
            if Setting.get(key) != val:
                Setting.set(key, val)
                changed[key] = val
        db.session.commit()
        clear_content_cache()
        flash(_gettext('SEO 高级配置已保存'), 'success')
        if changed:
            audit_log(OP_CONFIG_CHANGE, MODULE_SETTING, None, None,
                      {'category': 'seo_advanced', 'changed': changed})
        return redirect(url_for('admin.setting_seo_advanced'))
    settings = Setting.get_dict()
    # TTL 回显成整数
    for k in ('cache_ttl_index', 'cache_ttl_column', 'cache_ttl_article'):
        try:
            settings[k] = int(settings.get(k, 600))
        except (TypeError, ValueError):
            settings[k] = 600
    return render_template('admin/setting/seo_advanced.html', settings=settings)


# ============ 上传基础 + 上传扩展（模块6）============

@admin_bp.route('/settings/upload', methods=['GET', 'POST'])
@permission_required('system:settings')
def setting_upload():
    if request.method == 'POST':
        changed = {}
        try:
            max_size = int(request.form.get('upload_max_size') or 0)
            val = str(max_size * 1024)
        except ValueError:
            flash(_gettext('文件大小必须是数字'), 'danger')
            return redirect(url_for('admin.setting_upload'))
        if Setting.get('upload_max_size') != val:
            Setting.set('upload_max_size', val)
            changed['upload_max_size_kb'] = max_size
        val = (request.form.get('upload_allowed_exts') or '').strip()
        if Setting.get('upload_allowed_exts') != val:
            Setting.set('upload_allowed_exts', val)
            changed['upload_allowed_exts'] = val
        db.session.commit()
        flash(_gettext('上传基础配置已保存'), 'success')
        if changed:
            audit_log(OP_CONFIG_CHANGE, MODULE_SETTING, None, None,
                      {'category': 'upload', 'changed': changed})
        return redirect(url_for('admin.setting_upload'))

    settings = Setting.get_dict()
    try:
        settings['upload_max_size_kb'] = int(settings.get('upload_max_size', 0)) // 1024
    except ValueError:
        settings['upload_max_size_kb'] = 10240
    return render_template('admin/setting/upload.html', settings=settings)


@admin_bp.route('/settings/upload-security', methods=['GET', 'POST'])
@permission_required('system:settings')
def setting_upload_security():
    """模块6上传安全：MIME、单文件MB、压缩、缩略图、去重。"""
    if request.method == 'POST':
        changed = {}
        # 开关类
        for key in ('upload_enable_mime_check', 'upload_image_auto_compress',
                    'upload_image_thumb_enable', 'upload_enable_dedup'):
            val = _onoff(key)
            if Setting.get(key) != val:
                Setting.set(key, val)
                changed[key] = val
        # 数值类
        # upload_single_max_size_mb：MB
        mb_val = max(0, _int_safe('upload_single_max_size_mb', default=10))
        val = str(mb_val)
        if Setting.get('upload_single_max_size_mb') != val:
            Setting.set('upload_single_max_size_mb', val)
            changed['upload_single_max_size_mb'] = val
        # 图片压缩质量 0-100
        q = min(100, max(1, _int_safe('upload_image_compress_quality', default=80)))
        val = str(q)
        if Setting.get('upload_image_compress_quality') != val:
            Setting.set('upload_image_compress_quality', val)
            changed['upload_image_compress_quality'] = val
        # 缩略图宽度 px
        w = max(50, _int_safe('upload_image_thumb_width', default=300))
        val = str(w)
        if Setting.get('upload_image_thumb_width') != val:
            Setting.set('upload_image_thumb_width', val)
            changed['upload_image_thumb_width'] = val
        db.session.commit()
        flash(_gettext('上传安全与图片优化配置已保存'), 'success')
        if changed:
            audit_log(OP_CONFIG_CHANGE, MODULE_SETTING, None, None,
                      {'category': 'upload_security', 'changed': changed})
        return redirect(url_for('admin.setting_upload_security'))
    settings = Setting.get_dict()
    for k, d in (('upload_single_max_size_mb', 10),
                 ('upload_image_compress_quality', 80),
                 ('upload_image_thumb_width', 300)):
        try:
            settings[k] = int(settings.get(k, d))
        except (TypeError, ValueError):
            settings[k] = d
    return render_template('admin/setting/upload_security.html', settings=settings)


# ============ 后台安全（模块5：登录锁定 + 自定义后台前缀即时生效）============

@admin_bp.route('/settings/security', methods=['GET', 'POST'])
@permission_required('system:settings')
def setting_security():
    if request.method == 'POST':
        changed = {}
        # 1. 自定义路由前缀（即时生效）
        prefix = request.form.get('admin_prefix') or ''
        if prefix:
            ok, result = validate_prefix(prefix)
            if not ok:
                flash(result, 'danger')
                return redirect(url_for('admin.setting_security'))
            old_prefix = load_admin_prefix()
            save_admin_prefix(result)
            if old_prefix != result:
                changed['admin_prefix'] = (old_prefix, result)
                _rebuild_admin_rules_now()
                flash(_gettext('后台路由已即时切换为 /{0}/ ，新地址立即可用，旧地址同步失效。').format(result), 'success')
            else:
                flash(_gettext('后台路由未变（仍为 /{0}/）。').format(result), 'info')
        # 2. 登录安全：失败次数/锁定分钟/异地IP提醒
        max_fail = max(3, min(50, _int_safe('login_max_fail', default=5)))
        lock_min = max(1, min(600, _int_safe('login_lock_minutes', default=10)))
        if Setting.get('login_max_fail') != str(max_fail):
            Setting.set('login_max_fail', str(max_fail))
            changed['login_max_fail'] = max_fail
        if Setting.get('login_lock_minutes') != str(lock_min):
            Setting.set('login_lock_minutes', str(lock_min))
            changed['login_lock_minutes'] = lock_min
        val = _onoff('login_abnormal_city_alert')
        if Setting.get('login_abnormal_city_alert') != val:
            Setting.set('login_abnormal_city_alert', val)
            changed['login_abnormal_city_alert'] = val
        db.session.commit()
        if changed:
            audit_log(OP_CONFIG_CHANGE, MODULE_SETTING, None, None,
                      {'category': 'security', 'changed': changed})
        if 'admin_prefix' not in changed and not (set(changed.keys()) - {'admin_prefix'}):
            flash(_gettext('登录安全配置已保存'), 'success')
        # 若改变了前缀，url_for 在本次请求中使用的旧 URL adapter 已与新 url_map 不匹配，
        # 直接字面量拼新前缀下的 security 设置页 URL，避免 BuildError。
        from app.utils.admin_prefix import load_admin_prefix as _lap
        return redirect('/' + _lap() + '/settings/security')

    settings = Setting.get_dict()
    for k, d in (('login_max_fail', 5), ('login_lock_minutes', 10)):
        try:
            settings[k] = int(settings.get(k, d))
        except (TypeError, ValueError):
            settings[k] = d
    return render_template('admin/setting/security.html',
                           admin_prefix=load_admin_prefix(), settings=settings)


# ============ 消息通知（模块7）============

@admin_bp.route('/settings/notify', methods=['GET', 'POST'])
@permission_required('system:settings')
def setting_notify():
    """模块7：消息通知配置（邮件 + 企业微信 Webhook）。"""
    if request.method == 'POST':
        changed = {}
        # 总开关
        val = _onoff('form_notify_enable')
        if Setting.get('form_notify_enable') != val:
            Setting.set('form_notify_enable', val)
            changed['form_notify_enable'] = val
        # 渠道选择（用逗号分隔 email,wework）
        channels_raw = request.form.getlist('form_notify_channels[]')
        channels = ','.join(channels_raw) if channels_raw else ''
        if Setting.get('form_notify_channels') != channels:
            Setting.set('form_notify_channels', channels)
            changed['form_notify_channels'] = channels
        # 邮件 SMTP
        for key in ('notify_email_smtp_host', 'notify_email_sender_name',
                    'notify_email_sender_address', 'notify_email_receivers'):
            val = (request.form.get(key) or '').strip()
            if Setting.get(key) != val:
                Setting.set(key, val)
                changed[key] = val
        for key in ('notify_email_smtp_port',):
            val = str(_int_safe(key, default=465))
            if Setting.get(key) != val:
                Setting.set(key, val)
                changed[key] = val
        val = _onoff('notify_email_smtp_ssl')
        if Setting.get('notify_email_smtp_ssl') != val:
            Setting.set('notify_email_smtp_ssl', val)
            changed['notify_email_smtp_ssl'] = val
        for key in ('notify_email_smtp_user',):
            val = (request.form.get(key) or '').strip()
            if Setting.get(key) != val:
                Setting.set(key, val)
                changed[key] = val
        # 密码单独处理（未变更不覆写为空）
        pwd = request.form.get('notify_email_smtp_password') or ''
        if pwd:
            if Setting.get('notify_email_smtp_password') != pwd:
                Setting.set('notify_email_smtp_password', pwd)
                changed['notify_email_smtp_password'] = '***changed***'
        # 企业微信
        for key in ('notify_wework_webhook', 'notify_wework_mentioned_mobiles'):
            val = (request.form.get(key) or '').strip()
            if Setting.get(key) != val:
                Setting.set(key, val)
                changed[key] = val
        db.session.commit()
        flash(_gettext('消息通知配置已保存'), 'success')
        if changed:
            audit_log(OP_CONFIG_CHANGE, MODULE_SETTING, None, None,
                      {'category': 'notify', 'changed_keys': list(changed.keys())})
        return redirect(url_for('admin.setting_notify'))
    return render_template('admin/setting/notify.html', settings=Setting.get_dict())


# ============ 图片 ALT 批量管理（模块8）============

@admin_bp.route('/tools/image-alt')
@permission_required('system:settings')
def tool_image_alt():
    """页面入口：后台展示站点范围内所有缺失或可批量修改的图片ALT条目。
    前台具体渲染时会用 Setting.seo_image_alt_default 作为兜底。"""
    # 简单返回模板，静态逻辑在前端页面实现（通过API加载文章/栏目/碎片的img标签）
    return render_template('admin/setting/image_alt.html',
                           settings=Setting.get_dict())


# ============ 内容 API（v2.2.0）============

@admin_bp.route('/settings/api', methods=['GET', 'POST'])
@permission_required('system:settings')
def setting_api():
    """内容 API：总开关、Token 鉴权、接口缓存 TTL、跨域白名单。"""
    if request.method == 'POST':
        changed = {}
        for key in ('api_enable',):
            val = _onoff(key)
            if Setting.get(key) != val:
                Setting.set(key, val)
                changed[key] = val
        # Token：留空表示公开只读
        val = (request.form.get('api_token') or '').strip()
        if Setting.get('api_token') != val:
            Setting.set('api_token', val)
            changed['api_token'] = '已设置' if val else '已清空（公开访问）'
        val = str(max(0, _int_safe('api_cache_ttl', default=60)))
        if Setting.get('api_cache_ttl') != val:
            Setting.set('api_cache_ttl', val)
            changed['api_cache_ttl'] = val
        val = (request.form.get('api_cors_origins') or '').strip()
        if Setting.get('api_cors_origins') != val:
            Setting.set('api_cors_origins', val)
            changed['api_cors_origins'] = val
        db.session.commit()
        flash(_gettext('内容 API 配置已保存'), 'success')
        if changed:
            audit_log(OP_CONFIG_CHANGE, MODULE_SETTING, None, None,
                      {'category': 'api', 'changed': changed})
        return redirect(url_for('admin.setting_api'))

    settings = Setting.get_dict()
    try:
        settings['api_cache_ttl'] = int(settings.get('api_cache_ttl', 60))
    except (TypeError, ValueError):
        settings['api_cache_ttl'] = 60
    return render_template('admin/setting/api.html', settings=settings)


# ============ 国际化（v2.3.0 Flask-Babel）============

# 后台切换器可选项（首版仅 zh/en，扩展仅需追加映射）
# 注意：N_=lazy_gettext，仅让 pybabel 抽取 msgid，运行时在模板里再用 gettext 翻译
from flask_babel import lazy_gettext as N_  # noqa: F401
_LOCALE_OPTIONS = [
    ('zh', N_('中文')),
    ('en', 'English'),
    ('ja', N_('日本語')),
    ('ko', N_('한국어')),
]
# 运行时真实原文 label（模板 label|code 成对，不能直接把 lazy string 当 key）
_LOCALE_OPTIONS_PLAIN = [
    ('zh', '中文'),
    ('en', 'English'),
    ('ja', '日本語'),
    ('ko', '한국어'),
]


@admin_bp.route('/set-locale')
@admin_required
def set_locale():
    """切换后台语种：写 session['locale'] 后重定向回 next。

    任何已登录后台用户均可切换自己的语种（非 system:settings 权限）。
    """
    lang = request.args.get('lang')
    next_url = request.args.get('next') or request.referrer or '/'
    available = [c.strip() for c in
                 (Setting.get('i18n_available_locales') or 'zh').split(',')
                 if c.strip()]
    if lang and lang in available:
        session['locale'] = lang
    return redirect(next_url)


@admin_bp.route('/settings/i18n', methods=['GET', 'POST'])
@permission_required('system:settings')
def setting_i18n():
    """国际化：总开关、默认语种、可用语种清单。"""
    if request.method == 'POST':
        changed = {}
        val = '1' if request.form.get('i18n_enable') == 'on' else '0'
        if Setting.get('i18n_enable') != val:
            Setting.set('i18n_enable', val)
            changed['i18n_enable'] = val
        val = (request.form.get('i18n_default_locale') or 'zh').strip()
        if val not in dict(_LOCALE_OPTIONS_PLAIN):
            val = 'zh'
        if Setting.get('i18n_default_locale') != val:
            Setting.set('i18n_default_locale', val)
            changed['i18n_default_locale'] = val
        codes = request.form.getlist('i18n_available_locales')
        val = ','.join(c.strip() for c in codes if c.strip()) or 'zh'
        if Setting.get('i18n_available_locales') != val:
            Setting.set('i18n_available_locales', val)
            changed['i18n_available_locales'] = val
        db.session.commit()
        flash(_gettext('国际化配置已保存'), 'success')
        if changed:
            audit_log(OP_CONFIG_CHANGE, MODULE_SETTING, None, None,
                      {'category': 'i18n', 'changed': changed})
        return redirect(url_for('admin.setting_i18n'))

    settings = Setting.get_dict()
    available = [c.strip() for c in
                 (settings.get('i18n_available_locales') or 'zh').split(',')
                 if c.strip()]
    return render_template('admin/setting/i18n.html', settings=settings,
                           locale_options=_LOCALE_OPTIONS,
                           available=available)


# ============ 个人资料 / 密码 ============

@admin_bp.route('/profile', methods=['GET', 'POST'])
@admin_required
def profile():
    if request.method == 'POST':
        user = current_user
        old_nick = user.nickname
        old_email = user.email
        user.nickname = (request.form.get('nickname') or '').strip()
        user.email = (request.form.get('email') or '').strip()
        db.session.commit()
        flash(_gettext('个人资料已更新'), 'success')
        if old_nick != user.nickname or old_email != user.email:
            audit_log(OP_UPDATE, MODULE_SETTING, user.id, user.username,
                      {'action': 'profile',
                       'nickname': (old_nick, user.nickname),
                       'email': (old_email, user.email)})
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
            flash(_gettext('原密码错误'), 'danger')
            return redirect(url_for('admin.password'))
        if len(new_pwd) < 6:
            flash(_gettext('新密码长度不能少于 6 位'), 'danger')
            return redirect(url_for('admin.password'))
        if new_pwd != confirm_pwd:
            flash(_gettext('两次输入的新密码不一致'), 'danger')
            return redirect(url_for('admin.password'))

        user.set_password(new_pwd)
        # 修改密码清除锁定状态
        user.login_fail_count = 0
        user.locked_until = None
        db.session.commit()
        flash(_gettext('密码修改成功'), 'success')
        audit_log(OP_UPDATE, MODULE_SETTING, user.id, user.username,
                  {'action': 'change_password'})
        return redirect(url_for('admin.password'))
    return render_template('admin/setting/password.html')


# ============ 登录日志 ============

@admin_bp.route('/logs')
@permission_required('system:audit_log')
def logs():
    page = max(int(request.args.get('page', 1)), 1)
    pagination = LoginLog.query.order_by(LoginLog.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template('admin/setting/logs.html', logs=pagination.items, pagination=pagination)
