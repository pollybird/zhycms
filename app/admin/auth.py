"""后台认证：登录/注销/初始化。

模块5 安全加固：
- 连续失败 5 次（可配置）锁定 10 分钟（可配置）
- 锁定时拒绝登录，日志标记 result=locked
- 登录成功后，对比上次登录城市/IP，若异常则在 session 中放 flash 供下次 dashboard 提醒
"""
import os
from datetime import datetime

from flask import (
    render_template, redirect, url_for, request,
    flash, session, Response, current_app
)
from flask_babel import gettext as _gettext
from flask_login import login_user, logout_user, current_user, login_required

from ..extensions import db
from ..models.user import User
from ..models.setting import Setting
from ..utils.helpers import log_login, audit_log
from ..utils.captcha import generate_captcha
from ..utils.bootstrap import init_default_settings, create_admin, generate_demo_data
from ..utils.dbconfig import (
    build_uri, save_db_config, clear_db_config, test_connection, switch_engine,
    DEFAULT_PORTS,
)
from ..utils.ip_locator import locate_city, is_abnormal_login
from ..models.audit import OP_LOGIN, OP_LOGOUT, MODULE_USER
from . import admin_auth_bp


def _login_max_fail():
    try:
        return max(int(Setting.get('login_max_fail', '5')), 1)
    except ValueError:
        return 5


def _login_lock_minutes():
    try:
        return max(int(Setting.get('login_lock_minutes', '10')), 1)
    except ValueError:
        return 10


def _is_initialized():
    return User.query.filter_by(is_deleted=False).first() is not None


def _db_managed_by_env():
    """数据库是否由环境变量托管（Docker Compose 通过 ZHYCMS_DB_URI 注入）。

    托管时初始化向导不展示、不处理数据库连接配置：容器网络内数据库主机为
    compose 服务名（如 db-mysql），若允许向导填写，用户按直觉填 localhost
    会连到应用容器自身，导致 connection refused。
    """
    return bool(os.environ.get('ZHYCMS_DB_URI') or os.environ.get('ZHOCMS_DB_URI'))


def _current_db_label():
    """当前生效引擎的数据库类型显示名。"""
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '') or ''
    if uri.startswith('mysql'):
        return 'MySQL'
    if uri.startswith('postgresql'):
        return 'PostgreSQL'
    return 'SQLite'


# 向导可勾选的官方插件（与 plugins/ 目录一一对应；第三方插件请在插件管理页启用）
SETUP_PLUGINS = ('banner', 'product', 'friend_link', 'form')


def _form_ctx(request):
    return {
        'username': (request.form.get('username') or '').strip(),
        'nickname': (request.form.get('nickname') or '').strip(),
        'demo_type': (request.form.get('demo_type') or 'none').strip(),
        'db_type': (request.form.get('db_type') or 'sqlite').strip(),
        'db_host': (request.form.get('db_host') or '').strip(),
        'db_port': (request.form.get('db_port') or '').strip(),
        'db_name': (request.form.get('db_name') or '').strip(),
        'db_user': (request.form.get('db_user') or '').strip(),
        'plugins': [s for s in request.form.getlist('plugins')
                    if s in SETUP_PLUGINS],
    }


# ============================================================
# 系统初始化
# ============================================================

