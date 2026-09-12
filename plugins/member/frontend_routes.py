"""前台会员路由蓝本。

路由：
  /register                         注册
  /login                            登录（用户名密码 + 手机验证码双方式）
  /logout                           退出
  /forgot-password                  手机验证码找回/重置密码
  /sms/send                         发送短信验证码（AJAX/JSON）
  /oauth/<provider>                 微信/QQ 一键登录入口
  /oauth/<provider>/callback        OAuth 回调（登录 / 绑定 / 自动建号）
  /member                           会员中心
  /member/profile                   资料编辑
  /member/password                  修改密码

模板：插件内置 templates/frontend/*.html，随插件分发，不写入主题目录。
未启用插件时所有路由 404。
"""
import re
import secrets
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, jsonify, abort,
)
from flask_babel import gettext as _gettext

from app.extensions import db
from app.plugin_system import plugin_enabled
from app.constants import Upload as _Upload
from app.utils.uploads import save_upload_file

from .models import Member, MemberOauth
from .security import (
    login_member, logout_member, current_member, member_required,
)
from . import settings as cfg
from . import sms as sms_svc
from . import oauth as oauth_svc

member_frontend = Blueprint('member_frontend', __name__,
                            template_folder='templates')

USERNAME_RE = re.compile(r'^[A-Za-z0-9_\-]{3,32}$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _gate(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('member'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def _build_nav():
    from app.frontend.views import _build_nav as _nav
    return _nav()


def _seo(**kwargs):
    from app.frontend.views import _seo as _s
    return _s(**kwargs)


def _safe_next(target, default='/member'):
    """仅允许站内相对路径，防开放重定向。"""
    if target and target.startswith('/') and not target.startswith('//'):
        return target
    return default


def _find_member(identifier):
    """按用户名 / 手机号 / 邮箱查找会员。"""
    return Member.query.filter(
        (Member.username == identifier)
        | (Member.phone == identifier)
        | (Member.email == identifier),
        Member.is_deleted == False,
    ).first()


def _render(name, **ctx):
    # 调用方传入的 name 已含 .html 后缀
    return render_template(f'frontend/{name}', nav=_build_nav(), seo=_seo(), **ctx)


# ============================================================
# 注册
# ============================================================

@member_frontend.route('/register', methods=['GET', 'POST'])
@_gate
def register():
    if current_member() is not None:
        return redirect(url_for('member_frontend.center'))
    if not cfg.is_on('member_register_enable'):
        flash(_gettext('本站当前未开放注册'), 'warning')
        return redirect(url_for('member_frontend.login'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        confirm = request.form.get('password_confirm') or ''
        phone = (request.form.get('phone') or '').strip()
        email = (request.form.get('email') or '').strip()

        if not USERNAME_RE.match(username):
            flash(_gettext('用户名需为 3-32 位字母、数字、下划线或连字符'), 'danger')
        elif len(password) < 6:
            flash(_gettext('密码至少 6 位'), 'danger')
        elif password != confirm:
            flash(_gettext('两次输入的密码不一致'), 'danger')
        elif phone and not sms_svc.valid_phone(phone):
            flash(_gettext('手机号格式不正确'), 'danger')
        elif email and not EMAIL_RE.match(email):
            flash(_gettext('邮箱格式不正确'), 'danger')
        elif Member.query.filter_by(username=username, is_deleted=False).first():
            flash(_gettext('用户名已被注册'), 'danger')
        elif phone and Member.query.filter_by(phone=phone, is_deleted=False).first():
            flash(_gettext('手机号已被注册'), 'danger')
        elif email and Member.query.filter_by(email=email, is_deleted=False).first():
            flash(_gettext('邮箱已被注册'), 'danger')
        elif not request.form.get('agree'):
            flash(_gettext('请阅读并同意注册协议'), 'danger')
        else:
            member = Member(
                username=username, nickname=username,
                phone=phone or None, email=email or None,
            )
            member.set_password(password)
            db.session.add(member)
            db.session.commit()
            login_member(member)
            flash(_gettext('注册成功，欢迎加入！'), 'success')
            return redirect(_safe_next(request.form.get('next'), '/'))

    return _render('register.html')


# ============================================================
# 登录 / 退出
# ============================================================

@member_frontend.route('/login', methods=['GET', 'POST'])
@_gate
def login():
    if current_member() is not None:
        return redirect(url_for('member_frontend.center'))

    if request.method == 'POST':
        login_type = request.form.get('login_type', 'password')
        next_url = _safe_next(request.form.get('next'), '/')

        if login_type == 'sms':
            if not cfg.is_on('member_login_sms_enable'):
                flash(_gettext('短信登录未开启'), 'danger')
                return _render('login.html')
            phone = (request.form.get('phone') or '').strip()
            code = (request.form.get('code') or '').strip()
            if not sms_svc.valid_phone(phone):
                flash(_gettext('手机号格式不正确'), 'danger')
            elif not sms_svc.verify_code(phone, code, purpose='login'):
                flash(_gettext('验证码错误或已失效'), 'danger')
            else:
                member = Member.query.filter_by(
                    phone=phone, is_deleted=False).first()
                if member is None:
                    if not cfg.is_on('member_auto_register_sms'):
                        flash(_gettext('该手机号尚未注册'), 'danger')
                    else:
                        member = Member(
                            username='m' + phone, nickname=phone, phone=phone)
                        db.session.add(member)
                        db.session.commit()
                if member is not None:
                    if not _do_login_checks(member):
                        return _render('login.html')
                    login_member(member, remember=bool(request.form.get('remember')))
                    flash(_gettext('登录成功'), 'success')
                    return redirect(next_url)
            return _render('login.html')

        # 用户名 / 手机 / 邮箱 + 密码
        identifier = (request.form.get('identifier') or '').strip()
        password = request.form.get('password') or ''
        member = _find_member(identifier) if identifier else None
        if member is None or not member.check_password(password):
            if member is not None:
                member.record_login_fail()
                db.session.commit()
            flash(_gettext('账号或密码错误'), 'danger')
        elif not _do_login_checks(member):
            return _render('login.html')
        else:
            login_member(member, remember=bool(request.form.get('remember')))
            flash(_gettext('登录成功'), 'success')
            return redirect(next_url)

    return _render('login.html')


def _do_login_checks(member):
    """锁定/禁用状态检查，通过返回 True。"""
    if member.is_locked:
        flash(_gettext('账号已锁定，请稍后再试'), 'danger')
        return False
    if not member.is_enabled:
        flash(_gettext('账号已被禁用，请联系管理员'), 'danger')
        return False
    member.reset_login_fail()
    member.last_login_at = datetime.now()
    member.last_login_ip = request.remote_addr or ''
    db.session.commit()
    return True


@member_frontend.route('/logout')
@_gate
def logout():
    logout_member()
    flash(_gettext('您已安全退出'), 'info')
    return redirect(_safe_next(request.referrer if request.referrer and request.referrer.startswith(request.host_url) else None, '/'))


# ============================================================
# 短信验证码
# ============================================================

@member_frontend.route('/sms/send', methods=['POST'])
@_gate
def sms_send():
    if request.is_json:
        phone = (request.json.get('phone') or '').strip()
    else:
        phone = (request.form.get('phone') or '').strip()
    purpose = (request.form.get('purpose') or 'login').strip()
    if purpose not in sms_svc.PURPOSE_LABELS:
        return jsonify({'ok': False, 'error': '验证码用途无效'}), 400
    if purpose == 'login' and not cfg.is_on('member_login_sms_enable'):
        return jsonify({'ok': False, 'error': '短信登录未开启'}), 403

    ok, err = sms_svc.issue_code(phone, purpose=purpose, ip=request.remote_addr or '')
    return jsonify({'ok': ok, 'error': err}), (200 if ok else 400)


# ============================================================
# 找回密码（手机验证码重置）
# ============================================================

@member_frontend.route('/forgot-password', methods=['GET', 'POST'])
@_gate
def forgot_password():
    if current_member() is not None:
        return redirect(url_for('member_frontend.change_password'))
    if request.method == 'POST':
        phone = (request.form.get('phone') or '').strip()
        code = (request.form.get('code') or '').strip()
        password = request.form.get('password') or ''
        confirm = request.form.get('password_confirm') or ''

        member = Member.query.filter_by(phone=phone, is_deleted=False).first()
        if not sms_svc.valid_phone(phone):
            flash(_gettext('手机号格式不正确'), 'danger')
        elif member is None:
            flash(_gettext('该手机号尚未注册'), 'danger')
        elif not sms_svc.verify_code(phone, code, purpose='reset'):
            flash(_gettext('验证码错误或已失效'), 'danger')
        elif len(password) < 6:
            flash(_gettext('新密码至少 6 位'), 'danger')
        elif password != confirm:
            flash(_gettext('两次输入的密码不一致'), 'danger')
        else:
            member.set_password(password)
            db.session.commit()
            flash(_gettext('密码重置成功，请使用新密码登录'), 'success')
            return redirect(url_for('member_frontend.login'))
    return _render('forgot.html')


# ============================================================
# OAuth：微信 / QQ
# ============================================================

@member_frontend.route('/oauth/<provider>')
@_gate
def oauth_start(provider):
    if provider not in oauth_svc.PROVIDERS or not oauth_svc.is_enabled(provider):
        abort(404)
    state = secrets.token_urlsafe(24)
    session['oauth_state'] = state
    nxt = request.args.get('next')
    session['oauth_next'] = nxt if nxt and nxt.startswith('/') and not nxt.startswith('//') else ''
    callback = url_for('member_frontend.oauth_callback', provider=provider,
                       _external=True)
    return redirect(oauth_svc.authorize_url(provider, callback, state))


@member_frontend.route('/oauth/<provider>/callback')
@_gate
def oauth_callback(provider):
    if provider not in oauth_svc.PROVIDERS or not oauth_svc.is_enabled(provider):
        abort(404)
    state = request.args.get('state') or ''
    code = request.args.get('code') or ''
    if not state or state != session.pop('oauth_state', None):
        flash(_gettext('登录状态已过期，请重试'), 'danger')
        return redirect(url_for('member_frontend.login'))
    if not code:
        flash(_gettext('授权失败，未获取到授权码'), 'danger')
        return redirect(url_for('member_frontend.login'))

    callback = url_for('member_frontend.oauth_callback', provider=provider,
                       _external=True)
    try:
        profile = oauth_svc.fetch_profile(provider, code, callback)
    except Exception as e:
        flash(_gettext('第三方登录失败：%(err)s', err=str(e)), 'danger')
        return redirect(url_for('member_frontend.login'))

    binding = MemberOauth.query.filter_by(
        provider=provider, openid=profile['openid']).first()

    # 已绑定 → 直接登录
    if binding is not None:
        member = db.session.get(Member, binding.member_id)
        if member is None or member.is_deleted or not member.is_enabled:
            flash(_gettext('账号不可用，请联系管理员'), 'danger')
            return redirect(url_for('member_frontend.login'))
        login_member(member)
        flash(_gettext('登录成功'), 'success')
        return redirect(_safe_next(session.pop('oauth_next', ''), '/member'))

    # 已登录会员 → 绑定该第三方账号
    member = current_member()
    if member is not None:
        _bind_oauth(member, provider, profile)
        flash(_gettext('账号绑定成功'), 'success')
        return redirect(url_for('member_frontend.profile'))

    # 未绑定且未登录 → 按配置自动建号
    if not cfg.is_on('member_oauth_auto_register'):
        flash(_gettext('该第三方账号尚未绑定，请先注册或登录后再绑定'), 'warning')
        return redirect(url_for('member_frontend.register'))

    member = Member(
        username=_unique_oauth_username(provider, profile['openid']),
        nickname=profile['nickname'] or provider,
        avatar=profile['avatar'] or None,
    )
    db.session.add(member)
    db.session.commit()
    _bind_oauth(member, provider, profile)
    login_member(member)
    flash(_gettext('登录成功，已为您自动创建账号'), 'success')
    return redirect(_safe_next(session.pop('oauth_next', ''), '/member'))


def _bind_oauth(member, provider, profile):
    row = MemberOauth(
        member_id=member.id, provider=provider, openid=profile['openid'],
        unionid=profile.get('unionid') or '',
        nickname=profile.get('nickname') or '',
        avatar=profile.get('avatar') or '',
    )
    db.session.add(row)
    db.session.commit()


def _unique_oauth_username(provider, openid):
    base = f'{provider}_{(openid or "")[:12]}'
    base = re.sub(r'[^A-Za-z0-9_\-]', '_', base)[:32]
    name = base
    i = 1
    while Member.query.filter_by(username=name, is_deleted=False).first():
        suffix = f'_{i}'
        name = (base[:32 - len(suffix)] + suffix)
        i += 1
    return name


# ============================================================
# 会员中心 / 资料 / 改密
# ============================================================

@member_frontend.route('/member')
@_gate
@member_required
def center():
    member = current_member()
    bindings = {b.provider for b in member.oauths.all()}
    return _render('center.html', member=member, bindings=bindings)


@member_frontend.route('/member/profile', methods=['GET', 'POST'])
@_gate
@member_required
def profile():
    member = current_member()
    if request.method == 'POST':
        nickname = (request.form.get('nickname') or '').strip()
        email = (request.form.get('email') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        gender = request.form.get('gender') or ''
        signature = (request.form.get('signature') or '').strip()

        if not nickname:
            flash(_gettext('昵称必填'), 'danger')
        elif email and not EMAIL_RE.match(email):
            flash(_gettext('邮箱格式不正确'), 'danger')
        elif phone and not sms_svc.valid_phone(phone):
            flash(_gettext('手机号格式不正确'), 'danger')
        elif email and Member.query.filter(
                Member.email == email, Member.id != member.id,
                Member.is_deleted == False).first():
            flash(_gettext('邮箱已被其他账号使用'), 'danger')
        elif phone and Member.query.filter(
                Member.phone == phone, Member.id != member.id,
                Member.is_deleted == False).first():
            flash(_gettext('手机号已被其他账号使用'), 'danger')
        else:
            member.nickname = nickname
            member.email = email or None
            member.phone = phone or None
            member.gender = gender if gender in ('male', 'female') else ''
            member.signature = signature[:255]

            avatar_file = request.files.get('avatar')
            if avatar_file and avatar_file.filename:
                rel, url, err = save_upload_file(
                    avatar_file, sub_dir='member',
                    allowed_exts=list(_Upload.IMAGE_EXTS))
                if err:
                    flash(_gettext('头像上传失败：%(err)s', err=err), 'danger')
                else:
                    member.avatar = url
            db.session.commit()
            flash(_gettext('资料已更新'), 'success')
            return redirect(url_for('member_frontend.profile'))

    bindings = {b.provider for b in member.oauths.all()}
    return _render('profile.html', member=member, bindings=bindings)


@member_frontend.route('/member/password', methods=['GET', 'POST'])
@_gate
@member_required
def change_password():
    member = current_member()
    if request.method == 'POST':
        old = request.form.get('old_password') or ''
        new = request.form.get('new_password') or ''
        confirm = request.form.get('password_confirm') or ''
        if not member.check_password(old):
            flash(_gettext('原密码不正确'), 'danger')
        elif len(new) < 6:
            flash(_gettext('新密码至少 6 位'), 'danger')
        elif new != confirm:
            flash(_gettext('两次输入的新密码不一致'), 'danger')
        elif new == old:
            flash(_gettext('新密码不能与原密码相同'), 'danger')
        else:
            member.set_password(new)
            db.session.commit()
            flash(_gettext('密码修改成功，下次登录请使用新密码'), 'success')
            return redirect(url_for('member_frontend.center'))
    return _render('password.html', member=member)
