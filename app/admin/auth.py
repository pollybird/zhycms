"""后台认证：登录/注销/初始化。

模块5 安全加固：
- 连续失败 5 次（可配置）锁定 10 分钟（可配置）
- 锁定时拒绝登录，日志标记 result=locked
- 登录成功后，对比上次登录城市/IP，若异常则在 session 中放 flash 供下次 dashboard 提醒
"""
from datetime import datetime

from flask import (
    render_template, redirect, url_for, request,
    flash, session, Response, current_app
)
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
    }


# ============================================================
# 系统初始化
# ============================================================

@admin_auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    if _is_initialized():
        flash('系统已初始化，请直接登录', 'info')
        return redirect(url_for('admin_auth.login'))

    if request.method == 'POST':
        ctx = _form_ctx(request)
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
            flash('管理员账号至少 3 个字符', 'danger')
            return render_template('admin/setup.html', **ctx)
        if len(password) < 6:
            flash('管理员密码至少 6 个字符', 'danger')
            return render_template('admin/setup.html', **ctx)
        if password != password_confirm:
            flash('两次输入的密码不一致', 'danger')
            return render_template('admin/setup.html', **ctx)

        if db_type in ('mysql', 'postgresql'):
            host = ctx['db_host']
            port = ctx['db_port'] or str(DEFAULT_PORTS[db_type])
            name = ctx['db_name']
            user = ctx['db_user']
            if not host or not name or not user:
                flash('请填写完整的数据库连接信息（主机、数据库名、用户名）', 'danger')
                return render_template('admin/setup.html', **ctx)
            try:
                new_uri = build_uri(db_type, host, port, name, user, db_password)
            except ValueError as e:
                flash(f'数据库连接信息有误：{e}', 'danger')
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
                flash(f'切换到 {db_type} 失败，已回退到原数据库：{e}', 'danger')
                return render_template('admin/setup.html', **ctx)
            if _is_initialized():
                flash('目标数据库已包含管理员账号，无需重复初始化，请直接登录', 'info')
                return redirect(url_for('admin_auth.login'))
        else:
            clear_db_config()

        init_default_settings()

        admin = create_admin(username, password, nickname=nickname or '超级管理员')
        if admin is None:
            flash('初始化失败：已存在管理员账号', 'danger')
            return redirect(url_for('admin_auth.login'))

        if demo_type in ('manufacturing', 'service'):
            try:
                generate_demo_data(industry=demo_type)
                label = '制造业' if demo_type == 'manufacturing' else '服务业'
                flash(f'系统初始化完成，{label}演示数据已生成', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'演示数据生成失败：{e}', 'warning')
        else:
            flash('系统初始化完成，请登录后台开始配置', 'success')

        return redirect(url_for('admin_auth.login'))

    return render_template('admin/setup.html')


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
            flash('验证码错误', 'danger')
            log_login(username, 'failed', '验证码错误')
            return render_template('admin/login.html', username=username)

        user = User.query.filter_by(username=username, is_deleted=False).first()

        # 模块5：账号锁定校验
        if user and user.is_locked:
            remaining = int((user.locked_until - datetime.now()).total_seconds())
            mm, ss = divmod(remaining, 60) if remaining > 0 else (0, 0)
            msg = f'账号已被锁定，请 {mm} 分 {ss} 秒后再试'
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
                    msg = f'连续密码错误 {_login_max_fail()} 次，账号锁定 {_login_lock_minutes()} 分钟'
                    log_login(username, 'locked', msg, user_id=user.id)
                    audit_log(OP_LOGIN, MODULE_USER, target_id=user.id, target_name=username, detail=msg)
                    flash(msg, 'danger')
                    return render_template('admin/login.html', username=username)
            flash('账号或密码错误', 'danger')
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

        next_url = request.args.get('next')
        if not next_url or not next_url.startswith('/'):
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
