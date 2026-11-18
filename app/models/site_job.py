"""站点异步任务：记录克隆/备份导入等耗时操作的进度。

任务线程随请求进程执行，进度写入本表而非进程内缓存，因此多 worker
部署时任意进程都能响应轮询请求。
"""
from datetime import datetime

from ..extensions import db

JOB_PENDING = 'pending'
JOB_RUNNING = 'running'
JOB_SUCCESS = 'success'
JOB_FAILED = 'failed'

JOB_STATUSES = (JOB_PENDING, JOB_RUNNING, JOB_SUCCESS, JOB_FAILED)

JOB_CLONE = 'clone'
JOB_BACKUP_IMPORT = 'backup_import'
JOB_BACKUP_EXPORT = 'backup_export'


class SiteJob(db.Model):
    """站点级异步任务。"""
    __tablename__ = 'site_jobs'

    id = db.Column(db.Integer, primary_key=True)
    # 目标站点（克隆任务在创建时可能尚未建站，允许为 0）
    site_id = db.Column(db.Integer, nullable=False, default=0,
                        server_default='0', index=True)
    job_type = db.Column(db.String(32), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default=JOB_PENDING,
                       server_default=JOB_PENDING)
    progress = db.Column(db.Integer, nullable=False, default=0,
                         server_default='0')
    message = db.Column(db.String(255))
    payload_json = db.Column(db.Text)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False,
                           index=True)
    updated_at = db.Column(db.DateTime, default=datetime.now,
                           onupdate=datetime.now, nullable=False)

    __table_args__ = (
        db.Index('ix_site_jobs_site_type_status', 'site_id', 'job_type', 'status'),
    )

    @property
    def is_running(self):
        return self.status in (JOB_PENDING, JOB_RUNNING)

    def __repr__(self):
        return f'<SiteJob {self.id} {self.job_type}:{self.status}>'
