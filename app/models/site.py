"""站群模式（v3.2.0）：站点注册表与站点维度列。

设计要点：
- 默认站点固定 `id = 0`（`is_default=True`），单站点部署行为与现网完全一致；
- `SiteScopedMixin` 为内容表提供统一的 `site_id` 维度列（镜像 i18n 的 locale 维度）；
- `domain` 精确域名匹配 + `subdomain` 泛解析子域标签双列并存。

MySQL 注意：显式插入 id=0 需要会话级 `NO_AUTO_VALUE_ON_ZERO`，
由迁移 0012 负责设置；SQLite / PostgreSQL 原生支持。
"""
from datetime import datetime
import re

from ..extensions import db

# 默认站点主键（单站点部署恒为该值）
DEFAULT_SITE_ID = 0


class Site(db.Model):
    """站点注册表（站群模式的核心元数据）。"""
    __tablename__ = 'sites'

    id = db.Column(db.Integer, primary_key=True)  # 默认站点固定为 0
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    # 全量域名（精确匹配），如 www.b.com；空表示不按独立域名寻址
    domain = db.Column(db.String(255), unique=True)
    # 子域标签（配合泛解析 *.main.com），如 b；空值存 NULL（多 NULL 可共存）
    subdomain = db.Column(db.String(100), unique=True, index=True)
    status = db.Column(db.String(16), default='open', nullable=False)  # open / closed
    theme = db.Column(db.String(64))  # 站点主题，空则回退全局 site_theme
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    # 站点级 SEO（冗余，便于不 join settings 直取）
    seo_title = db.Column(db.String(255))
    seo_keywords = db.Column(db.String(255))
    seo_description = db.Column(db.String(500))
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    @classmethod
    def get_default(cls):
        """返回默认站点（id=0），不存在时返回 None。"""
        return cls.query.filter_by(id=DEFAULT_SITE_ID, is_deleted=False).first()

    @classmethod
    def ensure_default(cls):
        """幂等确保默认站点（id=0）存在，返回该站点。

        v3.3.2 起新装改为直接 stamp 最新迁移版本、跳过增量迁移，默认站点
        不再由迁移 0012 创建；在此兜底，保证任何启动路径（新装 / 旧库升级 /
        已管理）下默认站点都存在。已存在时为 no-op。
        """
        from sqlalchemy import text
        existing = cls.query.filter_by(id=DEFAULT_SITE_ID).first()
        if existing is not None:
            return existing
        # MySQL 下显式插入 id=0 会被当作自增值，需临时关闭该行为（同迁移 0012）
        if db.engine.dialect.name == 'mysql':
            db.session.execute(text(
                "SET SESSION sql_mode = CONCAT(@@sql_mode, ',NO_AUTO_VALUE_ON_ZERO')"))
        site = cls(
            id=DEFAULT_SITE_ID, name='默认站点', slug='default',
            status='open', is_default=True, sort_order=0, is_deleted=False,
        )
        db.session.add(site)
        db.session.flush()
        return site

    @classmethod
    def active_sites(cls):
        """返回未删除站点（按 sort_order 降序、id 升序）。"""
        return cls.query.filter_by(is_deleted=False).order_by(
            cls.sort_order.desc(), cls.id.asc()).all()

    @staticmethod
    def normalize_host(value):
        """域名/子域规范化：去空白、转小写、去尾点；空串返回 None。"""
        if not value:
            return None
        host = str(value).strip().lower().rstrip('.')
        return host or None

    @staticmethod
    def is_valid_domain(value):
        """按 DNS label 规则校验完整域名（不含协议与路径）。"""
        if not value or len(value) > 253 or '..' in value:
            return False
        for label in value.split('.'):
            if not label or len(label) > 63:
                return False
            if label[0] == '-' or label[-1] == '-':
                return False
            if not re.fullmatch(r'[a-z0-9-]+', label):
                return False
        return True

    def __repr__(self):
        return f'<Site {self.id} {self.slug}>'


class SiteScopedMixin:
    """内容按站点切分的统一维度列。

    默认值 0 保证存量数据与单站点部署语义不变；插件模型可直接继承本 mixin
    获得站点维度（见 `app/plugin_api.py` 的站群 SDK）。
    """
    site_id = db.Column(db.Integer, nullable=False, default=DEFAULT_SITE_ID,
                        server_default='0', index=True)
