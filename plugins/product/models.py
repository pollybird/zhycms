"""产品插件：数据模型。

与设计的差异说明（评审定稿口径）：
  - 封面与相册存图片 URL（而非 uploaded_files.id），与 Article.cover 惯例一致，
    便于外链图片与演示数据；上传中心在上传时已完成去重与 ref_count 登记。
  - gallery 为 JSON 数组（有序 URL 列表），specs 为 JSON 数组（分组 + 键值）。
"""
import json
from datetime import datetime

from app.extensions import db


class Product(db.Model):
    """产品：归属列表栏目（复用栏目树/栏目授权/伪静态/SEO/缓存体系），无工作流。"""
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    column_id = db.Column(db.Integer, db.ForeignKey('columns.id'),
                          nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    summary = db.Column(db.Text)                     # 列表页简介
    content = db.Column(db.Text)                     # 富文本详情（CKEditor）
    cover = db.Column(db.String(500))                # 封面 URL（空则取相册第一张）
    gallery = db.Column(db.Text)                     # JSON：[url, ...] 有序相册
    specs = db.Column(db.Text)                       # JSON：[{'group','items':[{'name','value'}]}]
    seo_title = db.Column(db.String(255))
    seo_keywords = db.Column(db.String(255))
    seo_description = db.Column(db.String(500))
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now,
                           onupdate=datetime.now, nullable=False)

    column = db.relationship('Column')

    # v2.5.0：多语言翻译（非默认语言的 title/summary/content/seo_* 存于此）
    translations = db.relationship(
        'ProductTranslation', backref='product',
        cascade='all, delete-orphan', lazy='selectin'
    )

    # ---- 相册 / 规格 ----

    def gallery_urls(self):
        """相册 URL 有序列表（JSON 解析失败兜底为空）。"""
        if not self.gallery:
            return []
        try:
            data = json.loads(self.gallery)
            return [u for u in data if isinstance(u, str) and u]
        except (ValueError, TypeError):
            return []

    def cover_url(self):
        """展示用封面：显式封面优先，否则相册第一张。"""
        if self.cover:
            return self.cover
        urls = self.gallery_urls()
        return urls[0] if urls else ''

    def specs_grouped(self, locale=None):
        """规格参数（JSON 解析失败兜底为空）。

        v2.5.2：locale 传入时优先取该语言翻译的 specs（结构同主表），
        翻译为空则回退主表默认语言；locale 为 None 只解析主表
        （后台编辑页预填用，不随请求语言漂移）。
        """
        if locale:
            from app.utils.i18n_content import t_field
            groups = self._parse_specs_json(
                t_field(self, 'specs', locale))
            if groups:
                return groups
        return self._parse_specs_json(self.specs)

    def translation_specs_grouped(self, locale):
        """指定语言翻译的规格（仅翻译表，不回退主表；后台编辑页预填用）。"""
        for tr in self.translations:
            if tr.locale == locale:
                return self._parse_specs_json(tr.specs)
        return []

    @staticmethod
    def _parse_specs_json(raw):
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
        if not isinstance(data, list):
            return []
        return [
            {
                'group': (g.get('group') or '').strip(),
                'items': [
                    {'name': (it.get('name') or '').strip(),
                     'value': (it.get('value') or '').strip()}
                    for it in (g.get('items') or [])
                    if (it.get('name') or '').strip()
                ],
            }
            for g in data if isinstance(g, dict)
        ]


class ProductTranslation(db.Model):
    """产品多语言翻译（v2.5.0；v2.5.2 增加规格参数 specs）。

    主表 products 存默认语言内容；非默认语言的 title/summary/content/
    seo_*/specs 存于此表。查不到对应 locale 的翻译时 fallback 到主表
    默认语言字段（specs 置空即回退主表）。
    """
    __tablename__ = 'product_translations'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer,
                           db.ForeignKey('products.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    locale = db.Column(db.String(10), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    summary = db.Column(db.Text)
    content = db.Column(db.Text)
    specs = db.Column(db.Text)     # JSON：[{'group','items':[{'name','value'}]}]
    seo_title = db.Column(db.String(255))
    seo_keywords = db.Column(db.String(255))
    seo_description = db.Column(db.String(500))

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now,
                           onupdate=datetime.now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('product_id', 'locale', name='uq_product_locale'),
        db.Index('ix_product_trans_locale', 'locale'),
    )
