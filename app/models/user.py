from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

from ..extensions import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    nickname = db.Column(db.String(64))
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(128))
    last_login_at = db.Column(db.DateTime)
    last_login_ip = db.Column(db.String(64))
    is_super = db.Column(db.Boolean, default=False, nullable=False)  # 兼容旧逻辑，新RBAC下超级管理员角色也用这个标记兜底
    is_active_flag = db.Column(db.Boolean, default=True, nullable=False)  # 启用/禁用账号
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    # 登录安全加固（模块5）
    login_fail_count = db.Column(db.Integer, default=0, nullable=False)  # 连续失败次数
    locked_until = db.Column(db.DateTime)  # 锁定截止时间
    last_login_city = db.Column(db.String(64))  # 上次登录城市（用于异地提醒）

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # 关联：角色分配（多对多）
    role_assignments = db.relationship(
        'UserRole', backref='user', cascade='all, delete-orphan', lazy='joined'
    )
    # 关联：栏目专属权限
    column_permissions = db.relationship(
        'UserColumnPermission', backref='user', cascade='all, delete-orphan', lazy='dynamic'
    )

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    # ========== 登录安全 ==========
    @property
    def is_locked(self):
        """账号是否被锁定（失败次数过多）。"""
        if self.locked_until and self.locked_until > datetime.now():
            return True
        # 超时自动重置失败计数与锁定状态
        if self.locked_until and self.locked_until <= datetime.now():
            self.locked_until = None
            self.login_fail_count = 0
        return False

    def record_login_fail(self, max_fail=5, lock_minutes=10):
        """记录一次登录失败，达到上限则锁定。"""
        self.login_fail_count = (self.login_fail_count or 0) + 1
        if self.login_fail_count >= max_fail:
            self.locked_until = datetime.now() + timedelta(minutes=lock_minutes)

    def reset_login_fail(self):
        """登录成功：重置失败计数。"""
        self.login_fail_count = 0
        self.locked_until = None

    # ========== RBAC 权限快捷方法 ==========
    @property
    def role_ids(self):
        return {r.role_id for r in self.role_assignments}

    @property
    def roles(self):
        """返回 User 对象当前绑定的 Role 实例列表（模板/业务便捷访问）。"""
        from .rbac import Role
        if not self.role_ids:
            return []
        return Role.query.filter(Role.id.in_(self.role_ids)).all()

    def has_any_permission(self, *perm_codes):
        """判断用户是否具备任一权限点（菜单/入口可见性判断用；超级管理员永远为真）。"""
        return any(self.has_permission(c) for c in perm_codes)

    def has_permission(self, perm_code):
        """判断用户是否具备指定权限（超级管理员 is_super=True 永远全放行）。"""
        from ..models.rbac import Role, RolePermission, Permission
        if self.is_super:
            return True
        if not self.role_ids:
            # 未绑定任何角色的普通用户 = 无任何权限（只读查看员也必须显式绑定角色）
            return False
        codes = {p.code for p in Permission.query.join(RolePermission).filter(
            RolePermission.role_id.in_(list(self.role_ids))
        ).all()}
        return perm_code in codes

    def get_allowed_column_ids(self):
        """获取用户有操作权限的栏目 ID 集合；None 表示不限制（管理员/全局权限）。"""
        if self.is_super:
            return None
        # 如果用户有「全栏目」的 content_manage:all 权限，则返回 None
        if self.has_permission('content_manage:all_columns'):
            return None
        # 否则返回被明确分配的栏目 ID
        return {cp.column_id for cp in self.column_permissions.all()}

    def can_access_column(self, column_id):
        """判断用户是否可操作/查看指定栏目。"""
        ids = self.get_allowed_column_ids()
        if ids is None:
            return True
        return column_id in ids

    def column_flag(self, flag, column_id):
        """栏目级操作标志（'can_review' / 'can_publish'）。

        优先级：超管 > 用户级显式授权行（UserColumnPermission，存在即按其
        标志判定，可覆盖角色默认）> 角色全局权限（content_manage:all_columns
        兜底，无行时全栏目放行）。
        """
        if self.is_super:
            return True
        from ..models.rbac import UserColumnPermission
        row = UserColumnPermission.query.filter_by(
            user_id=self.id, column_id=column_id).first()
        if row is not None:
            return bool(getattr(row, flag, False))
        return self.has_permission('content_manage:all_columns')


class LoginLog(db.Model):
    __tablename__ = 'login_logs'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)  # 登录成功时关联用户
    ip = db.Column(db.String(64))
    city = db.Column(db.String(64))  # IP 归属地（用于异地提醒）
    user_agent = db.Column(db.String(255))
    result = db.Column(db.String(16), nullable=False)  # success / failed / locked
    message = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)

    user = db.relationship('User', backref=db.backref('login_logs', lazy='dynamic'))
