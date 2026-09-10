"""轮播图插件（v2.2.0 首个示范插件）。

目录结构（详见 DESIGN-v2.2.0.md §三）：
  manifest.json   元数据（插件管理页展示）
  __init__.py     Plugin 类定义与实例（插件入口）
  models.py       BannerGroup / Banner（导入即注册，启用时自动建表）
  admin.py        后台管理路由（挂核心 admin_bp）
  frontend.py     banner_items() 模板全局函数
  api.py          GET /api/v1/banners/<slug>
  demo.py         演示数据钩子
  templates/      后台页面 + 前台轮播 partial（主题 index.html include）
"""
from app.plugin_api import PluginBase
from app.constants import Roles as _R

from . import admin as _admin  # noqa: F401  导入即注册后台路由（并引入 models）
from . import api as _api      # noqa: F401
from .frontend import banner_items


class BannerPlugin(PluginBase):
    slug = 'banner'
    version = '1.0.0'
    author = 'ZhyCMS 官方'

    # ---- 声明式注册 ----
    permissions = [('banner:manage', '轮播图管理', '轮播分组与图片管理')]
    preset_role_grants = {
        _R.CONTENT_AUDITOR: ['banner:manage'],
        _R.CONTENT_EDITOR: ['banner:manage'],
    }

    # ---- 代码钩子 ----

    @property
    def name(self):
        return self._('轮播图')

    @property
    def description(self):
        return self._('首页幻灯片/广告位分组管理，模板 banner_items() 一行调用，替代碎片拼轮播')

    @property
    def audit_modules(self):
        return [('banner', self._('轮播图'))]

    def get_admin_menu(self):
        return [{
            'label': self._('轮播管理'),
            'endpoint': 'admin.banner_group_index',
            'icon': 'fa-images',
            'permission': 'banner:manage',
            'active_prefix': 'banner',
        }]

    def get_admin_menu_icon(self):
        return 'fa-images'

    def get_frontend_blueprint(self):
        from flask import Blueprint
        # 无前台路由；注册蓝本仅为让插件模板（banner/hero_carousel.html）
        # 进入 Jinja 分发加载器搜索路径
        return Blueprint('banner_frontend', __name__, template_folder='templates')

    def get_jinja_globals(self):
        return {'banner_items': banner_items}

    def get_jinja_fallbacks(self):
        return {'banner_items': []}

    def get_api_routes(self, api_bp):
        _api.register(api_bp)

    def generate_demo_data(self, industry):
        from .demo import generate
        generate(industry)


plugin = BannerPlugin()
