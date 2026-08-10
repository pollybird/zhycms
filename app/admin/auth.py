from datetime import datetime

from flask import (
    render_template, redirect, url_for, request,
    flash, session, Response, current_app
)
from flask_login import login_user, logout_user, current_user, login_required

from ..extensions import db
from ..models.user import User
from ..models.setting import Setting
from ..utils.helpers import log_login
from ..utils.captcha import generate_captcha
from ..utils.bootstrap import init_default_settings, create_admin, generate_demo_data
from ..utils.dbconfig import (
    build_uri, save_db_config, clear_db_config, test_connection, switch_engine,
    DEFAULT_PORTS,
)
from . import admin_auth_bp


def _is_initialized():
    """判断系统是否已初始化（存在管理员账号）。"""
    return User.query.filter_by(is_deleted=False).first() is not None


def _form_ctx(request):
    """从表单收集可回填字段，供校验失败时重新渲染 setup 页面。"""
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


@admin_auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    """系统初始化引导：首次访问时由用户设置数据库、管理员账号与是否生成演示数据。"""
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
        # 兼容旧表单字段 load_demo
        if not request.form.get('demo_type') and request.form.get('load_demo') == 'on':
            demo_type = ctx['demo_type'] = 'manufacturing'

        db_type = ctx['db_type'] or 'sqlite'
        db_password = request.form.get('db_password') or ''

        # 校验管理员信息
        if not username or len(username) < 3:
            flash('管理员账号至少 3 个字符', 'danger')
            return render_template('admin/setup.html', **ctx)

        if len(password) < 6:
            flash('管理员密码至少 6 个字符', 'danger')
            return render_template('admin/setup.html', **ctx)

        if password != password_confirm:
            flash('两次输入的密码不一致', 'danger')
            return render_template('admin/setup.html', **ctx)

        # 处理数据库选择
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

            # 连接成功：落盘配置并热切换引擎；失败则原子回滚到原库
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

            # 切库后可能连到了一个已初始化过的库，二次检查避免重复初始化
            if _is_initialized():
                flash('目标数据库已包含管理员账号，无需重复初始化，请直接登录', 'info')
                return redirect(url_for('admin_auth.login'))
        else:
            # SQLite：清除已保存配置，回退默认库文件
            clear_db_config()

        # 初始化默认配置
        init_default_settings()

        # 创建管理员
        admin = create_admin(username, password, nickname=nickname or '超级管理员')
        if admin is None:
            flash('初始化失败：已存在管理员账号', 'danger')
            return redirect(url_for('admin_auth.login'))

        # 生成演示数据
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


@admin_auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))

    # 未初始化时跳转到初始化页
    if not _is_initialized():
        return redirect(url_for('admin_auth.setup'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        captcha = (request.form.get('captcha') or '').strip().lower()
        session_captcha = (session.get('captcha') or '').lower()

        # 简易验证码校验
        if not captcha or captcha != session_captcha:
            flash('验证码错误', 'danger')
            log_login(username, 'failed', '验证码错误')
            return render_template('admin/login.html', username=username)

        user = User.query.filter_by(username=username, is_deleted=False).first()
        if user is None or not user.check_password(password):
            flash('账号或密码错误', 'danger')
            log_login(username, 'failed', '账号或密码错误')
            return render_template('admin/login.html', username=username)

        # 登录成功
        login_user(user, remember=False)
        user.last_login_at = datetime.now()
        user.last_login_ip = request.remote_addr or ''
        db.session.commit()
        session.pop('captcha', None)

        log_login(username, 'success')

        next_url = request.args.get('next')
        if not next_url or not next_url.startswith('/'):
            next_url = url_for('admin.dashboard')
        return redirect(next_url)

    return render_template('admin/login.html')


@admin_auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('admin_auth.login'))


@admin_auth_bp.route('/captcha')
def captcha():
    code, image_data = generate_captcha()
    session['captcha'] = code
    return Response(image_data, mimetype='image/png')
