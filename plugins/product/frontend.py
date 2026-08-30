"""产品插件：前台模板函数（注册为 Jinja 全局，核心自动包裹启停守卫）。

- product_list_data(column)   栏目产品分页（themes/<主题>/list_product.html 专用）
- product_latest(slug, limit) 首页等处的产品卡片数据
- frontend_product_url(p)     产品详情 URL（伪静态开 → /product-{id}.html，关 → 动态 URL）
"""
from flask import request, url_for

from app.models.setting import Setting


def frontend_product_url(product, column=None):
    """产品详情 URL：伪静态开启用 /product-{id}.html，否则动态 URL。"""
    if Setting.get('seo_rewrite_enable') == 'on':
        return f'/product-{product.id}.html'
    col = column or product.column
    try:
        return url_for('product_frontend.product_detail_by_column',
                       slug=col.slug, pid=product.id)
    except Exception:
        return f'/column/{col.slug}/product/{product.id}'


def product_brief(product, column=None):
    """产品摘要（列表/卡片用，不含正文大字段）。"""
    col = column or product.column
    return {
        'id': product.id,
        'title': product.title,
        'summary': product.summary or '',
        'cover': product.cover_url(),
        'sort_order': product.sort_order,
        'url': frontend_product_url(product, col),
        'column': {'id': col.id, 'name': col.name, 'slug': col.slug}
        if col is not None else None,
    }


def product_list_data(column, page=None):
    """栏目产品分页数据。product_list.html 中：
    {% set pdata = product_list_data(column) %}。
    插件未启用时守卫返回 {'items': [], 'pagination': None}。
    """
    from .models import Product

    if page is None:
        page = request.args.get('page', 1)
        # 伪静态路由把页码放在 view_args 里
        view_page = (request.view_args or {}).get('page')
        if view_page is not None and column is not None \
                and (request.view_args or {}).get('slug') == column.slug:
            page = view_page
    try:
        page = max(int(page), 1)
    except (TypeError, ValueError):
        page = 1
    per_page = (column.page_size or 10) if column is not None else 10

    q = Product.query.filter_by(
        column_id=column.id, is_enabled=True, is_deleted=False
    ).order_by(Product.sort_order.desc(), Product.id.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    return {
        'items': [product_brief(p, column) for p in pagination.items],
        'pagination': pagination,
    }


def product_latest(column_slug, limit=8):
    """指定栏目（按 slug，含其启用子栏目）的最新产品卡片数据；栏目不存在返回 []。"""
    from app.models.column import Column
    from .models import Product

    col = Column.query.filter_by(slug=column_slug, is_enabled=True,
                                 is_deleted=False).first()
    if col is None:
        return []
    col_ids = [col.id]
    for child in col.children.filter_by(is_enabled=True, is_deleted=False).all():
        col_ids.append(child.id)
    products = Product.query.filter(
        Product.column_id.in_(col_ids),
        Product.is_enabled == True,   # noqa: E712
        Product.is_deleted == False,  # noqa: E712
    ).order_by(Product.sort_order.desc(), Product.id.desc()) \
        .limit(max(int(limit or 8), 1)).all()
    return [product_brief(p) for p in products]
