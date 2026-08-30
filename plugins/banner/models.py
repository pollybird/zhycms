"""轮播图插件：数据模型。

图片优先走上传中心（image_id → uploaded_files，保存/删除维护 ref_count）；
external_url 兼容外链图片与演示数据（本地演示图未经上传中心登记）。
"""
from datetime import datetime

from app.extensions import db


class BannerGroup(db.Model):
    """轮播分组：一个分组对应模板上一个轮播位。"""
    __tablename__ = 'banner_groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)            # 如「首页大图」
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    remark = db.Column(db.String(255))
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now,
                           onupdate=datetime.now, nullable=False)

    items = db.relationship(
        'Banner', backref='group', lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='Banner.sort_order.asc(), Banner.id.asc()')


class Banner(db.Model):
    """单张轮播图。"""
    __tablename__ = 'banners'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('banner_groups.id'),
                         nullable=False, index=True)
    title = db.Column(db.String(200))                            # alt 文案
    image_id = db.Column(db.Integer, db.ForeignKey('uploaded_files.id'))
    external_url = db.Column(db.String(500))                     # 外链图片（与 image_id 二选一）
    link_url = db.Column(db.String(500))                         # 留空纯展示
    link_target = db.Column(db.String(16), default='_self')
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    start_at = db.Column(db.DateTime)                            # 可选定时上线
    end_at = db.Column(db.DateTime)                              # 可选定时下线
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now,
                           onupdate=datetime.now, nullable=False)

    image = db.relationship('UploadedFile')

    def image_url(self):
        """展示用图片 URL：上传中心优先，外链兜底。"""
        if self.image is not None and self.image.url:
            return self.image.url
        return self.external_url or ''
