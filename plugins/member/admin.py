"""前台会员插件：后台管理。

路由挂核心 admin_bp（endpoint 归入 admin.*）：
  /members                       会员列表（搜索/筛选/分页）
  /members/<id>/edit             编辑会员（资料/状态/重置密码）
  /members/<id>/delete           删除会员
  /member/settings               会员设置（基础/短信/微信/QQ 四组）
  /member/columns                栏目对前台会员的可见性配置

未启用插件时所有路由 404。
"""
from functools import wraps

from flask import render_template, redirect, url_for, request, flash, abort
from flask_babel import gettext as _gettext

from app.extensions import db
from app.admin import admin_bp
from app.models.audit import OP_UPDATE, OP_DELETE, OP_CREATE
from app.models.column import Column
from app.utils.helpers import permission_required, audit_log, clear_content_cache
from app.plugin_system import plugin_enabled

from .models import Member
from . import settings as cfg

MODULE_MEMBER = 'member'


def _gate(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('member'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


# ============ 会员列表 / 编辑 / 删除 ============

@admin_bp.route('/members')
@_gate
@permission_required('member:manage')
def member_index():
    page = max(int(request.args.get('page', 1)), 1)
    keyword = (request.args.get('keyword') or '').strip()
    status = (request.args.get('status') or '').strip()

    query = Member.query.filter_by(is_deleted=False)
    if keyword:
        like = f'%{keyword}%'
        query = query.filter(
            db.or_(Member.username.like(like), Member.nickname.like(like),
                   Member.phone.like(like), Member.email.like(like)))
    if status == 'enabled':
        query = query.filter_by(is_enabled=True)
    elif status == 'disabled':
        query = query.filter_by(is_enabled=False)

    pagination = query.order_by(Member.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False)

    return render_template(
        'admin/member/index.html',
        members=pagination.items, pagination=pagination,
        keyword=keyword, status=status,
    )


@admin_bp.route('/members/<int:mid>/edit', methods=['GET', 'POST'])
@_gate
@permission_required('member:manage')
def member_edit(mid):
    member = db.session.get(Member, mid)
    if member is None or member.is_deleted:
        abort(404)

    if request.method == 'POST':
        nickname = (request.form.get('nickname') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        email = (request.form.get('email') or '').strip()
        gender = request.form.get('gender') or ''
        new_password = request.form.get('new_password') or ''

        if not nickname:
            flash(_gettext('昵称必填'), 'danger')
        elif phone and Member.query.filter(
                Member.phone == phone, Member.id != member.id,
                Member.is_deleted == False).first():
            flash(_gettext('手机号已被其他会员使用'), 'danger')
        elif email and Member.query.filter(
                Member.email == email, Member.id != member.id,
                Member.is_deleted == False).first():
            flash(_gettext('邮箱已被其他会员使用'), 'danger')
        elif new_password and len(new_password) < 6:
            flash(_gettext('新密码至少 6 位'), 'danger')
        else:
            member.nickname = nickname
            member.phone = phone or None
            member.email = email or None
            member.gender = gender if gender in ('male', 'female') else ''
            member.is_enabled = (request.form.get('is_enabled') == 'on')
            if new_password:
                member.set_password(new_password)
            db.session.commit()
            audit_log(OP_UPDATE, MODULE_MEMBER, member.id, member.username,
                      {'phone': member.phone, 'enabled': member.is_enabled})
            flash(_gettext('会员信息已更新'), 'success')
            return redirect(url_for('admin.member_index'))

    return render_template('admin/member/form.html', member=member)


@admin_bp.route('/members/<int:mid>/delete', methods=['POST'])
@_gate
@permission_required('member:manage')
def member_delete(mid):
    member = db.session.get(Member, mid)
    if member is not None and not member.is_deleted:
        member.is_deleted = True
        member.is_enabled = False
        db.session.commit()
        audit_log(OP_DELETE, MODULE_MEMBER, member.id, member.username, None)
        flash(_gettext('会员已删除'), 'success')
    return redirect(url_for('admin.member_index'))


# ============ 会员设置（基础/短信/微信/QQ） ============

@admin_bp.route('/member/settings', methods=['GET', 'POST'])
@_gate
@permission_required('member:manage')
def member_settings():
    if request.method == 'POST':
        group = request.form.get('group') or 'basic'
    else:
        group = request.args.get('group') or 'basic'
    if group not in cfg.GROUP_KEYS:
        group = 'basic'

    if request.method == 'POST':
        cfg.save_group(group, request.form)
        clear_content_cache()
        audit_log(OP_UPDATE, MODULE_MEMBER, None, f'settings:{group}', None)
        flash(_gettext('设置已保存'), 'success')
        return redirect(url_for('admin.member_settings', group=group))

    values = {key: cfg.cfg(key) for key in cfg.GROUP_KEYS[group]}
    return render_template(
        'admin/member/settings.html',
        group=group, groups=cfg.FIELD_GROUPS,
        values=values, group_keys=cfg.GROUP_KEYS[group],
    )


# ============ 栏目会员可见性 ============

@admin_bp.route('/member/columns', methods=['GET', 'POST'])
@_gate
@permission_required('member:manage')
def member_columns():
    if request.method == 'POST':
        visible_ids = set()
        for raw in request.form.getlist('member_only'):
            try:
                visible_ids.add(int(raw))
            except (TypeError, ValueError):
                continue
        columns = Column.query.filter_by(is_deleted=False).all()
        changed = 0
        for col in columns:
            flag = col.id in visible_ids
            if bool(col.member_only) != flag:
                col.member_only = flag
                changed += 1
        db.session.commit()
        if changed:
            clear_content_cache()
        audit_log(OP_CREATE, MODULE_MEMBER, None, 'column_visibility',
                  {'member_only_ids': sorted(visible_ids)})
        flash(_gettext('栏目可见性已更新（%(n)s 项变更）', n=changed), 'success')
        return redirect(url_for('admin.member_columns'))

    columns = Column.get_tree(enabled_only=False)
    tree = Column.build_nested(columns)
    return render_template('admin/member/columns.html', columns=columns, tree=tree)
