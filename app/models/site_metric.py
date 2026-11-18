"""站点资源指标每日快照。"""
from datetime import datetime

from ..extensions import db


class SiteMetricSnapshot(db.Model):
    """按站点、按天保存的文章/浏览量/缓存/磁盘指标。"""
    __tablename__ = 'site_metric_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    article_count = db.Column(
        db.Integer, nullable=False, default=0, server_default='0')
    view_count = db.Column(
        db.Integer, nullable=False, default=0, server_default='0')
    cache_entries = db.Column(db.Integer, nullable=True)
    disk_bytes = db.Column(
        db.BigInteger, nullable=False, default=0, server_default='0')
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('site_id', 'date', name='uq_site_metric_site_date'),
    )

    def __repr__(self):
        return f'<SiteMetricSnapshot site={self.site_id} date={self.date}>'
