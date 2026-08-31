"""招聘插件：数据模型。

RecruitJob    招聘岗位（标题/部门/地点/人数/薪资/岗位介绍/招聘截止时间）
RecruitApplication  求职申请（基本信息 + 简历文件 + 处理状态）

截止时间语义：deadline 为空 = 长期有效；超过 deadline 前台不可再提交申请。
"""
from datetime import datetime

from app.extensions import db


class RecruitJob(db.Model):
    """招聘岗位。"""
    __tablename__ = 'recruit_jobs'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    department = db.Column(db.String(100))            # 所属部门（可选）
    location = db.Column(db.String(200))              # 工作地点（可选）
    headcount = db.Column(db.Integer, default=1)      # 招聘人数（可选）
    salary = db.Column(db.String(100))                # 薪资待遇（可选）
    description = db.Column(db.Text)                  # 岗位介绍（富文本）
    deadline = db.Column(db.DateTime, index=True)     # 招聘截止时间（空=长期有效）
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now,
                           onupdate=datetime.now, nullable=False)

    # ---- 截止状态 ----

    def is_expired(self):
        """是否已过招聘截止时间（未设截止时间视为长期有效）。"""
        if self.deadline is None:
            return False
        return datetime.now() > self.deadline

    def is_open(self):
        """是否开放申请：启用 + 未删除 + 未截止。"""
        return self.is_enabled and not self.is_deleted and not self.is_expired()

    def applications_count(self):
        return RecruitApplication.query.filter_by(job_id=self.id).count()


class RecruitApplication(db.Model):
    """求职申请。"""
    __tablename__ = 'recruit_applications'

    STATUS_PENDING = 'pending'    # 未处理
    STATUS_VIEWED = 'viewed'      # 已查看
    STATUS_PASS = 'pass'          # 录用
    STATUS_REJECT = 'reject'      # 不合适
    STATUS_LABELS = {
        STATUS_PENDING: '未处理', STATUS_VIEWED: '已查看',
        STATUS_PASS: '录用', STATUS_REJECT: '不合适',
    }

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('recruit_jobs.id'),
                       nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)     # 姓名
    phone = db.Column(db.String(32), nullable=False)    # 联系电话
    email = db.Column(db.String(128))                   # 邮箱（可选）
    education = db.Column(db.String(64))                # 学历（可选）
    intro = db.Column(db.Text)                          # 自我介绍（可选）
    resume_file = db.Column(db.String(500))             # 简历存储相对路径（uploads/...）
    resume_name = db.Column(db.String(255))             # 简历原始文件名
    ip = db.Column(db.String(64))
    status = db.Column(db.String(16), default=STATUS_PENDING, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now,
                           nullable=False, index=True)

    job = db.relationship('RecruitJob', backref=db.backref(
        'applications', lazy='dynamic'))

    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)
