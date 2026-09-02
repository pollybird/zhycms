"""友情链接插件（v2.2.0 起由核心功能转为内置插件）。

目录结构（参照 banner 插件，详见 DESIGN-v2.2.0.md §三）：
  manifest.json   元数据（builtin: true 官方内置）
  __init__.py     Plugin 类定义与实例（插件入口）
  models.py       FriendLink（导入即注册，启用时自动建表；表名沿用核心
                  原表 friend_links，老站升级后数据无缝保留）
  admin.py        后台管理路由（挂核心 admin_bp，原 /friend-links 路径不变）
  frontend.py     friend_links() 模板全局函数
  demo.py         演示数据钩子（制造业/服务业各 3 条演示链接）
  templates/      后台管理页面（由插件蓝本模板目录提供）

迁移兼容说明：
  - 表结构与审计模块代码（friend_link）与核心版完全一致，历史审计日志
    在插件启用后自动正常翻译显示；
  - 老站点升级后由 create_app 一次性自动启用本插件（Setting 标记
    friend_link_plugin_migrated），无需手工操作。
"""
from app.plugin_api import PluginBase

from . import admin as _admin  # noqa: F401  导入即注册后台路由（并引入 models）
from .frontend import friend_links


class FriendLinkPlugin(PluginBase):
    slug = 'friend_link'
    version = '1.0.0'
    author = 'ZhyCMS 官方'

    # ---- 声明式注册 ----
    # 沿用核心时代行为：仅系统设置类角色可管理，预设内容角色不默认授权，
    # 需要时可由超级管理员在「角色权限」中为自定义角色勾选
    permissions = [('friend_link:manage', '友情链接管理', '友情链接的增删改与启停')]
    preset_role_grants = {}

    # ---- 代码钩子 ----

    @property
    def name(self):
        return self._('友情链接')

    @property
    def description(self):
        return self._(
            '站点友情链接管理：名称/LOGO/排序/启停，前台模板 '
            'friend_links() 一行调用；v2.2.0 起由核心功能转为内置插件，'
            '老站数据无缝保留'
        )

    @property
    def audit_modules(self):
        return [('friend_link', self._('友情链接'))]

    def get_admin_menu(self):
        return [{
            'label': self._('友情链接'),
            'endpoint': 'admin.friend_link_index',
            'icon': 'fa-link',
            'permission': 'friend_link:manage',
            'active_prefix': 'friend_link',
        }]

    def get_admin_menu_icon(self):
        return 'fa-link'

    def get_frontend_blueprint(self):
        from flask import Blueprint
        # 无前台路由；注册蓝本仅为让插件模板（friend_link/*.html）
        # 进入 Jinja 分发加载器搜索路径
        return Blueprint('friend_link_frontend', __name__, template_folder='templates')

    def get_jinja_globals(self):
        return {'friend_links': friend_links}

    def get_jinja_fallbacks(self):
        return {'friend_links': []}

    def generate_demo_data(self, industry):
        from .demo import generate
        generate(industry)


plugin = FriendLinkPlugin()
