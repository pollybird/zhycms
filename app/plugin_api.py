"""插件开发接口（v2.2.0 插件机制 / v2.3.0 新增国际化钩子）。

插件目录约定：项目根 plugins/<slug>/，内含 manifest.json（纯元数据）与
__init__.py（定义 PluginBase 子类并实例化为模块级变量 `plugin`）。

核心在启动时通过 app.plugin_system.discover_and_load() 全量导入并注册：
  - get_admin_routes(admin_bp)   在核心后台蓝本上注册路由（endpoint 归入 admin.*，
                                 自动获得后台地址前缀即时生效机制）
  - get_frontend_blueprint()     返回前台蓝本（含模板与静态资源），核心负责注册
  - get_api_routes(api_bp)       向核心内容 API 蓝本（/api/v1）注册只读端点
  - get_jinja_globals()          注册模板全局函数（核心自动包裹「插件启用」守卫，
                                 未启用时返回 get_jinja_fallbacks() 声明的空值）
  - get_admin_menu()             声明后台侧边栏菜单（启用且有权限才显示）
  - get_sitemap_urls()           向 sitemap.xml 贡献 URL
  - generate_demo_data()         演示数据生成钩子（仅启用时调用）
  - get_i18n_dir()               v2.3：返回插件自有翻译目录（默认 translations/），
                                 存在时自动作为独立 domain 加载；模板中
                                 `{{ _p('<slug>', '原文')|safe }}` 或 Python 代码
                                 `plugin._('原文')` 走插件域翻译。

启用/禁用即时生效（运行时 Setting 门控），无需重启。
"""

import os


class PluginBase:
    """插件基类：子类按需覆写钩子方法。"""

    # ---- 元数据（与 manifest.json 保持一致，以类属性为准） ----
    slug = ''
    name = ''
    version = '1.0.0'
    description = ''
    author = ''

    # ---- 声明式注册信息 ----
    # [(code, label, desc)] 启用时幂等种子写入 permissions 表
    permissions = []
    # {role_code: [perm_code, ...]} 启用时幂等给预设角色补授权
    preset_role_grants = {}
    # [(module_code, label)] 审计日志页筛选下拉聚合
    audit_modules = []

    # ---- 代码钩子 ----

    # ---- 国际化（v2.3） ----

    def get_i18n_dir(self):
        """返回插件自有翻译目录（绝对或相对插件包目录）。

        默认返回插件包下的 translations/。若该目录存在且包含
        ``<locale>/LC_MESSAGES/messages.(po|mo)``，核心会自动把
        ``messages`` 作为 Babel 补充域挂到当前 locale 下，使：
          - Jinja: ``{{ _p('<slug>', '原文') }}``
          - Python: ``self._('原文')`` / ``self.ngettext(sing, plur, n)``
        三者生效。翻译不命中时 fallback 到原文（中文）。
        """
        try:
            base = os.path.dirname(os.path.abspath(__import__(
                type(self).__module__).__file__))
        except Exception:
            base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, 'translations')

    def _(self, message):
        """便捷翻译函数：等价于 ``plugin_gettext(self.slug, message)``。"""
        from .i18n import plugin_gettext
        return plugin_gettext(self.slug, message)

    def ngettext(self, singular, plural, n):
        """便捷复数翻译函数：等价于 ``plugin_ngettext(self.slug, s, p, n)``。"""
        from .i18n import plugin_ngettext
        return plugin_ngettext(self.slug, singular, plural, n)

    # ---- 路由与模板注册 ----

    def get_admin_routes(self, admin_bp):
        """在核心后台蓝本上注册路由（@admin_bp.route）。

        注意 endpoint 会归入 admin.* 命名空间，命名建议 admin.<slug>_xxx。
        """

    def get_frontend_blueprint(self):
        """返回前台蓝本（可含 template_folder/static_folder），无需返回则 None。

        建议：Blueprint(f'{self.slug}_frontend', __name__,
                        template_folder='templates',
                        static_folder='static',
                        static_url_path=f'/plugins-static/{self.slug}')
        """
        return None

    def get_api_routes(self, api_bp):
        """向核心内容 API 蓝本（url_prefix=/api/v1）注册只读端点。"""

    def get_jinja_globals(self):
        """返回 {模板全局函数名: 函数}；核心自动包裹启用守卫。"""
        return {}

    def get_jinja_fallbacks(self):
        """返回 {函数名: 未启用时的返回值}，未声明的默认 None。"""
        return {}

    def get_admin_menu(self):
        """返回后台菜单项列表：
        [{'label', 'endpoint', 'icon', 'permission', 'active_prefix'}, ...]
        - endpoint: admin.* 端点名
        - permission: 显示所需权限点（None=登录即可）
        - active_prefix: 高亮判断用 active_menu 前缀
        """
        return []

    def get_frontend_menu(self):
        """返回前台导航菜单项列表（v2.2.0）：
        [{'label', 'url', 'target'}, ...]
        - 仅启用插件的菜单项会出现在前台导航栏（追加在栏目之后）
        - url 建议返回插件固定路由（如 '/jobs'）；target 为链接打开方式（'' 当前页）
        - 归属栏目的插件（如产品）栏目本身已进导航，无需实现本钩子
        """
        return []

    def get_sitemap_urls(self):
        """yield {'loc', 'lastmod', 'changefreq', 'priority'}（loc 为完整 URL）。"""
        return []

    def generate_demo_data(self, industry):
        """演示数据生成钩子（industry: manufacturing / service）。"""
