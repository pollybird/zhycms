"""产品插件：前台路由蓝本。

路由：
  /column/<slug>/product/<int:pid>   产品详情动态 URL（与文章对称）
  /product-<int:pid>.html            产品详情伪静态 URL（Werkzeug 静态段优先，
                                     与 /article-{id}.html 同级，先于分页规则匹配）

模板解析链：themes/<当前主题>/product_detail.html（企业可覆盖）
           → plugins/product/templates/product/product_detail.html（插件兜底）。
"""
import os
from functools import wraps

from flask import Blueprint, render_template, abort
from flask import current_app  # noqa: F401

from app.extensions import db
from app.extensions import cache
from app.models.column import Column
from app.models.setting import Setting
from app.plugin_system import plugin_enabled
from app.utils.themes import theme_template, get_active_theme, THEMES_DIR

from .models import Product
from .frontend import product_brief

product_frontend = Blueprint('product_frontend', __name__,
                             template_folder='templates')


# ============================================================
# 守卫 / 缓存 / 模板解析
# ============================================================

def _gate(view):
    """插件启用守卫：未启用 → 404（不暴露存在性）。"""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('product'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def _try_cache(key, ttl_setting_key, default_ttl=900):
    """页面缓存（与前台 views._try_cache 同款简易实现）。"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if Setting.get('cache_enable') != 'on':
                return view_func(*args, **kwargs)
            try:
                ttl = int(Setting.get(ttl_setting_key, default_ttl))
            except (TypeError, ValueError):
                ttl = default_ttl
            if ttl <= 0:
                return view_func(*args, **kwargs)
            cache_key = f'frontend/{key}/' + '/'.join(
                [str(v) for v in args] + [f'{k}={v}' for k, v in sorted(kwargs.items())]
            )
            # v2.5.0：缓存键包含当前 locale，避免不同语言命中同一缓存
            try:
                from app.i18n import select_locale
                cache_key += '|loc=' + select_locale()
            except Exception:
                pass
            try:
                cached = cache.get(cache_key)
                if cached is not None:
                    return cached
            except Exception:
                pass
            resp = view_func(*args, **kwargs)
            try:
                cache.set(cache_key, resp, timeout=ttl)
            except Exception:
                pass
            return resp
        return wrapper
    return decorator


def _resolve_detail_template():
    """主题有 product_detail.html 覆盖则用主题版，否则用插件自带版。"""
    theme = get_active_theme()
    if os.path.isfile(os.path.join(THEMES_DIR, theme, 'product_detail.html')):
        return theme_template('product_detail')
    return 'product/product_detail.html'


def _seo_for(product, column):
    """SEO 信息（v2.5.0：按当前 locale 取翻译，无翻译回退主表字段）。"""
    from app.utils.i18n_content import t_field
    return {
        'title': t_field(product, 'seo_title') or t_field(product, 'title'),
        'keywords': t_field(product, 'seo_keywords') or '',
        'description': t_field(product, 'seo_description') or t_field(product, 'summary') or '',
        'column': column,
    }


def _render_product_detail(column, product):
    """渲染产品详情（导航/上下篇/SEO）。"""
    from app.frontend.views import _build_nav, _inject_default_alt
    from app.utils.i18n_content import t_field

    base_q = Product.query.filter(
        Product.column_id == column.id,
        Product.is_deleted == False,  # noqa: E712
        Product.is_enabled == True,  # noqa: E712
    )
    prev_p = base_q.filter(Product.id < product.id) \
        .order_by(Product.id.desc()).first()
    next_p = base_q.filter(Product.id > product.id) \
        .order_by(Product.id.asc()).first()

    data = product_brief(product, column)
    content = t_field(product, 'content') or ''
    if content:
        content = _inject_default_alt(content)

    from app.i18n import current_locale
    return render_template(
        _resolve_detail_template(),
        product=product, pdata=data, content=content,
        gallery=[u for u in product.gallery_urls()],
        specs=product.specs_grouped(current_locale()),
        column=column, nav=_build_nav(),
        prev_product=prev_p, next_product=next_p,
        seo=_seo_for(product, column),
    )


# ============================================================
# 路由
# ============================================================

@product_frontend.route('/column/<slug>/product/<int:pid>')
@_gate
@_try_cache('product', 'cache_ttl_article', 900)
def product_detail_by_column(slug, pid):
    col = Column.query.filter_by(slug=slug, is_deleted=False).first_or_404()
    product = Product.query.get_or_404(pid)
    if product.column_id != col.id or product.is_deleted or not product.is_enabled:
        abort(404)
    if not col.is_enabled:
        abort(404)
    return _render_product_detail(col, product)


@product_frontend.route('/product-<int:pid>.html')
@_gate
@_try_cache('product', 'cache_ttl_article', 900)
def product_detail_rewrite(pid):
    """伪静态 /product-12.html（与 /article-{id}.html 同级静态前缀）。"""
    if Setting.get('seo_rewrite_enable') != 'on':
        abort(404)
    product = Product.query.get_or_404(pid)
    if product.is_deleted or not product.is_enabled:
        abort(404)
    col = Column.query.get(product.column_id)
    if col is None or col.is_deleted or not col.is_enabled:
        abort(404)
    return _render_product_detail(col, product)
