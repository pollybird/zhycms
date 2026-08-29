"""RBAC 权限管理体系模型。

核心设计：
- 四种预设角色：super_admin / content_auditor / content_editor / readonly_viewer
- 权限粒度（code 命名约定 模块:动作）：
    * system:settings        → 系统设置（网站/SEO/上传/安全/伪静态/缓存/通知）
    * system:user_manage     → 用户/角色/权限管理
    * system:backup          → 备份/恢复/运维监控
    * system:audit_log       → 查看/导出/清理操作审计日志
    * column:manage          → 栏目管理（增删改）
    * content_manage:all_columns → 所有栏目下的内容（增删改/审核/发布/归档/移动）
    * form:view              → 表单数据查看/导出
    * form:manage            → 表单配置管理（字段/增删改）
- 栏目专属权限：UserColumnPermission 可把特定栏目绑定给用户，实现精细化隔离。
"""
from datetime import datetime

from ..extensions import db


# ============================================================
# 预设角色常量
# ============================================================

ROLE_SUPER_ADMIN = 'super_admin'        # 超级管理员
ROLE_CONTENT_AUDITOR = 'content_auditor'   # 内容审核员
ROLE_CONTENT_EDITOR = 'content_editor'     # 内容编辑
ROLE_READONLY_VIEWER = 'readonly_viewer'   # 只读查看员

PRESET_ROLES = {
    ROLE_SUPER_ADMIN: {
        'name': '超级管理员',
        'description': '拥有系统全部权限，不可删除',
        'is_system': True,
    },
    ROLE_CONTENT_AUDITOR: {
        'name': '内容审核员',
        'description': '可审核发布内容、管理栏目、查看表单数据与审计日志',
        'is_system': True,
    },
    ROLE_CONTENT_EDITOR: {
        'name': '内容编辑',
        'description': '可编辑草稿、提交审核（需通过栏目专属权限或全局栏目权限限制范围）',
        'is_system': True,
    },
    ROLE_READONLY_VIEWER: {
        'name': '只读查看员',
        'description': '仅可查看后台内容，无任何修改权限',
        'is_system': True,
    },
}

# ============================================================
# 预设权限点（module:action）
# ============================================================

PERMISSION_DEFS = [
    # 系统设置分组
    ('system:settings',        '系统设置',    '网站/SEO/上传/安全/伪静态/缓存/通知等基础配置管理'),
    ('system:user_manage',     '用户管理',    '后台账号与角色权限管理'),
    ('system:backup',          '备份运维',    '数据库备份恢复与系统监控'),
    ('system:audit_log',       '审计日志',    '查看/导出/清理操作审计日志'),
    # 栏目管理
    ('column:manage',          '栏目管理',    '栏目增删改、字段配置、排序启用禁用'),
    # 内容发布
    ('content_manage:all_columns', '全局内容管理', '所有栏目下内容的增删改/审核/发布/归档/移动'),
    # 表单
    ('form:view',              '表单数据查看', '查看/导出表单提交数据'),
    ('form:manage',            '表单配置管理', '表单字段/增删改配置'),
    # 内容工作流中的细分权限（在 content_manage:all_columns 或栏目专属权限授予的前提下生效）
    ('content:create',         '内容创建',    '创建草稿（编辑角色通常需要）'),
    ('content:edit',           '内容编辑',    '编辑已有内容'),
    ('content:delete',         '内容删除',    '删除内容'),
    ('content:submit_review',  '提交审核',    '把草稿提交为待审核'),
    ('content:review',         '内容审核',    '审核通过/驳回（审核员角色）'),
    ('content:publish',        '内容发布',    '直接发布或审核通过后上线'),
    ('content:archive',        '内容归档',    '归档内容'),
    ('content:batch',          '批量操作',    '批量移动/发布/归档/删除'),
    ('content:rollback',       '版本回滚',    '查看历史版本并回滚'),
]

