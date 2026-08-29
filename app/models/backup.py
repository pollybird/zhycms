"""数据库备份记录与运维模型。"""
import os
from datetime import datetime

from ..extensions import db


# 备份触发方式
TRIGGER_MANUAL = 'manual'     # 手动
TRIGGER_SCHEDULED = 'scheduled'   # 定时自动

TRIGGER_CHOICES = [
    (TRIGGER_MANUAL, '手动备份'),
    (TRIGGER_SCHEDULED, '定时自动'),
]

# 备份类型（默认 SQLite dump；其他数据库类型 dump 对应）
BAK_FULL = 'full'


class BackupRecord(db.Model):
    """备份记录：记录每次备份的元信息，实际文件存放于 instance/backups/。"""
    __tablename__ = 'backup_records'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False, index=True)     # 文件名（不含路径）
    file_size = db.Column(db.Integer, default=0)                         # 字节数
    trigger = db.Column(db.String(16), default=TRIGGER_MANUAL, nullable=False)
    backup_type = db.Column(db.String(16), default=BAK_FULL, nullable=False)
    db_type = db.Column(db.String(16))                                    # sqlite/mysql/postgresql
    remark = db.Column(db.String(255))
    status = db.Column(db.String(16), default='ok')                       # ok/failed
    error_msg = db.Column(db.Text)

    # 操作人
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
    expired_at = db.Column(db.DateTime)                                   # 过期自动清理时间

    creator = db.relationship('User', backref=db.backref('backups', lazy='dynamic'))

    @property
    def abs_path(self):
        from ..config import BASE_DIR
        return os.path.join(BASE_DIR, 'instance', 'backups', self.filename)

    @classmethod
    def cleanup_expired(cls):
        """删除过期备份记录及对应文件，返回 (records_deleted, files_deleted, error_files)。"""
        expired = cls.query.filter(cls.expired_at.isnot(None), cls.expired_at < datetime.now()).all()
        records_deleted = 0
        files_deleted = 0
        error_files = []
        for r in expired:
            path = r.abs_path
            try:
                if os.path.exists(path):
                    os.remove(path)
                    files_deleted += 1
            except OSError as e:
                error_files.append(f'{r.filename}: {e}')
            db.session.delete(r)
            records_deleted += 1
        db.session.commit()
        return records_deleted, files_deleted, error_files
