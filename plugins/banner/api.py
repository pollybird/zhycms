"""轮播图插件：内容 API 只读端点（GET /api/v1/banners/<slug>）。

端点经 api_bp 统一门控（api_enable / api_token / CORS），
额外受插件启用门控：未启用 → 404（不暴露存在性）。
"""
from app.api.views import api_ok, api_err, api_cache
from app.plugin_system import plugin_enabled


def register(api_bp):
    @api_bp.route('/banners/<slug>')
    @api_cache('banner')
    def banner_api_detail(slug):
        if not plugin_enabled('banner'):
            return api_err(404, '资源不存在')
        from .models import BannerGroup
        if BannerGroup.query.filter_by(slug=slug).first() is None:
            return api_err(404, '轮播分组不存在')
        from .frontend import banner_items
        return api_ok(banner_items(slug))
