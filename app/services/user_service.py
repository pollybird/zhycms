"""用户与 RBAC 业务逻辑（service 层）。

从 app/admin/system/users.py 的 user_create / user_edit 内联逻辑抽离而来。
v3.2.3：角色分配支持站点维度（user_roles.site_id），并收敛站点管理员的操作边界。
"""
from flask_login import current_user
from flask_babel import gettext as _gettext
from sqlalchemy.exc import IntegrityError

from ..constants import Roles as ROLE_CODES
from ..extensions import db
from ..models.user import User
from ..models.rbac import Role, UserRole, UserColumnPermission, UserSitePermission
from ..utils.helpers import audit_log
from ..models.audit import OP_CREATE, OP_UPDATE, MODULE_USER


# ============================================================
# 操作者范围（v3.2.3）
# ============================================================

def is_platform_admin(user=None):
    """是否为平台级管理员：超级管理员或拥有 site:manage（站点管理）权限。"""
    u = user or current_user
    if not getattr(u, 'is_authenticated', False):
        return False
    return bool(getattr(u, 'is_super', False) or u.has_permission('site:manage'))


def managed_site_ids(user=None):
    """操作者可管理的站点 id 集合。

    平台管理员 → 全部启用站点；其余（站点管理员）→ 自己可访问的站点。
    """
    from ..models.site import Site
    from ..sites import accessible_sites
    u = user or current_user
    if is_platform_admin(u):
        return {s.id for s in Site.active_sites()}
    return {s.id for s in accessible_sites(u)}


def assignable_site_roles():
    """站点内可分配的角色（站点管理员/审核员/编辑/只读查看员）。"""
    return (Role.query
            .filter(Role.is_deleted.is_(False),
                    Role.code.in_(ROLE_CODES.SITE_ASSIGNABLE))
            .order_by(Role.id.asc()).all())


def user_in_scope(target, user=None):
    """目标账号是否完全处于操作者的管理范围内。

    平台管理员可管理全部账号；站点管理员仅能管理「角色全部落在自己管理的
    站点内、且没有全局角色」的账号，避免连带影响其他站点的授权。
    """
    u = user or current_user
    # 超级管理员账号只能由超级管理员本人（is_super）管理，防止 site:manage 账号越权改密
    if getattr(target, 'is_super', False) and not getattr(u, 'is_super', False):
        return False
    if is_platform_admin(u):
        return True
    if target is None:
        return False
    managed = managed_site_ids(u)
    assignments = list(target.role_assignments or [])
    if any(a.site_id is None for a in assignments):
        return False
    role_sites = {a.site_id for a in assignments if a.site_id is not None}
    if role_sites:
        return role_sites <= managed
    # 兼容 v3.2.0 只勾选站点权限、未绑定角色的存量账号
    perm_sites = {p.site_id for p in UserSitePermission.query.filter_by(
        user_id=target.id).all()}
    return bool(perm_sites) and perm_sites <= managed


# ============================================================
# 表单解析 / 分配
# ============================================================

def _site_role_selections(form_data, managed_ids, allowed_role_ids):
    """读取 `site_role_<站点id>` 下拉，返回 {site_id: role_id}（仅管理范围内）。"""
    result = {}
    for key in form_data.keys():
        if not key.startswith('site_role_'):
            continue
        sid_part = key[len('site_role_'):]
        if not sid_part.isdigit():
            continue
        sid = int(sid_part)
        if sid not in managed_ids:
            continue
        raw = (form_data.get(key) or '').strip()
        if raw.isdigit() and int(raw) in allowed_role_ids:
            result[sid] = int(raw)
    return result


def _apply_global_roles(user, role_ids):
    """重建账号的全局角色（site_id IS NULL）。"""
    UserRole.query.filter_by(user_id=user.id, site_id=None).delete(
        synchronize_session=False)
    for rid in role_ids:
        if Role.query.get(rid):
            db.session.add(UserRole(user_id=user.id, role_id=rid))


def _apply_site_roles(user, *, managed_ids, role_map):
    """重建账号在管理范围内站点的角色，范围外的站点授权保持不动。"""
    if managed_ids:
        UserRole.query.filter(
            UserRole.user_id == user.id,
            UserRole.site_id.in_(list(managed_ids)),
        ).delete(synchronize_session=False)
    for sid, rid in role_map.items():
        db.session.add(UserRole(user_id=user.id, role_id=rid, site_id=sid))


def _apply_site_permissions(user, form_data, managed_ids):
    """v3.2.0 站群：按表单重建账号的站点专属权限（每站可审核/可发布）。"""
    if managed_ids:
        UserSitePermission.query.filter(
            UserSitePermission.user_id == user.id,
            UserSitePermission.site_id.in_(list(managed_ids)),
        ).delete(synchronize_session=False)
    site_ids = [int(x) for x in form_data.getlist('site_ids[]') if x.isdigit()]
    can_review_ids = set(form_data.getlist('site_can_review_ids[]'))
    can_publish_ids = set(form_data.getlist('site_can_publish_ids[]'))
    for sid in site_ids:
        if sid not in managed_ids:
            continue
        db.session.add(UserSitePermission(
            user_id=user.id, site_id=sid,
            can_review=str(sid) in can_review_ids,
            can_publish=str(sid) in can_publish_ids,
        ))


