"""Webhook 事件订阅模型（v3.2.12）。

两张表：
  - webhook_subscriptions：订阅（接收地址 + 加密密钥 + 事件类型），按站点隔离；
  - webhook_events：逐订阅的投递记录（一行 = 一次事件对一个订阅的投递），
    带状态机、重试时间与幂等标识 replay_id。
"""
import secrets
from datetime import datetime

from ..extensions import db
from ..utils.crypto import decrypt_value, encrypt_value


class WebhookSubscription(db.Model):
    __tablename__ = 'webhook_subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, nullable=False, default=0, index=True)
    url = db.Column(db.String(500), nullable=False)
    # 签名密钥 Fernet 加密存储，数据库不落明文
    secret_enc = db.Column(db.Text, nullable=False, default='')
    # 逗号分隔事件类型，如 article.published,form.submitted
    events = db.Column(db.Text, nullable=False, default='')
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now,
                           onupdate=datetime.now, nullable=False)

    deliveries = db.relationship(
        'WebhookEvent', backref='subscription',
        cascade='all, delete-orphan', lazy='dynamic')

    __table_args__ = (
        db.UniqueConstraint('site_id', 'url', name='uq_webhook_sub_site_url'),
    )

    @staticmethod
    def generate_secret():
        return secrets.token_hex(32)

    def set_secret(self, plain):
        self.secret_enc = encrypt_value(plain)

    @property
    def secret(self):
        return decrypt_value(self.secret_enc) or ''

    @property
    def secret_mask(self):
        plain = self.secret
        return '********' + plain[-4:] if len(plain) >= 4 else '********'

    @property
    def event_list(self):
        return [e for e in (self.events or '').split(',') if e]

    def subscribes(self, event_type):
        return event_type in self.event_list


class WebhookEvent(db.Model):
    """一次事件对一个订阅的投递记录。"""

    STATUS_PENDING = 'pending'
    STATUS_DELIVERING = 'delivering'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'

    __tablename__ = 'webhook_events'

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(
        db.Integer, db.ForeignKey('webhook_subscriptions.id', ondelete='CASCADE'),
        nullable=False, index=True)
    site_id = db.Column(db.Integer, nullable=False, default=0, index=True)
    event_type = db.Column(db.String(64), nullable=False)
    payload_json = db.Column(db.Text, nullable=False, default='{}')
    status = db.Column(db.String(16), nullable=False, default=STATUS_PENDING)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    next_retry_at = db.Column(db.DateTime, index=True)
    last_status_code = db.Column(db.Integer)
    last_error = db.Column(db.Text)
    # 消费方幂等标识（X-ZhyCMS-Delivery），重试保持不变
    replay_id = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    delivered_at = db.Column(db.DateTime)

    __table_args__ = (
        db.Index('ix_webhook_events_status_retry', 'status', 'next_retry_at'),
        db.Index('ix_webhook_events_site_created', 'site_id', 'created_at'),
    )
