"""产品插件（v2.2.0 官方插件之二）。

目录结构（详见 DESIGN-v2.2.0.md §四）：
  manifest.json        元数据（插件管理页展示）
  __init__.py          Plugin 类定义与实例（插件入口）
  models.py            Product 模型（导入即注册，启用时自动建表）
  admin.py             后台管理路由（挂核心 admin_bp）
  frontend.py          product_list_data() / product_latest() / frontend_product_url()
  frontend_routes.py   前台详情路由（动态 + 伪静态）
  api.py               GET /api/v1/columns/<slug>/products、/api/v1/products/<pid>
  demo.py              演示数据钩子（manufacturing 行业）
  templates/product/   后台页面 + 前台详情兜底模板
"""
from app.plugin_api import PluginBase
from app.constants import Roles as _R

from . import admin as _admin       # noqa: F401  导入即注册后台路由（并引入 models）
from .frontend import (
    frontend_product_url, product_brief, product_list_data, product_latest,
)


class ProductPlugin(PluginBase):
    slug = 'product'
    version = '1.1.0'
    author = 'ZhyCMS 官方'

    # ---- 声明式注册 ----
    permissions = [('product:manage', '产品管理', '产品增删改与相册/规格维护')]
    preset_role_grants = {
        _R.CONTENT_AUDITOR: ['product:manage'],
        _R.CONTENT_EDITOR: ['product:manage'],
    }

    # ---- 代码钩子 ----

    @property
    def name(self):
        return self._('产品展示')

    @property
    def description(self):
        return self._('产品多图相册与规格参数表，归属栏目树管理，区别普通文章，适合制造业企业')

    @property
    def audit_modules(self):
        return [('product', self._('产品管理'))]

    def get_admin_menu(self):
        return [{
            'label': self._('产品管理'),
            'endpoint': 'admin.product_index',
            'icon': 'fa-box-open',
            'permission': 'product:manage',
            'active_prefix': 'product',
        }]

    def get_admin_menu_icon(self):
        return 'fa-box-open'

    def get_frontend_blueprint(self):
        # 直接返回 frontend_routes 的 product_frontend 蓝本：既注册详情路由
        # （动态 + 伪静态），其 template_folder 又把插件模板接入搜索路径
        from .frontend_routes import product_frontend
        return product_frontend

    def get_jinja_globals(self):
        return {
            'frontend_product_url': frontend_product_url,
            'product_brief': product_brief,
            'product_list_data': product_list_data,
            'product_latest': product_latest,
        }

    def get_jinja_fallbacks(self):
        return {
            'frontend_product_url': '#',
            'product_brief': None,
            'product_list_data': {'items': [], 'pagination': None},
            'product_latest': [],
        }

    def get_api_routes(self, api_bp):
        from . import api as _api
        _api.register(api_bp)

    def get_sitemap_urls(self):
        """启用产品详情页收录（频率/优先级沿用文章规则，loc 为完整 URL）。"""
        from flask import has_request_context, request
        from app.models.setting import Setting
        from .models import Product
        from .frontend import frontend_product_url

        base = request.url_root.rstrip('/') if has_request_context() else ''
        if not base:
            base = (Setting.get('site_url') or '').strip().rstrip('/')
        freq = Setting.get('seo_sitemap_changefreq_article') or 'monthly'
        prio = Setting.get('seo_sitemap_priority_article') or '0.6'
        urls = []
        q = Product.query.filter_by(is_enabled=True, is_deleted=False) \
            .order_by(Product.updated_at.desc()).limit(2000)
        for p in q:
            urls.append({
                'loc': base + frontend_product_url(p),
                'lastmod': p.updated_at.strftime('%Y-%m-%d')
                if p.updated_at else '',
                'changefreq': freq,
                'priority': prio,
            })
        return urls

    def get_search_provider(self):
        """产品进入全站搜索（v2.5.2）：索引/SQL 兜底/结果 URL 均由其负责。"""
        from .search import ProductSearchProvider
        return ProductSearchProvider()

    def on_disabled(self):
        """禁用后从全站搜索索引移除全部产品（禁用后 SQL 兜底亦不再召回）。

        重建前历史索引中的产品文档需主动清除，否则索引检索仍会命中并导致
        详情链接 404；SQL 兜底因提供者已随门控失效，天然不再返回产品。
        """
        try:
            from app.extensions import db
            from app.utils.search import get_backend
            from .models import Product
            backend = get_backend()
            ids = [row[0] for row in
                   db.session.query(Product.id).filter_by(is_deleted=False).all()]
            for pid in ids:
                backend.unindex_object('product', pid)
        except Exception:
            pass

    def generate_demo_data(self, industry):
        from .demo import generate
        generate(industry)


plugin = ProductPlugin()
