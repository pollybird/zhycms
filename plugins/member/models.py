"""前台会员插件数据模型。

与后台管理员（users 表）完全独立：
  members          前台会员账号（用户名/手机/邮箱 + 密码）
  member_oauths    第三方账号绑定（微信/QQ，独立绑定表，不污染会员主表）
  member_sms_codes 短信验证码（哈希存储，含用途/频控/有效期）
"""
import hashlib
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db


class Member(db.Model):
    """前台会员。"""
    __tablename__ = 'members'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255))  # 第三方/短信注册用户初始可为空
    nickname = db.Column(db.String(64))
    avatar = db.Column(db.String(255))
    email = db.Column(db.String(128), index=True)
    phone = db.Column(db.String(20), index=True)
    gender = db.Column(db.String(8), default='')  # '' / male / female
    signature = db.Column(db.String(255))

    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    # 登录安全（与后台管理员同策略：5 次失败锁 10 分钟）
    last_login_at = db.Column(db.DateTime)
    last_login_ip = db.Column(db.String(64))
    login_fail_count = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    oauths = db.relationship(
        'MemberOauth', backref='member', cascade='all, delete-orphan', lazy='dynamic'
    )

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw)

    @property
    def display_name(self):
        return self.nickname or self.username

    @property
    def is_locked(self):
        if self.locked_until and self.locked_until > datetime.now():
            return True
        if self.locked_until and self.locked_until <= datetime.now():
            self.locked_until = None
            self.login_fail_count = 0
        return False

    def record_login_fail(self, max_fail=5, lock_minutes=10):
        self.login_fail_count = (self.login_fail_count or 0) + 1
        if self.login_fail_count >= max_fail:
            self.locked_until = datetime.now() + timedelta(minutes=lock_minutes)

    def reset_login_fail(self):
        self.login_fail_count = 0
        self.locked_until = None


class MemberOauth(db.Model):
    """第三方账号绑定（provider+openid 唯一）。"""
    __tablename__ = 'member_oauths'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False, index=True)
    provider = db.Column(db.String(20), nullable=False)  # wechat / qq
    openid = db.Column(db.String(128), nullable=False)
    unionid = db.Column(db.String(128))
    nickname = db.Column(db.String(128))
    avatar = db.Column(db.String(255))
    raw_info = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('provider', 'openid', name='uq_member_oauth_openid'),
    )


class MemberSmsCode(db.Model):
    """短信验证码（仅存哈希值，不留存明文）。"""
    __tablename__ = 'member_sms_codes'

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), nullable=False, index=True)
    code_hash = db.Column(db.String(64), nullable=False)
    purpose = db.Column(db.String(20), nullable=False, default='login')  # login / reset
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    ip = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)

    @staticmethod
    def hash_code(phone, code):
        return hashlib.sha256(f'{phone}:{code}'.encode('utf-8')).hexdigest()

    @property
    def is_expired(self):
        return datetime.now() > self.expires_at
