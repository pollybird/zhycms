"""友情链接插件：数据模型。

FriendLink  友情链接（名称/URL/LOGO/排序/启停/软删除）
表结构沿用核心迁移前定义（friend_links），旧站点升级后数据无缝保留。
"""
from datetime import datetime

from app.extensions import db


class FriendLink(db.Model):
    __tablename__ = 'friend_links'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(255), nullable=False)
    logo = db.Column(db.String(255))
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    target = db.Column(db.String(16), default='_blank')  # _self / _blank
    remark = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now,
                           onupdate=datetime.now, nullable=False)