def _requested_super(form_data):
    """表单是否勾选了超管标志；非超管操作者一律视为 False（防提权）。"""
    if form_data.get('is_super') != 'on':
        return False
    return bool(current_user.is_super)


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
    is_super = _requested_super(form_data)

    if not username or len(username) < 3:
        _flash(_gettext('用户名至少 3 位'), 'danger')
        return None, messages
    if User.query.filter_by(username=username, is_deleted=False).first():
        _flash(_gettext('用户名已存在'), 'danger')
        return None, messages
    # v3.1.10 VULN-015：后台新密码策略（12 位 + 四类字符）
    from ..utils.password_policy import validate_password
    ok, msg = validate_password(password)
    if not ok:
        _flash(msg, 'danger')
        return None, messages
    if password != confirm:
        _flash(_gettext('两次输入的密码不一致'), 'danger')
        return None, messages

    try:
        role_ids = [int(x) for x in role_ids if x.isdigit()]
    except ValueError:
        role_ids = []

    # v3.2.3：站点管理员只能按站点授权；全局角色仅平台管理员可分配
    platform_admin = is_platform_admin()
    managed_ids = managed_site_ids()
    allowed_site_role_ids = {r.id for r in assignable_site_roles()}
    site_role_map = _site_role_selections(
        form_data, managed_ids, allowed_site_role_ids)
    global_role_ids = role_ids if platform_admin else []

    user = User(username=username, nickname=nickname or username,
                email=email, is_active_flag=is_active, is_super=is_super)
    user.set_password(password)
    db.session.add(user)
    # v3.1.3 M10（GitCode issue #3）：先查重后插入存在并发竞态，users.username
    # 唯一索引兜底时 flush/commit 会抛 IntegrityError —— 捕获后回退业务错误而非 500
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        _flash(_gettext('用户名已存在'), 'danger')
        return None, messages

    # 全局角色 + 站点级角色
    _apply_global_roles(user, global_role_ids)
    _apply_site_roles(user, managed_ids=managed_ids, role_map=site_role_map)

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

    # 站点专属权限（v3.2.0 站群）
    _apply_site_permissions(user, form_data, managed_ids)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        _flash(_gettext('用户名已存在'), 'danger')
        return None, messages
    _flash(_gettext('账号创建成功'), 'success')
    audit_log(OP_CREATE, MODULE_USER, user.id, user.username,
              {'nickname': nickname, 'email': email,
               'role_ids': global_role_ids,
               'site_roles': {str(k): v for k, v in site_role_map.items()}})
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
    is_super = _requested_super(form_data)

    # v3.2.3：越权保护（路由层已校验，service 层再做一次兜底）
    if not user_in_scope(user):
        _flash(_gettext('无权管理该账号'), 'danger')
        return None, messages

    # v3.1.10 VULN-015：后台新密码策略（12 位 + 四类字符），留空表示不改密
    if password:
        from ..utils.password_policy import validate_password
        ok, msg = validate_password(password)
        if not ok:
            _flash(msg, 'danger')
            return None, messages
    if password and password != confirm:
        _flash(_gettext('两次输入的密码不一致'), 'danger')
        return None, messages

    try:
        role_ids = [int(x) for x in role_ids if x.isdigit()]
    except ValueError:
        role_ids = []

    platform_admin = is_platform_admin()
    managed_ids = managed_site_ids()
    allowed_site_role_ids = {r.id for r in assignable_site_roles()}
    site_role_map = _site_role_selections(
        form_data, managed_ids, allowed_site_role_ids)

    user.nickname = nickname or user.username
    user.email = email
    user.is_active_flag = is_active
    # 系统第一个超级管理员 is_super 不可被取消（兜底）
    if not (user.is_super and User.query.filter_by(is_super=True, is_deleted=False).count() <= 1):
        user.is_super = is_super
    if password:
        user.set_password(password)

    # 重建角色：平台管理员可改全局角色；站点管理员保留自己看不到的全局授权
    if platform_admin:
        _apply_global_roles(user, role_ids)
    _apply_site_roles(user, managed_ids=managed_ids, role_map=site_role_map)

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

    # 站点专属权限（v3.2.0 站群）
    _apply_site_permissions(user, form_data, managed_ids)

    db.session.commit()
    _flash(_gettext('账号保存成功'), 'success')
    audit_log(OP_UPDATE, MODULE_USER, user.id, user.username,
              {'nickname': nickname, 'email': email,
               'role_ids': role_ids if platform_admin else None,
               'site_roles': {str(k): v for k, v in site_role_map.items()},
               'is_active': is_active, 'pwd_changed': bool(password)})
    return user, messages