@admin_auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    if _is_initialized():
        flash(_gettext('系统已初始化，请直接登录'), 'info')
        return redirect(url_for('admin_auth.login'))

    if request.method == 'POST':
        ctx = _form_ctx(request)
        ctx['db_managed'] = _db_managed_by_env()
        ctx['db_current_label'] = _current_db_label()
        username = ctx['username']
        password = request.form.get('password') or ''
        password_confirm = request.form.get('password_confirm') or ''
        nickname = ctx['nickname']
        demo_type = ctx['demo_type']
        if not request.form.get('demo_type') and request.form.get('load_demo') == 'on':
            demo_type = ctx['demo_type'] = 'manufacturing'

        db_type = ctx['db_type'] or 'sqlite'
        db_password = request.form.get('db_password') or ''

        if not username or len(username) < 3:
            flash(_gettext('管理员账号至少 3 个字符'), 'danger')
            return render_template('admin/setup.html', **ctx)
        if len(password) < 6:
            flash(_gettext('管理员密码至少 6 个字符'), 'danger')
            return render_template('admin/setup.html', **ctx)
        if password != password_confirm:
            flash(_gettext('两次输入的密码不一致'), 'danger')
            return render_template('admin/setup.html', **ctx)

        if ctx['db_managed']:
            # 数据库由环境变量托管（Docker Compose 部署）：
            # 直接使用启动时已连通的引擎，表结构由启动迁移保证，
            # 向导不接收任何连接参数（忽略表单中的 db_type/主机等字段）
            pass
        elif db_type in ('mysql', 'postgresql'):
            host = ctx['db_host']
            port = ctx['db_port'] or str(DEFAULT_PORTS[db_type])
            name = ctx['db_name']
            user = ctx['db_user']
            if not host or not name or not user:
                flash(_gettext('请填写完整的数据库连接信息（主机、数据库名、用户名）'), 'danger')
                return render_template('admin/setup.html', **ctx)
            try:
                new_uri = build_uri(db_type, host, port, name, user, db_password)
            except ValueError as e:
                flash(_gettext('数据库连接信息有误：%(error)s') % {'error': e}, 'danger')
                return render_template('admin/setup.html', **ctx)
            ok, msg = test_connection(new_uri)
            if not ok:
                flash(msg, 'danger')
                return render_template('admin/setup.html', **ctx)

            old_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI')
            try:
                save_db_config(db_type, new_uri, meta={
                    'host': host, 'port': int(port), 'database': name, 'user': user,
                })
                switch_engine(current_app, db, new_uri)
                db.create_all()
            except Exception as e:
                clear_db_config()
                try:
                    switch_engine(current_app, db, old_uri)
                except Exception:
                    pass
                flash(_gettext('切换到 %(dbtype)s 失败，已回退到原数据库：%(error)s') % {'dbtype': db_type, 'error': e}, 'danger')
                return render_template('admin/setup.html', **ctx)
            if _is_initialized():
                flash(_gettext('目标数据库已包含管理员账号，无需重复初始化，请直接登录'), 'info')
                return redirect(url_for('admin_auth.login'))
        else:
            clear_db_config()

        init_default_settings()

        admin = create_admin(username, password, nickname=nickname or '超级管理员')
        if admin is None:
            flash(_gettext('初始化失败：已存在管理员账号'), 'danger')
            return redirect(url_for('admin_auth.login'))

        if demo_type in ('manufacturing', 'service', 'manufacturing_en', 'default_en', 'education', 'catering'):
            # v2.2.0：行业演示数据与官方插件联动 —— 轮播图、友情链接在两个
            # 行业模板下均强制启用；制造业演示数据的产品页依赖 product 插件
            # （多图相册/规格参数/伪静态详情，演示钩子会把产品子栏目切换为
            # list_product 模板），同样强制启用。
            # 不生成演示数据时，仍按向导勾选启用。
            # v2.3.0：英文模板（manufacturing_en / default_en）同联动逻辑。
            # v2.6.3：教育（education）/ 餐饮（catering）行业。
            # v2.6.4：教育行业课程中心由社区插件 tutorial 提供，随安装自动启用
            # 并生成课程示例数据（社区插件不在向导勾选白名单内，仅走行业联动）。
            from ..plugin_system import enable_plugin, run_demo_data_hooks
            auto_plugins = {'banner', 'friend_link', 'form'}
            if demo_type in ('manufacturing', 'manufacturing_en'):
                auto_plugins.add('product')
            elif demo_type == 'education':
                auto_plugins.add('tutorial')
            # 用户勾选插件限定在向导白名单内；行业联动插件由系统强制启用
            for slug in dict.fromkeys(list(ctx['plugins']) + sorted(auto_plugins)):
                if slug not in SETUP_PLUGINS and slug not in auto_plugins:
                    continue
                err = enable_plugin(slug)
                if err:
                    flash(_gettext('插件启用失败：%(error)s') % {'error': err}, 'warning')
            try:
                if demo_type in ('manufacturing', 'service', 'education', 'catering'):
                    generate_demo_data(industry=demo_type)
                    for slug, err in run_demo_data_hooks(demo_type):
                        flash(_gettext('插件 %(slug)s 演示数据生成失败：%(error)s') % {'slug': slug, 'error': err}, 'warning')
                    label_map = {
                        'manufacturing': _gettext('制造业'),
                        'service': _gettext('服务业'),
                        'education': _gettext('教育行业'),
                        'catering': _gettext('餐饮行业'),
                    }
                    flash(_gettext('系统初始化完成，%(label)s演示数据已生成') % {'label': label_map[demo_type]}, 'success')
                elif demo_type == 'manufacturing_en':
                    # v2.3.0：英文模板需启用 i18n 并设默认语言为 en
                    from ..models.setting import Setting
                    Setting.set('i18n_enable', '1')
                    Setting.set('i18n_default_locale', 'en')
                    Setting.set('i18n_available_locales', 'zh,en')
                    generate_demo_data(industry='manufacturing_en')
                    for slug, err in run_demo_data_hooks('manufacturing_en'):
                        flash(_gettext('插件 %(slug)s 演示数据生成失败：%(error)s') % {'slug': slug, 'error': err}, 'warning')
                    flash(_gettext('系统初始化完成，Manufacturing (EN) 演示数据已生成'), 'success')
                elif demo_type == 'default_en':
                    # 英文默认主题：启用 i18n + 默认语言 en，不生成演示数据
                    from ..models.setting import Setting
                    Setting.set('i18n_enable', '1')
                    Setting.set('i18n_default_locale', 'en')
                    Setting.set('i18n_available_locales', 'zh,en')
                    Setting.set('site_theme', 'default_en')
                    flash(_gettext('系统初始化完成，请登录后台开始配置'), 'success')
            except Exception as e:
                db.session.rollback()
                flash(_gettext('演示数据生成失败：%(error)s') % {'error': e}, 'warning')
        else:
            # 不生成演示数据时同样启用勾选的插件
            from ..plugin_system import enable_plugin
            for slug in ctx['plugins']:
                err = enable_plugin(slug)
                if err:
                    flash(_gettext('插件启用失败：%(error)s') % {'error': err}, 'warning')
            flash(_gettext('系统初始化完成，请登录后台开始配置'), 'success')

        return redirect(url_for('admin_auth.login'))

    # 默认勾选官方轮播图 + 产品插件（可取消；选择行业演示数据时会自动补齐联动插件）
    return render_template(
        'admin/setup.html',
        plugins=list(SETUP_PLUGINS),
        db_managed=_db_managed_by_env(),
        db_current_label=_current_db_label(),
    )


