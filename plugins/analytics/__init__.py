"""第三方统计代码插件（v2.3.0 内置插件）。

目录结构（参照 friend_link 插件）：
  manifest.json   元数据（builtin: true 官方内置，min_core_version: 2.3.0）
  __init__.py      Plugin 类定义与实例（插件入口）
  frontend.py     analytics_head() / analytics_body() 模板全局注入函数
  admin.py         后台配置路由（挂核心 admin_bp，路径 /analytics）
  templates/analytics/settings.html  后台配置页

数据与设置：采用 Setting 键值存储（不建表，零迁移）：
  analytics_enable          总开关（1=启用 / 0=关闭）
  analytics_google          Google Analytics 代码（注入 head）
  analytics_baidu           百度统计代码（注入 head）
  analytics_webmaster       站长工具代码 cnzz/51la（注入 head）
  analytics_custom_head     自定义 </head> 前注入代码
  analytics_custom_body     自定义 </body> 前注入代码

注入机制：插件 get_jinja_globals 注册 analytics_head/analytics_body，
4 套主题 base.html 在 </head> 与 </body> 前调用（|safe）；核心自动包裹
启用守卫，未启用返回空串，模板零改动不报错。保存即写 Setting，前台
下一次请求即读到新值（Setting 无服务级缓存，符合「保存即生效」语义）。

安全：仅超级管理员或被授权 analytics:manage 的角色可编辑；注入仅作用于
前台主题页面，不注入后台管理页。
"""
from app.plugin_api import PluginBase

from . import admin as _admin  # noqa: F401  导入即注册后台路由
from .frontend import analytics_head, analytics_body


class AnalyticsPlugin(PluginBase):
    slug = 'analytics'
    version = '1.0.0'
    author = 'ZhyCMS 官方'

    # 仅系统设置类角色可管（沿用核心时代策略：不向内容角色默认授权）
    permissions = [
        ('analytics:manage', '统计代码管理', '配置第三方统计代码与自定义注入代码'),
    ]
    preset_role_grants = {}

    # ---- 代码钩子 ----

    @property
    def name(self):
        return self._('统计代码')

    @property
    def description(self):
        return self._(
            '第三方统计代码嵌入：百度统计/Google Analytics/站长工具/'
            '自定义 head/body 代码，后台配置即时生效，前台自动注入；'
            'v2.3.0 起作为内置插件'
        )

    @property
    def audit_modules(self):
        return [('analytics', self._('统计代码'))]

    def get_admin_menu(self):
        return [{
            'label': self._('统计代码'),
            'endpoint': 'admin.analytics_index',
            'icon': 'fa-chart-bar',
            'permission': 'analytics:manage',
            'active_prefix': 'analytics',
        }]

    def get_admin_menu_icon(self):
        # fas fa-chart-bar：FA5 合法 solid 图标
        return 'fa-chart-bar'

    def get_frontend_blueprint(self):
        from flask import Blueprint
        # 无前台路由；注册蓝本仅为让插件模板（analytics/*.html）
        # 进入 Jinja 分发加载器搜索路径（后台 render_template 才能找到）
        return Blueprint('analytics_frontend', __name__, template_folder='templates')

    def get_jinja_globals(self):
        return {'analytics_head': analytics_head, 'analytics_body': analytics_body}

    def get_jinja_fallbacks(self):
        # 未启用时返回空串，主题模板调用零报错
        return {'analytics_head': '', 'analytics_body': ''}


plugin = AnalyticsPlugin()
