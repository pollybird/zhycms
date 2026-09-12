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
  - get_search_provider()        v2.5.2：向全站搜索贡献独立内容（如产品），
                                 返回 app.utils.search.SearchProvider 子类实例
  - generate_demo_data()         演示数据生成钩子（仅启用时调用）
  - get_i18n_dir()               v2.3：返回插件自有翻译目录（默认 translations/），
                                 存在时自动作为独立 domain 加载；模板中
                                 `{{ _p('<slug>', '原文')|safe }}` 或 Python 代码
                                 `plugin._('原文')` 走插件域翻译。

启用/禁用即时生效（运行时 Setting 门控），无需重启。
"""

import os
import importlib


class PluginBase:
    """插件基类：子类按需覆写钩子方法。"""

    # ---- 元数据（与 manifest.json 保持一致，以类属性为准） ----
    slug = ''
    name = ''
    version = '1.0.0'
    description = ''
    author = ''
    # 最低核心版本（如 '2.6.3'），核心版本低于此值时拒绝启用
    min_core_version = ''
    # 依赖插件 slug 列表：启用前这些插件必须已启用
    requires = []
    # 父插件 slug：本插件基于其二次开发，父插件须安装且已启用
    extends = ''

    # ---- 声明式注册信息 ----
    # [(code, label, desc)] 启用时幂等种子写入 permissions 表
    permissions = []
    # {role_code: [perm_code, ...]} 启用时幂等给预设角色补授权
    preset_role_grants = {}
    # [(module_code, label)] 审计日志页筛选下拉聚合
    audit_modules = []

    # ---- 代码钩子 ----

    # ---- 数据库迁移（v2.4） ----

    def get_migration_files(self):
        """返回插件迁移文件列表（绝对路径）。

        插件可在 ``migrations/versions/`` 目录下放置 Alembic 迁移脚本。
        核心启动时自动发现并合并到 ``version_locations``，使插件
        schema 变更也纳入 Alembic 统一管理。

        无迁移文件的插件返回空列表（默认），仍由 ``db.create_all()``
        兜底建表。
        """
        try:
            mod = importlib.import_module(type(self).__module__)
            base = os.path.dirname(os.path.abspath(mod.__file__))
        except Exception:
            return []
        versions_dir = os.path.join(base, 'migrations', 'versions')
        if not os.path.isdir(versions_dir):
            return []
        return [os.path.join(versions_dir, f)
                for f in sorted(os.listdir(versions_dir))
                if f.endswith('.py') and not f.startswith('__')]

    # ---- 存储驱动（v2.4） ----

    def get_storage_drivers(self):
        """返回插件贡献的存储驱动类列表（app.utils.storage.StorageDriver 子类）。

        核心启动时自动注册进存储驱动注册表；插件禁用后其驱动不再被
        选中（get_driver 回退本地）。官方 oss_storage 插件使用本钩子
        注册阿里云 OSS / 腾讯云 COS / 七牛云驱动。
        """
        return []

    def on_disabled(self):
        """插件被禁用后的回调（运行时 Setting 门控，无需重启）。

        插件可在此回收外部资源配置（如把依赖该插件的全局设置重置为安全
        默认值）。异常不影响禁用流程本身。
        """

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
            mod = importlib.import_module(type(self).__module__)
            base = os.path.dirname(os.path.abspath(mod.__file__))
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

    def get_frontend_guard(self):
        """前台访问守卫钩子（v2.6.4）：返回 dict 或 None。

        插件需要引入「前台登录用户」概念（如会员插件）时实现，返回：
          {
            'is_authenticated': 无参可调用对象，返回当前访客是否已登录,
            'login_url':        无参可调用对象，返回登录页地址（可带 next）,
          }
        核心在前台导航构建、栏目/文章访问时调用：栏目标记 member_only
        且守卫存在、访客未登录时，导航隐藏该项、直接访问跳转登录页。
        没有任何启用插件提供守卫时，前台行为与旧版完全一致。
        """
        return None

    def get_sitemap_urls(self):
        """yield {'loc', 'lastmod', 'changefreq', 'priority'}（loc 为完整 URL）。"""
        return []

    def get_search_provider(self):
        """返回全站搜索内容提供者（v2.5.2）：SearchProvider 子类实例或 None。

        插件自有的前台公开内容（如产品、招聘职位）通过该提供者进入全站搜索：
        重建索引、保存时实时索引、索引故障/未建时的 SQL 兜底检索均自动覆盖。
        协议见 app/utils/search.py 的 SearchProvider。
        """
        return None

    def generate_demo_data(self, industry):
        """演示数据生成钩子（industry: manufacturing / service）。"""
