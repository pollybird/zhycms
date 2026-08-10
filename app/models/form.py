import json
from datetime import datetime

from ..extensions import db


class Form(db.Model):
    """自定义表单配置。"""
    __tablename__ = 'forms'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    success_message = db.Column(db.String(255), default='提交成功，感谢您的反馈！')
    is_open = db.Column(db.Boolean, default=True, nullable=False)
    # 防重复提交：间隔秒数；0 表示不限制
    submit_interval = db.Column(db.Integer, default=60, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    fields = db.relationship(
        'FormField', backref='form', lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='FormField.sort_order.desc()'
    )
    submissions = db.relationship(
        'FormSubmission', backref='form', lazy='dynamic',
        cascade='all, delete-orphan'
    )


class FormField(db.Model):
    """表单字段。

    field_type:
      text/textarea/phone/email/select/checkbox/radio/file
    options: JSON 字符串，用于 select/checkbox/radio 选项
    """
    __tablename__ = 'form_fields'

    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('forms.id'), nullable=False, index=True)
    label = db.Column(db.String(100), nullable=False)
    field_key = db.Column(db.String(100), nullable=False)
    field_type = db.Column(db.String(32), nullable=False)
    is_required = db.Column(db.Boolean, default=False, nullable=False)
    placeholder = db.Column(db.String(255))
    help_text = db.Column(db.String(255))
    options = db.Column(db.Text)  # JSON
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    # 文件上传字段额外配置
    allowed_exts = db.Column(db.String(255))
    max_size = db.Column(db.Integer)

    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __table_args__ = (db.UniqueConstraint('form_id', 'field_key', name='uq_form_field_key'),)

    def get_options(self):
        if not self.options:
            return []
        try:
            return json.loads(self.options)
        except (TypeError, ValueError):
            return []


class FormSubmission(db.Model):
    """表单提交记录。"""
    __tablename__ = 'form_submissions'

    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('forms.id'), nullable=False, index=True)
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)

    values = db.relationship(
        'FormSubmissionValue', backref='submission',
        cascade='all, delete-orphan', lazy='joined'
    )

    def get_value(self, field_id):
        for v in self.values:
            if v.field_id == field_id:
                return v.value
        return ''


class FormSubmissionValue(db.Model):
    __tablename__ = 'form_submission_values'

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('form_submissions.id'), nullable=False, index=True)
    field_id = db.Column(db.Integer, db.ForeignKey('form_fields.id'), nullable=False)
    value = db.Column(db.Text)

    field = db.relationship('FormField')
