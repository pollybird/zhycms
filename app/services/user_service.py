"""用户与 RBAC 业务逻辑（service 层）。

从 app/admin/system/users.py 的 user_create / user_edit 内联逻辑抽离而来。
"""
from flask_babel import gettext as _gettext

from ..extensions import db
from ..models.user import User
from ..models.rbac import Role, UserRole, UserColumnPermission
from ..utils.helpers import audit_log
from ..models.audit import OP_CREATE, OP_UPDATE, MODULE_USER


def create_user(*, form_data):
    """创建后台账号。

    :param form_data: 表单数据（request.form）
    :returns: (user_or_None, messages)
    """
    messages = []

    def _flash(msg, category='info'):
        messages.append((category, msg))

    username = (form_data.get('username') or '').strip().lower()
    nickname = (form_data.get('nickname') or '').strip()
    email = (form_data.get('email') or '').strip()
    password = form_data.get('password') or ''
    confirm = form_data.get('confirm_password') or ''
    role_ids = form_data.getlist('role_ids[]')
    is_active = form_data.get('is_active_flag') == 'on'
    is_super = form_data.get('is_super') == 'on'

    if not username or len(username) < 3:
        _flash(_gettext('用户名至少 3 位'), 'danger')
        return None, messages
    if User.query.filter_by(username=username, is_deleted=False).first():
        _flash(_gettext('用户名已存在'), 'danger')
        return None, messages
    if len(password) < 6:
        _flash(_gettext('密码至少 6 位'), 'danger')
        return None, messages
    if password != confirm:
        _flash(_gettext('两次输入的密码不一致'), 'danger')
        return None, messages

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
    col_ids = form_data.getlist('column_ids[]')
    col_ids = [int(x) for x in col_ids if x.isdigit()]
    can_review_ids = set(form_data.getlist('can_review_ids[]'))
    can_publish_ids = set(form_data.getlist('can_publish_ids[]'))
    for cid in col_ids:
        db.session.add(UserColumnPermission(
            user_id=user.id, column_id=cid,
            can_review=str(cid) in can_review_ids,
            can_publish=str(cid) in can_publish_ids,
        ))

    db.session.commit()
    _flash(_gettext('账号创建成功'), 'success')
    audit_log(OP_CREATE, MODULE_USER, user.id, user.username,
              {'nickname': nickname, 'email': email, 'role_ids': role_ids})
    return user, messages


def update_user(user, *, form_data):
    """更新后台账号。

    :param user: 待更新的 User 实例
    :param form_data: 表单数据（request.form）
    :returns: (user_or_None, messages)
    """
    messages = []

    def _flash(msg, category='info'):
        messages.append((category, msg))

    nickname = (form_data.get('nickname') or '').strip()
    email = (form_data.get('email') or '').strip()
    password = form_data.get('password') or ''
    confirm = form_data.get('confirm_password') or ''
    role_ids = form_data.getlist('role_ids[]')
    is_active = form_data.get('is_active_flag') == 'on'
    is_super = form_data.get('is_super') == 'on'

    if password and len(password) < 6:
        _flash(_gettext('密码至少 6 位'), 'danger')
        return None, messages
    if password and password != confirm:
        _flash(_gettext('两次输入的密码不一致'), 'danger')
        return None, messages

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
    col_ids = form_data.getlist('column_ids[]')
    col_ids = [int(x) for x in col_ids if x.isdigit()]
    can_review_ids = set(form_data.getlist('can_review_ids[]'))
    can_publish_ids = set(form_data.getlist('can_publish_ids[]'))
    for cid in col_ids:
        db.session.add(UserColumnPermission(
            user_id=user.id, column_id=cid,
            can_review=str(cid) in can_review_ids,
            can_publish=str(cid) in can_publish_ids,
        ))

    db.session.commit()
    _flash(_gettext('账号保存成功'), 'success')
    audit_log(OP_UPDATE, MODULE_USER, user.id, user.username,
              {'nickname': nickname, 'email': email, 'role_ids': role_ids,
               'is_active': is_active, 'pwd_changed': bool(password)})
    return user, messages
