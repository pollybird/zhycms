"""教程中心插件（社区插件 v1.0.0）。

参考教育行业模板设计，提供教程分类管理 + 教程发布 + 前台列表/详情页。
目录结构：
  manifest.json        元数据（builtin: false 社区插件）
  __init__.py           Plugin 类定义与实例
  models.py             TutorialCategory / Tutorial
  admin.py              后台管理路由（分类 + 教程增删改查）
  frontend_routes.py    前台蓝本 tutorial_frontend（/tutorials, /tutorials/<slug> 等）
  demo.py               演示数据钩子（教育行业）
  templates/            前台与后台模板
"""
from app.plugin_api import PluginBase

from . import admin as _admin  # noqa: F401  导入即注册后台路由（并引入 models）
from .frontend_routes import tutorial_frontend  # noqa: F401


class TutorialPlugin(PluginBase):
    slug = 'tutorial'
    version = '1.0.0'
    author = '社区贡献'

    permissions = [
        ('tutorial:manage', '教程管理', '教程与分类的增删改查'),
        ('tutorial:view', '教程查看', '查看教程列表与详情'),
    ]
    # 默认仅超管可管，内容角色可在角色权限中按需授权
    preset_role_grants = {}

    @property
    def name(self):
        return self._('教程中心')

    @property
    def description(self):
        return self._(
            '教程/课程内容管理：分类管理、教程发布（封面/难度/时长）、'
            '前台列表与详情页。适合教育、培训、知识分享类站点。'
        )

    @property
    def audit_modules(self):
        return [('tutorial', self._('教程')),
                ('tutorial_category', self._('教程分类'))]

    def get_admin_menu(self):
        return [{
            'label': self._('教程中心'),
            'endpoint': 'admin.tutorial_index',
            'icon': 'fa-graduation-cap',
            'permission': 'tutorial:view',
            'active_prefix': 'tutorial',
        }]

    def get_admin_menu_icon(self):
        return 'fa-graduation-cap'

    def get_frontend_blueprint(self):
        return tutorial_frontend

    def get_frontend_menu(self):
        # 前台导航追加「教程中心」入口（与 /tutorials 路由对应）
        return [{'label': self._('教程中心'), 'url': '/tutorials', 'target': ''}]

    def get_jinja_globals(self):
        """提供模板全局函数 tutorials(category=None, limit=8)，供主题首页
        「课程中心」等区块直接渲染教程/课程数据，无需核心视图传参。"""
        from .models import Tutorial, TutorialCategory

        def tutorials(category=None, limit=8):
            """返回启用的教程列表。

            category: 分类 slug 字符串，None=全部；limit: 条数上限。
            """
            query = Tutorial.query.filter_by(is_deleted=False, is_enabled=True)
            if category:
                cat = TutorialCategory.query.filter_by(
                    slug=category, is_deleted=False, is_enabled=True).first()
                if cat is not None:
                    query = query.filter_by(category_id=cat.id)
            return query.order_by(
                Tutorial.sort_order.desc(), Tutorial.created_at.desc()
            ).limit(limit).all()

        return {'tutorials': tutorials}

    def get_jinja_fallbacks(self):
        # 插件未启用时 tutorials() 直接返回空列表，模板 {% if courses %} 自动隐藏区块
        return {'tutorials': []}

    def generate_demo_data(self, industry):
        from .demo import generate
        generate(industry)


plugin = TutorialPlugin()
