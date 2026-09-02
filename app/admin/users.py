"""模块1：多用户RBAC权限管理 —— 后台账号、角色、栏目专属权限管理。"""
from datetime import datetime

from flask import (
    render_template, redirect, url_for, request, flash, abort, jsonify
)
from flask_babel import gettext as _gettext
from flask_login import current_user

from ..extensions import db
from ..models.user import User
from ..models.column import Column
from ..models.rbac import (
    Role, Permission, UserRole, UserColumnPermission,
    ROLE_SUPER_ADMIN, ROLE_CONTENT_EDITOR,
)
from ..utils.helpers import permission_required, audit_log
from ..models.audit import (
    OP_CREATE, OP_UPDATE, OP_DELETE, OP_USER_MANAGE,
    MODULE_USER, MODULE_ROLE,
)
from . import admin_bp


# ============================================================
# 工具函数
# ============================================================

def _build_tree_with_depth(columns, parent_id=None, depth=0):
    """构建带层级的栏目列表。"""
    result = []
    for col in columns:
        if col.parent_id == parent_id:
            col._depth = depth
            result.append(col)
            result.extend(_build_tree_with_depth(columns, col.id, depth + 1))
    return result


def _get_roles_for_form():
    return Role.query.filter_by(is_deleted=False).order_by(Role.id.asc()).all()


def _get_all_columns_tree():
    cols = Column.query.filter_by(is_deleted=False).all()
    return _build_tree_with_depth(cols)


# ============================================================
# 后台账号管理
# ============================================================

@admin_bp.route('/users')
@permission_required('system:user_manage')
def user_index():
    page = max(int(request.args.get('page', 1)), 1)
    keyword = (request.args.get('keyword') or '').strip()
    role_filter = request.args.get('role', '')
    status_filter = request.args.get('status', '')

    query = User.query.filter_by(is_deleted=False)
    if keyword:
        like = f'%{keyword}%'
        query = query.filter(
            db.or_(User.username.like(like), User.nickname.like(like), User.email.like(like))
        )
    if status_filter == 'active':
        query = query.filter_by(is_active_flag=True)
    elif status_filter == 'disabled':
        query = query.filter_by(is_active_flag=False)

    pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    users = pagination.items

    # 预加载角色信息
    user_ids = [u.id for u in users]
    if user_ids:
        links = UserRole.query.filter(UserRole.user_id.in_(user_ids)).all()
        user_roles = {}
        for l in links:
            user_roles.setdefault(l.user_id, []).append(l.role)
        for u in users:
            u._roles = user_roles.get(u.id, [])
    else:
        for u in users:
            u._roles = []

    roles = _get_roles_for_form()
    return render_template(
        'admin/users/index.html',
        users=users, pagination=pagination,
        keyword=keyword, role_filter=role_filter, status_filter=status_filter,
        roles=roles,
    )


