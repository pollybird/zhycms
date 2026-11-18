"""站点回收站：记录被删除站点及可彻底删除的时间。

站点删除后仅为软删除（`sites.is_deleted=True`），内容行保留；到期前可恢复，
到期后由定时任务先自动备份再彻底删除。
"""
from datetime import datetime

from ..extensions import db


class SiteRecycleBin(db.Model):
    """站点回收站记录。"""
    __tablename__ = 'site_recycle_bin'

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, nullable=False, index=True)
    slug = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    deleted_by = db.Column(db.Integer, nullable=True)
    deleted_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    purge_at = db.Column(db.DateTime, nullable=False, index=True)
    restored_at = db.Column(db.DateTime, nullable=True)
    snapshot_json = db.Column(db.Text)

    def __repr__(self):
        return f'<SiteRecycleBin site={self.site_id}>'
