"""全量操作审计日志。"""
from datetime import datetime

from ..extensions import db


# 操作类型枚举
OP_LOGIN = 'login'
OP_LOGOUT = 'logout'
OP_CREATE = 'create'
OP_UPDATE = 'update'
OP_DELETE = 'delete'
OP_PUBLISH = 'publish'
OP_ARCHIVE = 'archive'
OP_REVIEW_PASS = 'review_pass'
OP_REVIEW_REJECT = 'review_reject'
OP_BATCH = 'batch'
OP_ROLLBACK = 'rollback'
OP_CONFIG_CHANGE = 'config_change'
OP_USER_MANAGE = 'user_manage'
OP_BACKUP_CREATE = 'backup_create'
OP_BACKUP_RESTORE = 'backup_restore'
OP_EXPORT = 'export'
OP_UPLOAD = 'upload'
OP_OTHER = 'other'

OP_TYPE_CHOICES = [
    (OP_LOGIN, '登录'),
    (OP_LOGOUT, '退出'),
    (OP_CREATE, '新增'),
    (OP_UPDATE, '修改'),
    (OP_DELETE, '删除'),
    (OP_PUBLISH, '发布'),
    (OP_ARCHIVE, '归档'),
    (OP_REVIEW_PASS, '审核通过'),
    (OP_REVIEW_REJECT, '审核驳回'),
    (OP_BATCH, '批量操作'),
    (OP_ROLLBACK, '版本回滚'),
    (OP_CONFIG_CHANGE, '配置变更'),
    (OP_USER_MANAGE, '用户管理'),
    (OP_BACKUP_CREATE, '创建备份'),
    (OP_BACKUP_RESTORE, '恢复备份'),
    (OP_EXPORT, '导出数据'),
    (OP_UPLOAD, '文件上传'),
    (OP_OTHER, '其他'),
]

# 操作对象（模块）分类
MODULE_USER = 'user'
MODULE_ROLE = 'role'
MODULE_COLUMN = 'column'
MODULE_ARTICLE = 'article'
MODULE_FRAGMENT = 'fragment'
MODULE_FRIEND_LINK = 'friend_link'
MODULE_FORM = 'form'
MODULE_FORM_SUBMISSION = 'form_submission'
MODULE_SETTING = 'setting'
MODULE_AUDIT = 'audit'
MODULE_BACKUP = 'backup'
MODULE_UPLOAD = 'upload'
MODULE_OTHER = 'other'


class AuditLog(db.Model):
    """后台关键操作审计日志。"""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)   # 操作人
    username = db.Column(db.String(64), index=True)                            # 冗余存储，便于查
    nickname = db.Column(db.String(64))
    ip = db.Column(db.String(64), index=True)
    user_agent = db.Column(db.String(255))

    op_type = db.Column(db.String(32), nullable=False, index=True)             # 操作类型，见 OP_*
    module = db.Column(db.String(32), nullable=False, index=True)              # 所属模块
    target_id = db.Column(db.String(64))                                        # 操作对象 ID（字符串，兼容多类型）
    target_name = db.Column(db.String(255))                                     # 操作对象名称/摘要
    detail = db.Column(db.Text)                                                 # 操作详情（JSON或纯文本）

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)

    user = db.relationship('User', backref=db.backref('audit_logs', lazy='dynamic'))

    @classmethod
    def record(cls, op_type, module, target_id=None, target_name=None, detail=None,
               user=None, ip=None, user_agent=None):
        """快捷记录一条审计日志。

        user 可取 current_user；ip/user_agent 留空时从 request 填充。
        无请求上下文（定时任务/命令行）时跳过 request/current_user 兜底，
        保证审计写入不会因此静默丢失。
        """
        from flask import has_request_context, request
        from flask_login import current_user as _cu
        try:
            if user is not None:
                u = user
            elif has_request_context():
                u = _cu if _cu.is_authenticated else None
            else:
                u = None
            _ip = ip or (request.remote_addr if has_request_context() else '')
            _ua = user_agent
            if _ua is None and has_request_context() and request.user_agent:
                _ua = request.user_agent.string[:255]
            log = cls(
                user_id=u.id if u else None,
                username=u.username if u else '',
                nickname=u.nickname if u else '',
                ip=_ip or '',
                user_agent=_ua or '',
                op_type=op_type,
                module=module,
                target_id=str(target_id) if target_id is not None else None,
                target_name=(target_name or '')[:255],
                detail=detail,
            )
            db.session.add(log)
            db.session.commit()
        except Exception:
            # 审计日志写入失败不得影响业务
            db.session.rollback()

    @classmethod
    def clean_expired(cls, keep_days=90):
        """清理过期日志，返回清理条数。"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=keep_days)
        q = cls.query.filter(cls.created_at < cutoff)
        cnt = q.count()
        q.delete(synchronize_session=False)
        db.session.commit()
        return cnt
