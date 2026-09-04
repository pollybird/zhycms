from .user import User, LoginLog
from .column import Column, ColumnField, ColumnFieldValue
from .article import Article, ArticleFieldValue
from .fragment import Fragment, FragmentGroup
# 自定义表单 v2.3.0 起转为内置插件 plugins/form，模型由插件注册
from .setting import Setting
from .rbac import (
    Role, Permission, RolePermission, UserRole, UserColumnPermission,
    PRESET_ROLES, PERMISSION_DEFS,
    ROLE_SUPER_ADMIN, ROLE_CONTENT_AUDITOR, ROLE_CONTENT_EDITOR, ROLE_READONLY_VIEWER,
)
from .audit import (
    AuditLog, OP_TYPE_CHOICES, MODULE_USER, MODULE_ROLE, MODULE_COLUMN, MODULE_ARTICLE,
    MODULE_FRAGMENT, MODULE_FORM, MODULE_FORM_SUBMISSION, MODULE_SETTING,
    MODULE_AUDIT, MODULE_BACKUP, MODULE_UPLOAD, MODULE_OTHER,
    OP_LOGIN, OP_LOGOUT, OP_CREATE, OP_UPDATE, OP_DELETE, OP_PUBLISH, OP_ARCHIVE,
    OP_REVIEW_PASS, OP_REVIEW_REJECT, OP_BATCH, OP_ROLLBACK, OP_CONFIG_CHANGE,
    OP_USER_MANAGE, OP_BACKUP_CREATE, OP_BACKUP_RESTORE, OP_EXPORT, OP_UPLOAD, OP_OTHER,
)
from .workflow import (
    STATUS_DRAFT, STATUS_REVIEW, STATUS_PUBLISHED, STATUS_ARCHIVED,
    STATUS_CHOICES, ArticleVersion,
)
from .backup import BackupRecord, TRIGGER_MANUAL, TRIGGER_SCHEDULED
from .upload import UploadedFile

# v2.4.0: search_index 表由迁移 0002 创建；为避免 Alembic 下一次 autogenerate
# 把它误报为 DROP，需要有一个对应的 ORM 模型声明在 db.metadata 中「锚定」。
# 模型层故意不使用它，避免和业务耦合。
from app.extensions import db as _db
if 'search_index' not in _db.metadata.tables:
    class SearchIndex(_db.Model):
        __tablename__ = 'search_index'
        __table_args__ = {'extend_existing': True}
        article_id = _db.Column(_db.Integer, primary_key=True, nullable=False)
        indexed_at = _db.Column(
            _db.DateTime, nullable=False,
            server_default=_db.text('CURRENT_TIMESTAMP'),
        )
        content_hash = _db.Column(_db.String(64), nullable=True)
        _db.Index('ix_search_index_indexed_at', indexed_at)
    del SearchIndex

__all__ = [
    'User', 'LoginLog',
    'Column', 'ColumnField', 'ColumnFieldValue',
    'Article', 'ArticleFieldValue',
    'Fragment', 'FragmentGroup',
    'Setting',
    # RBAC
    'Role', 'Permission', 'RolePermission', 'UserRole', 'UserColumnPermission',
    'PRESET_ROLES', 'PERMISSION_DEFS',
    'ROLE_SUPER_ADMIN', 'ROLE_CONTENT_AUDITOR', 'ROLE_CONTENT_EDITOR', 'ROLE_READONLY_VIEWER',
    # Audit
    'AuditLog', 'OP_TYPE_CHOICES',
    'MODULE_USER', 'MODULE_ROLE', 'MODULE_COLUMN', 'MODULE_ARTICLE',
    'MODULE_FRAGMENT', 'MODULE_FORM', 'MODULE_FORM_SUBMISSION',
    'MODULE_SETTING', 'MODULE_AUDIT', 'MODULE_BACKUP', 'MODULE_UPLOAD', 'MODULE_OTHER',
    'OP_LOGIN', 'OP_LOGOUT', 'OP_CREATE', 'OP_UPDATE', 'OP_DELETE',
    'OP_PUBLISH', 'OP_ARCHIVE', 'OP_REVIEW_PASS', 'OP_REVIEW_REJECT',
    'OP_BATCH', 'OP_ROLLBACK', 'OP_CONFIG_CHANGE', 'OP_USER_MANAGE',
    'OP_BACKUP_CREATE', 'OP_BACKUP_RESTORE', 'OP_EXPORT', 'OP_UPLOAD', 'OP_OTHER',
    # Workflow
    'STATUS_DRAFT', 'STATUS_REVIEW', 'STATUS_PUBLISHED', 'STATUS_ARCHIVED',
    'STATUS_CHOICES', 'ArticleVersion',
    # Backup
    'BackupRecord', 'TRIGGER_MANUAL', 'TRIGGER_SCHEDULED',
    # Upload
    'UploadedFile',
]
