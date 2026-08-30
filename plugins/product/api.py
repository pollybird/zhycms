"""产品插件：内容 API 只读端点。

  GET /api/v1/columns/<slug>/products   产品分页列表
  GET /api/v1/products/<int:pid>        产品详情（相册/规格/正文/SEO）

端点经 api_bp 统一门控（api_enable / api_token / CORS），
额外受插件启用门控：未启用 → 404（不暴露存在性）。
"""
from flask import request

from app.api.views import (
    api_ok, api_err, api_cache, _abs_url, _get_enabled_column,
    _pagination_meta, _to_int,
)
from app.plugin_system import plugin_enabled
from app.models.setting import Setting


def _product_summary(p, col=None):
    from .frontend import frontend_product_url

    col = col or p.column
    url = frontend_product_url(p, col)
    if url.startswith('/'):
        url = _abs_url(url)
    return {
        'id': p.id, 'title': p.title, 'summary': p.summary or '',
        'cover': _abs_url(p.cover_url()),
        'sort_order': p.sort_order, 'url': url,
        'column': {'id': col.id, 'name': col.name, 'slug': col.slug}
        if col is not None else None,
    }


def _product_detail(p, col):
    data = _product_summary(p, col)
    data.update({
        'content': p.content or '',
        'gallery': [_abs_url(u) for u in p.gallery_urls()],
        'specs': p.specs_grouped(),
        'seo': {
            'title': p.seo_title or p.title,
            'keywords': p.seo_keywords or '',
            'description': p.seo_description or p.summary or '',
        },
    })
    return data


def register(api_bp):

    @api_bp.route('/columns/<slug>/products')
    @api_cache('products')
    def product_api_list(slug):
        if not plugin_enabled('product'):
            return api_err(404, '资源不存在')
        col = _get_enabled_column(slug)
        if col is None:
            return api_err(404, '栏目不存在')
        from .models import Product

        page = max(_to_int(request.args.get('page'), 1), 1)
        per_page = min(max(_to_int(request.args.get('per_page'), 10), 1), 50)
        q = Product.query.filter_by(
            column_id=col.id, is_enabled=True, is_deleted=False
        ).order_by(Product.sort_order.desc(), Product.id.desc())
        keyword = (request.args.get('keyword') or '').strip()
        if keyword:
            q = q.filter(Product.title.like(f'%{keyword}%'))
        pagination = q.paginate(page=page, per_page=per_page, error_out=False)
        return api_ok(
            [_product_summary(p, col) for p in pagination.items],
            meta=_pagination_meta(pagination),
        )

    @api_bp.route('/products/<int:pid>')
    @api_cache('product')
    def product_api_detail(pid):
        if not plugin_enabled('product'):
            return api_err(404, '资源不存在')
        from .models import Product

        p = Product.query.get(pid)
        if p is None or p.is_deleted or not p.is_enabled:
            return api_err(404, '产品不存在')
        col = p.column
        if col is None or col.is_deleted or not col.is_enabled:
            return api_err(404, '产品不存在')
        data = _product_detail(p, col)
        base_q = Product.query.filter(
            Product.column_id == col.id,
            Product.is_deleted == False,  # noqa: E712
            Product.is_enabled == True,  # noqa: E712
        )
        prev_p = base_q.filter(Product.id < p.id) \
            .order_by(Product.id.desc()).first()
        next_p = base_q.filter(Product.id > p.id) \
            .order_by(Product.id.asc()).first()
        data['prev'] = {'id': prev_p.id, 'title': prev_p.title} if prev_p else None
        data['next'] = {'id': next_p.id, 'title': next_p.title} if next_p else None
        return api_ok(data)
