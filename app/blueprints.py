"""蓝图注册与插件加载（v2.6.1 从 create_app 抽离）。

职责：
  1. 导入核心蓝图（admin / admin_auth / frontend / api）
  2. 加载插件（discover_and_load）
  3. 注册蓝图到 app
  4. 注册 CORS
  5. 注册统一异常处理（app/errors.py）
"""


def register_blueprints(app):
    """注册所有核心蓝图 + 加载插件 + 错误处理。

    在 create_app() 中调用，顺序固定：
      api 蓝本导入 → 插件加载 → admin/auth/frontend/api 蓝图注册 → CORS → 错误处理
    """
    # ---- 核心蓝图 ----
    from .admin import admin_bp, admin_auth_bp
    from .frontend import frontend_bp
    from .utils.admin_prefix import get_admin_url_prefix

    # v2.2.0 内容 API 蓝本（先于插件导入，插件可向其注册只读端点）
    from .api import api_bp as content_api_bp
    from .api.views import _register_cors

    # v2.2.0 插件机制：先于 admin_bp 注册前加载插件（插件向 admin_bp 追加路由，
    # 使其 endpoint 归入 admin.* 从而自动获得后台前缀即时生效机制）
    from .plugin_system import discover_and_load
    discover_and_load(app)

    # ---- 注册蓝图 ----
    admin_prefix = get_admin_url_prefix()
    app.register_blueprint(admin_auth_bp, url_prefix=admin_prefix)
    app.register_blueprint(admin_bp, url_prefix=admin_prefix)
    app.register_blueprint(frontend_bp)
    app.register_blueprint(content_api_bp, url_prefix='/api/v1')
    _register_cors(app)

    # ---- v2.6.0 统一异常处理 ----
    from .errors import register_error_handlers
    register_error_handlers(app)
