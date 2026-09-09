"""产品插件：全站搜索内容提供者（v2.5.2）。

把 products / product_translations 的内容接入核心全站搜索：
  - 重建索引时产出全部上架产品（各语言）
  - 产品保存/删除/下架时由 admin.py 调用核心 reindex_object/unindex_object
  - 索引后端零命中/故障时，SQL 兜底检索同样覆盖产品
"""
from datetime import datetime

from app.extensions import db
from app.utils.search import SearchProvider, _search_locale
from app.utils.i18n_content import t_field, get_default_locale


PRODUCT_TYPE = 'product'


def _product_doc(product, col, locale):
    """构造产品在指定语言下的索引文档 dict（无标题返回 None）。

    正文附加本地化规格参数文本（v2.5.2：规格参数已支持多语言），使
    规格名/值（如 Model、功率）也可被全文检索。
    """
    title = t_field(product, 'title', locale) or product.title or ''
    if not title:
        return None
    content = t_field(product, 'content', locale) or product.content or ''
    specs_text = _specs_text(product.specs_grouped(locale))
    if specs_text:
        content = f'{content}\n{specs_text}' if content else specs_text
    return {
        'id': product.id,
        'title': title,
        'summary': t_field(product, 'summary', locale) or product.summary or '',
        'content': content,
        'column_id': product.column_id,
        'column_name': (t_field(col, 'name', locale) or col.name or '')
        if col is not None else '',
        'column_slug': col.slug if col is not None else '',
        'published_at': product.updated_at or product.created_at or datetime.now(),
    }


def _specs_text(groups):
    """规格分组转纯文本（分组名 参数名：参数值 …），供全文检索。"""
    parts = []
    for g in groups or []:
        head = g.get('group') or ''
        for it in g.get('items') or []:
            parts.append(f"{head} {it.get('name')}：{it.get('value')}".strip())
    return '；'.join(parts)


def _product_item(product, col, loc):
    """构造 SQL 兜底搜索结果项。"""
    return {
        'id': product.id,
        'uid': f'{PRODUCT_TYPE}:{product.id}',
        'type': PRODUCT_TYPE,
        'title': t_field(product, 'title', loc) or product.title or '',
        'summary': t_field(product, 'summary', loc) or '',
        'column_id': product.column_id,
        'column_name': (t_field(col, 'name', loc) or col.name or '')
        if col is not None else '',
        'column_slug': col.slug if col is not None else '',
        'published_at': product.updated_at or product.created_at,
        'url': None,
    }


class ProductSearchProvider(SearchProvider):
    """产品搜索提供者：索引文档产出 + SQL 兜底检索 + 结果 URL。"""

    type = PRODUCT_TYPE

    # ---- 索引 ----

    def iter_docs(self, locale):
        """重建索引：产出全部上架且未删除产品在指定语言下的文档。"""
        from .models import Product
        from app.models.column import Column
        products = Product.query.filter_by(
            is_enabled=True, is_deleted=False).all()
        col_cache = {}
        for p in products:
            col = col_cache.get(p.column_id)
            if col is None and p.column_id not in col_cache:
                col = Column.query.get(p.column_id)
                col_cache[p.column_id] = col
            doc = _product_doc(p, col, locale)
            if doc:
                yield doc

    def get_doc(self, obj_id, locale):
        """单条产品文档（实时索引用）；不存在/下架/删除返回 None。"""
        from .models import Product
        from app.models.column import Column
        p = Product.query.filter_by(
            id=obj_id, is_enabled=True, is_deleted=False).first()
        if p is None:
            return None
        return _product_doc(p, p.column or Column.query.get(p.column_id), locale)

    # ---- SQL 兜底 ----

    def sql_search(self, keyword, locale, page=1, per_page=20):
        """产品 LIKE 检索（非默认语言同时匹配 product_translations）。"""
        from .models import Product, ProductTranslation
        like = f'%{keyword}%'
        loc = _search_locale(locale)
        q = Product.query.filter(
            Product.is_deleted == False,  # noqa: E712
            Product.is_enabled == True,   # noqa: E712
        )
        main_match = db.or_(
            Product.title.like(like),
            Product.summary.like(like),
            Product.content.like(like),
        )
        if loc != get_default_locale():
            trans_ids = db.session.query(ProductTranslation.product_id).filter(
                ProductTranslation.locale == loc,
                db.or_(
                    ProductTranslation.title.like(like),
                    ProductTranslation.summary.like(like),
                    ProductTranslation.content.like(like),
                    ProductTranslation.specs.like(like),
                )
            )
            q = q.filter(db.or_(Product.id.in_(trans_ids), main_match))
        else:
            q = q.filter(main_match)
        pagination = q.order_by(Product.updated_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        items = [_product_item(p, p.column, loc) for p in pagination.items]
        return items, pagination.total

    # ---- 结果 URL ----

    def build_url(self, item):
        """产品详情 URL：伪静态开 → /product-<id>.html，否则动态路由。"""
        from flask import url_for
        from app.models.setting import Setting
        pid = item.get('id')
        if Setting.get('seo_rewrite_enable') == 'on':
            return f'/product-{pid}.html'
        slug = item.get('column_slug') or ''
        try:
            return url_for('product_frontend.product_detail_by_column',
                           slug=slug, pid=pid)
        except Exception:
            return f'/product-{pid}.html'
