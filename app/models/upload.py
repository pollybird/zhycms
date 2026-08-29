"""文件上传优化：上传记录 + 图片去重（基于内容 hash）。"""
from datetime import datetime

from ..extensions import db


class UploadedFile(db.Model):
    """上传文件索引表：用于去重、图片压缩/缩略图关联、上传审计。"""
    __tablename__ = 'uploaded_files'

    id = db.Column(db.Integer, primary_key=True)
    original_name = db.Column(db.String(255))        # 原始文件名
    stored_name = db.Column(db.String(255), nullable=False)  # 存储相对路径，如 uploads/article/20260101/uuid.jpg
    url = db.Column(db.String(512))                   # 可访问 URL
    file_size = db.Column(db.Integer, default=0)      # 原始大小（字节）
    compressed_size = db.Column(db.Integer, default=0)  # 压缩后大小（字节，0=未压缩）
    mime_type = db.Column(db.String(128))             # MIME 类型二次校验结果
    ext = db.Column(db.String(32))                    # 后缀（小写，不含点）
    content_hash = db.Column(db.String(64), index=True)   # SHA-256，用于去重
    kind = db.Column(db.String(16))                   # image/file/document
    width = db.Column(db.Integer)                     # 图片宽
    height = db.Column(db.Integer)                    # 图片高
    thumb_url = db.Column(db.String(512))             # 缩略图 URL
    thumb_path = db.Column(db.String(255))            # 缩略图相对路径

    uploader_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
    ref_count = db.Column(db.Integer, default=1, nullable=False)  # 引用计数（同内容去重）

    uploader = db.relationship('User', backref=db.backref('uploaded_files', lazy='dynamic'))

    @classmethod
    def find_by_hash(cls, content_hash):
        return cls.query.filter_by(content_hash=content_hash).first()

    @classmethod
    def find_by_url(cls, url):
        return cls.query.filter_by(url=url).first()
