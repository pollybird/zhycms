import json
from datetime import datetime

from ..extensions import db


class Setting(db.Model):
    """全局站点配置，key-value 形式。

    预定义 key：
      site_name / site_subtitle / site_logo / site_status / site_close_reason
      footer_copyright
      seo_title / seo_keywords / seo_description
      upload_max_size / upload_allowed_exts
    """
    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    description = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # ==== CMS 自身标识（固定常量，后台使用，永远不可通过设置或演示数据修改）====
    # 与前台的“网站名称 / 前台版权”严格区分：
    #   - CMS_NAME：后台顶栏/登录页显示的 CMS 名称
    #   - CMS_COPYRIGHT：后台底部版权，永远为泰州姜堰钟毓信息技术有限公司
    CMS_NAME = '钟毓企业网站CMS'
    CMS_COPYRIGHT = '版权所有：泰州姜堰钟毓信息技术有限公司'

    DEFAULTS = {
        # site_name 为“网站名称”，前台展示企业名称，可在网站设置中修改，演示数据会写入企业名
        'site_name': '钟毓企业网站CMS',
        'site_subtitle': '欢迎访问我们的企业官方网站',
        'site_logo': '',
        'site_status': 'open',  # open / closed
        'site_close_reason': '网站维护中，请稍后访问……',
        # footer_copyright 为“前台版权”，前台底部展示企业版权，可修改，演示数据会写入企业版权
        'footer_copyright': '版权所有：泰州姜堰钟毓信息技术有限公司',
        'seo_title': '钟毓企业网站CMS',
        'seo_keywords': '',
        'seo_description': '',
        'upload_max_size': str(10 * 1024 * 1024),  # 10MB
        'upload_allowed_exts': 'jpg,jpeg,png,gif,pdf,doc,docx,xls,xlsx,zip,rar,txt',
        'site_theme': 'default',  # 前台主题
    }

    @classmethod
    def get(cls, key, default=None):
        item = cls.query.filter_by(key=key).first()
        if item is None:
            return default if default is not None else cls.DEFAULTS.get(key, '')
        return item.value or ''

    @classmethod
    def get_dict(cls):
        result = dict(cls.DEFAULTS)
        for item in cls.query.all():
            result[item.key] = item.value or ''
        return result

    @classmethod
    def set(cls, key, value):
        item = cls.query.filter_by(key=key).first()
        if item is None:
            item = cls(key=key, value=str(value) if value is not None else '')
            db.session.add(item)
        else:
            item.value = str(value) if value is not None else ''
        return item

    @classmethod
    def get_upload_max_size(cls):
        try:
            return int(cls.get('upload_max_size', cls.DEFAULTS['upload_max_size']))
        except (TypeError, ValueError):
            return 10 * 1024 * 1024

    @classmethod
    def get_allowed_exts(cls):
        raw = cls.get('upload_allowed_exts', cls.DEFAULTS['upload_allowed_exts'])
        return [e.strip().lower() for e in raw.split(',') if e.strip()]