@admin_bp.route('/users/create', methods=['GET', 'POST'])
@permission_required('system:user_manage')
def user_create():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip().lower()
        nickname = (request.form.get('nickname') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''
        confirm = request.form.get('confirm_password') or ''
        role_ids = request.form.getlist('role_ids[]')
        is_active = request.form.get('is_active_flag') == 'on'
        is_super = request.form.get('is_super') == 'on'

        if not username or len(username) < 3:
            flash(_gettext('用户名至少 3 位'), 'danger')
        elif User.query.filter_by(username=username, is_deleted=False).first():
            flash(_gettext('用户名已存在'), 'danger')
        elif len(password) < 6:
            flash(_gettext('密码至少 6 位'), 'danger')
        elif password != confirm:
            flash(_gettext('两次输入的密码不一致'), 'danger')
        else:
            try:
                role_ids = [int(x) for x in role_ids if x.isdigit()]
            except ValueError:
                role_ids = []

            user = User(username=username, nickname=nickname or username,
                        email=email, is_active_flag=is_active, is_super=is_super)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()

            # 分配角色
            for rid in role_ids:
                if Role.query.get(rid):
                    db.session.add(UserRole(user_id=user.id, role_id=rid))

            # 栏目专属权限
            col_ids = request.form.getlist('column_ids[]')
            col_ids = [int(x) for x in col_ids if x.isdigit()]
            can_review_ids = set(request.form.getlist('can_review_ids[]'))
            can_publish_ids = set(request.form.getlist('can_publish_ids[]'))
            for cid in col_ids:
                db.session.add(UserColumnPermission(
                    user_id=user.id, column_id=cid,
                    can_review=str(cid) in can_review_ids,
                    can_publish=str(cid) in can_publish_ids,
                ))

            db.session.commit()
            flash(_gettext('账号创建成功'), 'success')
            audit_log(OP_CREATE, MODULE_USER, user.id, user.username,
                      {'nickname': nickname, 'email': email, 'role_ids': role_ids})
            return redirect(url_for('admin.user_index'))

    return render_template(
        'admin/users/form.html',
        user=None, roles=_get_roles_for_form(),
        columns=_get_all_columns_tree(),
    )


@admin_bp.route('/users/<int:uid>/edit', methods=['GET', 'POST'])
@permission_required('system:user_manage')
def user_edit(uid):
    user = User.query.filter_by(id=uid, is_deleted=False).first()
    if user is None:
        abort(404)
    # 禁止修改自己的权限（防止越权操作，让超级管理员之间互改）
    if user.id == current_user.id and not current_user.is_super:
        flash(_gettext('不能修改自己的账号权限，请联系其他超级管理员'), 'warning')
        return redirect(url_for('admin.user_index'))

    if request.method == 'POST':
        nickname = (request.form.get('nickname') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''
        confirm = request.form.get('confirm_password') or ''
        role_ids = request.form.getlist('role_ids[]')
        is_active = request.form.get('is_active_flag') == 'on'
        is_super = request.form.get('is_super') == 'on'

        if password and len(password) < 6:
            flash(_gettext('密码至少 6 位'), 'danger')
        elif password and password != confirm:
            flash(_gettext('两次输入的密码不一致'), 'danger')
        else:
            try:
                role_ids = [int(x) for x in role_ids if x.isdigit()]
            except ValueError:
                role_ids = []

            user.nickname = nickname or user.username
            user.email = email
            user.is_active_flag = is_active
            # 系统第一个超级管理员 is_super 不可被取消（兜底）
            if not (user.is_super and User.query.filter_by(is_super=True, is_deleted=False).count() <= 1):
                user.is_super = is_super
            if password:
                user.set_password(password)

            # 重建角色
            UserRole.query.filter_by(user_id=user.id).delete()
            for rid in role_ids:
                if Role.query.get(rid):
                    db.session.add(UserRole(user_id=user.id, role_id=rid))

            # 重建栏目权限
            UserColumnPermission.query.filter_by(user_id=user.id).delete()
            col_ids = request.form.getlist('column_ids[]')
            col_ids = [int(x) for x in col_ids if x.isdigit()]
            can_review_ids = set(request.form.getlist('can_review_ids[]'))
            can_publish_ids = set(request.form.getlist('can_publish_ids[]'))
            for cid in col_ids:
                db.session.add(UserColumnPermission(
                    user_id=user.id, column_id=cid,
                    can_review=str(cid) in can_review_ids,
                    can_publish=str(cid) in can_publish_ids,
                ))

            db.session.commit()
            flash(_gettext('账号保存成功'), 'success')
            audit_log(OP_UPDATE, MODULE_USER, user.id, user.username,
                      {'nickname': nickname, 'email': email, 'role_ids': role_ids,
                       'is_active': is_active, 'pwd_changed': bool(password)})
            return redirect(url_for('admin.user_index'))

    # 当前分配的角色ID集合
    user_role_ids = {r.role_id for r in UserRole.query.filter_by(user_id=user.id).all()}
    # 当前分配的栏目权限
    col_perms = UserColumnPermission.query.filter_by(user_id=user.id).all()
    user_column_ids = {p.column_id for p in col_perms}
    can_review_map = {p.column_id: p.can_review for p in col_perms}
    can_publish_map = {p.column_id: p.can_publish for p in col_perms}

    return render_template(
        'admin/users/form.html',
        user=user, roles=_get_roles_for_form(),
        columns=_get_all_columns_tree(),
        user_role_ids=user_role_ids,
        user_column_ids=user_column_ids,
        can_review_map=can_review_map,
        can_publish_map=can_publish_map,
    )


@admin_bp.route('/users/<int:uid>/toggle', methods=['POST'])
@permission_required('system:user_manage')
def user_toggle(uid):
    user = User.query.filter_by(id=uid, is_deleted=False).first() or abort(404)
    if user.id == current_user.id:
        flash(_gettext('不能禁用自己的账号'), 'warning')
        return redirect(url_for('admin.user_index'))
    user.is_active_flag = not user.is_active_flag
    db.session.commit()
    msg = '已启用' if user.is_active_flag else '已禁用'
    flash(_gettext('{0}账号：{1}').format(msg, user.username), 'success')
    audit_log(OP_USER_MANAGE, MODULE_USER, user.id, user.username,
              {'action': 'toggle', 'is_active_flag': user.is_active_flag})
    return redirect(url_for('admin.user_index'))


@admin_bp.route('/users/<int:uid>/delete', methods=['POST'])
@permission_required('system:user_manage')
def user_delete(uid):
    user = User.query.filter_by(id=uid, is_deleted=False).first() or abort(404)
    if user.id == current_user.id:
        flash(_gettext('不能删除自己的账号'), 'warning')
        return redirect(url_for('admin.user_index'))
    if user.is_super and User.query.filter_by(is_super=True, is_deleted=False).count() <= 1:
        flash(_gettext('至少保留一个超级管理员账号'), 'danger')
        return redirect(url_for('admin.user_index'))
    user.is_deleted = True
    user.is_active_flag = False
    db.session.commit()
    flash(_gettext('已删除账号：{0}').format(user.username), 'success')
    audit_log(OP_DELETE, MODULE_USER, user.id, user.username, {})
    return redirect(url_for('admin.user_index'))


@admin_bp.route('/users/<int:uid>/reset-password', methods=['POST'])
@permission_required('system:user_manage')
def user_reset_password(uid):
    """超级管理员重置指定账号密码。"""
    user = User.query.filter_by(id=uid, is_deleted=False).first() or abort(404)
    new_pwd = request.form.get('new_password') or ''
    if len(new_pwd) < 6:
        flash(_gettext('新密码至少 6 位'), 'danger')
        return redirect(url_for('admin.user_edit', uid=uid))
    user.set_password(new_pwd)
    # 重置锁定计数
    user.login_fail_count = 0
    user.locked_until = None
    db.session.commit()
    flash(_gettext('密码重置成功，用户锁定状态已解除'), 'success')
    audit_log(OP_USER_MANAGE, MODULE_USER, user.id, user.username, {'action': 'reset_password'})
    return redirect(url_for('admin.user_edit', uid=uid))


# ============================================================
# 角色管理（预设为主，支持自定义角色权限微调）
# ============================================================

@admin_bp.route('/roles')
@permission_required('system:user_manage')
def role_index():
    roles = Role.query.filter_by(is_deleted=False).order_by(Role.id.asc()).all()
    perms = Permission.query.order_by(Permission.group.asc(), Permission.code.asc()).all()
    # 按 group 分组展示
    groups = {}
    for p in perms:
        groups.setdefault(p.group, []).append(p)
    return render_template('admin/users/roles.html', roles=roles,
                           permission_groups=groups)


@admin_bp.route('/roles/<int:rid>/permissions', methods=['POST'])
@permission_required('system:user_manage')
def role_save_permissions(rid):
    role = Role.query.filter_by(id=rid, is_deleted=False).first() or abort(404)
    if role.code == ROLE_SUPER_ADMIN:
        flash(_gettext('超级管理员角色权限不可修改（由 is_super 字段兜底）'), 'warning')
        return redirect(url_for('admin.role_index'))
    codes = request.form.getlist('permission_codes[]')
    # 只接收存在于 permissions 表的 code
    valid = {p.code for p in Permission.query.all()}
    codes = [c for c in codes if c in valid]
    from ..models.rbac import RolePermission
    RolePermission.ensure_for_role(role.id, codes)
    db.session.commit()
    flash(_gettext('角色「{0}」的权限已保存').format(role.name), 'success')
    audit_log(OP_UPDATE, MODULE_ROLE, role.id, role.name,
              {'permission_codes_count': len(codes)})
    return redirect(url_for('admin.role_index'))


@admin_bp.route('/roles/create', methods=['GET', 'POST'])
@permission_required('system:user_manage')
def role_create():
    if request.method == 'POST':
        code = (request.form.get('code') or '').strip().lower()
        name = (request.form.get('name') or '').strip()
        description = (request.form.get('description') or request.form.get('remark') or '').strip()
        if not code or not code.replace('_', '').isalnum():
            flash(_gettext('角色代码必填，只能包含字母数字下划线'), 'danger')
        elif not name:
            flash(_gettext('角色名称必填'), 'danger')
        elif Role.query.filter_by(code=code, is_deleted=False).first():
            flash(_gettext('角色代码已存在'), 'danger')
        else:
            role = Role(code=code, name=name, description=description, is_system=False)
            db.session.add(role)
            db.session.commit()
            flash(_gettext('角色「{0}」创建成功').format(name), 'success')
            audit_log(OP_CREATE, MODULE_ROLE, role.id, role.name, {'code': code})
            return redirect(url_for('admin.role_index'))
    from ..models.rbac import Permission as _Perm
    perms = _Perm.query.order_by(_Perm.group.asc(), _Perm.code.asc()).all()
    return render_template('admin/users/role_form.html', role=None,
                           all_permissions=perms, role_permissions=[],
                           group_label_map={})


@admin_bp.route('/roles/<int:rid>/edit', methods=['GET', 'POST'])
@permission_required('system:user_manage')
def role_edit(rid):
    role = Role.query.filter_by(id=rid, is_deleted=False).first() or abort(404)
    if request.method == 'POST':
        if role.is_system:
            flash(_gettext('系统预设角色的代码/名称不可修改（仅可修改备注）'), 'warning')
            remark = (request.form.get('description') or request.form.get('remark') or '').strip()
            role.description = remark
        else:
            code = (request.form.get('code') or '').strip().lower()
            name = (request.form.get('name') or '').strip()
            description = (request.form.get('description') or request.form.get('remark') or '').strip()
            if not code or not code.replace('_', '').isalnum():
                flash(_gettext('角色代码必填，只能包含字母数字下划线'), 'danger')
                return redirect(url_for('admin.role_edit', rid=rid))
            if not name:
                flash(_gettext('角色名称必填'), 'danger')
                return redirect(url_for('admin.role_edit', rid=rid))
            dup = Role.query.filter(Role.code == code, Role.id != role.id,
                                    Role.is_deleted.is_(False)).first()
            if dup:
                flash(_gettext('角色代码已存在'), 'danger')
                return redirect(url_for('admin.role_edit', rid=rid))
            role.code = code
            role.name = name
            role.description = description
        db.session.commit()
        flash(_gettext('角色「{0}」修改成功').format(role.name), 'success')
        audit_log(OP_UPDATE, MODULE_ROLE, role.id, role.name, {})
        return redirect(url_for('admin.role_index'))
    from ..models.rbac import Permission as _Perm
    perms = _Perm.query.order_by(_Perm.group.asc(), _Perm.code.asc()).all()
    return render_template('admin/users/role_form.html', role=role,
                           all_permissions=perms, role_permissions=perms,
                           group_label_map={})


@admin_bp.route('/roles/<int:rid>/delete', methods=['POST'])
@permission_required('system:user_manage')
def role_delete(rid):
    role = Role.query.filter_by(id=rid, is_deleted=False).first() or abort(404)
    if role.is_system:
        flash(_gettext('系统预设角色不可删除'), 'danger')
        return redirect(url_for('admin.role_index'))
    # 检查是否有用户绑定该角色
    bound_count = UserRole.query.filter_by(role_id=role.id).count()
    if bound_count:
        flash(_gettext('该角色有 {0} 个用户绑定，请先移除后再删除').format(bound_count), 'warning')
        return redirect(url_for('admin.role_index'))
    role.is_deleted = True
    db.session.commit()
    flash(_gettext('角色已删除'), 'success')
    audit_log(OP_DELETE, MODULE_ROLE, role.id, role.name, {})
    return redirect(url_for('admin.role_index'))
