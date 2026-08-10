from datetime import datetime

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
    is_super = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)


class LoginLog(db.Model):
    __tablename__ = 'login_logs'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, index=True)
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    result = db.Column(db.String(16), nullable=False)  # success / failed
    message = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