# 四种预设角色的默认权限（超级管理员所有权限在运行时由 is_super 兜底，不必写全）
PRESET_ROLE_PERMISSIONS = {
    ROLE_SUPER_ADMIN: [p[0] for p in PERMISSION_DEFS],
    ROLE_CONTENT_AUDITOR: [
        'system:audit_log',
        'column:manage',
        'content_manage:all_columns',
        'content:create', 'content:edit', 'content:delete',
        'content:submit_review', 'content:review',
        'content:publish', 'content:archive', 'content:batch',
        'content:rollback',
        'form:view',
    ],
    ROLE_CONTENT_EDITOR: [
        'content:create', 'content:edit',
        'content:submit_review',
        # 编辑默认不给全栏目权限，需通过 UserColumnPermission 绑定具体栏目；
        # 如需全局编辑权限，可额外授予 content_manage:all_columns
    ],
    ROLE_READONLY_VIEWER: [
        'form:view',
        'system:audit_log',  # 只读可看审计日志列表（但无清理/导出权限）
    ],
}


# ============================================================
# ORM 模型
# ============================================================

class Role(db.Model):
    """角色表。"""
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, nullable=False, index=True)  # 英文标识，如 super_admin
    name = db.Column(db.String(64), nullable=False)                           # 显示名称
    description = db.Column(db.String(255))
    is_system = db.Column(db.Boolean, default=False, nullable=False)          # 系统预设角色不可删除
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    permission_assignments = db.relationship(
        'RolePermission', backref='role', cascade='all, delete-orphan', lazy='joined'
    )

    @property
    def permission_codes(self):
        return {p.permission_code for p in self.permission_assignments}

    @classmethod
    def ensure_presets(cls):
        """幂等写入四种预设角色与权限。"""
        for code, info in PRESET_ROLES.items():
            role = cls.query.filter_by(code=code).first()
            if role is None:
                role = cls(code=code, name=info['name'],
                           description=info['description'],
                           is_system=info['is_system'])
                db.session.add(role)
                db.session.flush()
            # 更新显示名称（避免旧数据名称不对）
            role.name = info['name']
            role.description = info['description']
            role.is_system = True

            # 分配预设权限（对系统角色）
            RolePermission.ensure_for_role(role.id, PRESET_ROLE_PERMISSIONS.get(code, []))

    @classmethod
    def get_by_code(cls, code):
        return cls.query.filter_by(code=code, is_deleted=False).first()


class Permission(db.Model):
    """权限点定义表（code 即权限标识）。"""
    __tablename__ = 'permissions'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(128), unique=True, nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255))
    group = db.Column(db.String(64))  # 用于后台分组展示（如 system / column / content / form）
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    @classmethod
    def ensure_presets(cls):
        """幂等写入所有权限点。"""
        for code, name, desc in PERMISSION_DEFS:
            item = cls.query.filter_by(code=code).first()
            group = code.split(':', 1)[0] if ':' in code else ''
            if item is None:
                item = cls(code=code, name=name, description=desc, group=group)
                db.session.add(item)
            else:
                item.name = name
                item.description = desc
                item.group = group


class RolePermission(db.Model):
    """角色-权限 多对多 关联。"""
    __tablename__ = 'role_permissions'

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False, index=True)
    permission_code = db.Column(db.String(128), db.ForeignKey('permissions.code'),
                                nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('role_id', 'permission_code', name='uq_role_permission'),
    )

    permission = db.relationship('Permission', backref=db.backref('role_links', lazy='dynamic'))

    @classmethod
    def ensure_for_role(cls, role_id, codes):
        """用事务保证「先清空后重建」的幂等一致性。"""
        existing = {rp.permission_code for rp in cls.query.filter_by(role_id=role_id).all()}
        target = set(codes)
        for code in target - existing:
            db.session.add(cls(role_id=role_id, permission_code=code))
        for code in existing - target:
            rp = cls.query.filter_by(role_id=role_id, permission_code=code).first()
            if rp:
                db.session.delete(rp)


class UserRole(db.Model):
    """用户-角色 多对多 关联。"""
    __tablename__ = 'user_roles'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'role_id', name='uq_user_role'),
    )

    role = db.relationship('Role')


class UserColumnPermission(db.Model):
    """用户-栏目专属权限：限制用户只能操作指定栏目下的内容。"""
    __tablename__ = 'user_column_permissions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    column_id = db.Column(db.Integer, db.ForeignKey('columns.id'), nullable=False, index=True)
    # 细粒度：是否允许在本栏目下审核/发布，编辑默认只允许草稿提交
    can_review = db.Column(db.Boolean, default=False, nullable=False)
    can_publish = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'column_id', name='uq_user_column'),
    )

    column = db.relationship('Column')