# ============================================================
# 登录 / 注销
# ============================================================

@admin_auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))

    if not _is_initialized():
        return redirect(url_for('admin_auth.setup'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        captcha = (request.form.get('captcha') or '').strip().lower()
        session_captcha = (session.get('captcha') or '').lower()

        if not captcha or captcha != session_captcha:
            flash(_gettext('验证码错误'), 'danger')
            log_login(username, 'failed', '验证码错误')
            return render_template('admin/login.html', username=username)

        user = User.query.filter_by(username=username, is_deleted=False).first()

        # 模块5：账号锁定校验
        if user and user.is_locked:
            remaining = int((user.locked_until - datetime.now()).total_seconds())
            mm, ss = divmod(remaining, 60) if remaining > 0 else (0, 0)
            msg = _gettext('账号已被锁定，请 %(mm)d 分 %(ss)d 秒后再试') % {'mm': mm, 'ss': ss}
            flash(msg, 'danger')
            log_login(username, 'locked', msg, user_id=user.id)
            audit_log(OP_LOGIN, MODULE_USER, target_id=user.id, target_name=username,
                      detail=f'登录失败：账号锁定（连续密码错误超过{_login_max_fail()}次）')
            return render_template('admin/login.html', username=username)

        if user is None or not user.is_active_flag or not user.check_password(password):
            # 密码错误：记录失败计数；只有该账号存在才计数（避免用枚举用户名来消耗计数）
            if user and not user.is_deleted:
                user.record_login_fail(max_fail=_login_max_fail(),
                                       lock_minutes=_login_lock_minutes())
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                if user.is_locked:
                    _lf = _login_max_fail()
                    _ll = _login_lock_minutes()
                    msg = _gettext('连续密码错误 %(n)d 次，账号锁定 %(m)d 分钟') % {'n': _lf, 'm': _ll}
                    log_login(username, 'locked', msg, user_id=user.id)
                    audit_log(OP_LOGIN, MODULE_USER, target_id=user.id, target_name=username, detail=msg)
                    flash(msg, 'danger')
                    return render_template('admin/login.html', username=username)
            flash(_gettext('账号或密码错误'), 'danger')
            log_login(username, 'failed', '账号或密码错误', user_id=user.id if user else None)
            return render_template('admin/login.html', username=username)

        # 登录成功
        login_user(user, remember=False)
        user.reset_login_fail()

        # IP / 城市 + 异地提醒
        ip = request.remote_addr or ''
        last_ip = user.last_login_ip or ''
        try:
            city = locate_city(ip)
        except Exception:
            city = ''
        abnormal = (Setting.get('login_abnormal_city_alert') == 'on'
                    and is_abnormal_login(ip, last_ip))
        if abnormal:
            session['login_abnormal_alert'] = {
                'city': city or '未知',
                'ip': ip,
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }

        user.last_login_at = datetime.now()
        user.last_login_ip = ip
        if city:
            user.last_login_city = city
        db.session.commit()
        session.pop('captcha', None)

        log_login(username, 'success', user_id=user.id, city=city)
        audit_log(OP_LOGIN, MODULE_USER, target_id=user.id, target_name=username,
                  detail={'ip': ip, 'city': city, 'abnormal': abnormal})

        # 安全修复（v2.4.1）：拒绝协议相对 URL（如 //evil.com），
        # 只允许站内相对路径，杜绝开放重定向钓鱼
        next_url = request.args.get('next') or ''
        if (not next_url
                or not next_url.startswith('/')
                or next_url.startswith('//')
                or next_url.startswith('/\\')):
            next_url = url_for('admin.dashboard')
        return redirect(next_url)

    return render_template('admin/login.html')


def divmax(a, b):
    """避免 lint 报错的临时 helper。"""
    return divmod(a, b) if b else (0, 0)


@admin_auth_bp.route('/logout')
@login_required
def logout():
    uid = getattr(current_user, 'id', None)
    uname = getattr(current_user, 'username', '')
    audit_log(OP_LOGOUT, MODULE_USER, target_id=uid, target_name=uname,
              detail={'ip': request.remote_addr or ''})
    logout_user()
    return redirect(url_for('admin_auth.login'))


@admin_auth_bp.route('/captcha')
def captcha():
    code, image_data = generate_captcha()
    session['captcha'] = code
    return Response(image_data, mimetype='image/png')
