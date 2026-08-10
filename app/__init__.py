import os

from flask import Flask, redirect, url_for, request
from flask_login import current_user

from .config import config
from .extensions import db, login_manager


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('ZHOCMS_ENV', 'default')

    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config[config_name])

    config[config_name].init_app(app)

    # 初始化扩展
    db.init_app(app)
    login_manager.init_app(app)

    # 注册用户加载器
    from .models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    # 注入全局模板变量
    @app.context_processor
    def inject_globals():
        from .models.setting import Setting
        from .models.fragment import Fragment
        from .models.column import Column
        from .utils.themes import get_active_theme

        settings = Setting.get_dict()
        fragments = Fragment.get_dict()
        nav_columns = Column.get_tree(enabled_only=True)
        theme = get_active_theme()

        return dict(
            site_settings=settings,
            site_fragments=fragments,
            nav_columns=nav_columns,
            current_user=current_user,
            current_theme=theme,
            theme_base=f'themes/{theme}/base.html',
            # CMS 自身标识（后台使用，与前台企业名称/版权严格区分，固定不可改）
            cms_name=Setting.CMS_NAME,
            cms_copyright=Setting.CMS_COPYRIGHT,
        )

    # 注册蓝本
    from .admin import admin_bp, admin_auth_bp
    from .frontend import frontend_bp
    from .utils.admin_prefix import get_admin_url_prefix

    # 后台路由前缀可由管理员自定义（默认 /admin），修改后需重启生效
    admin_prefix = get_admin_url_prefix()
    app.register_blueprint(admin_auth_bp, url_prefix=admin_prefix)
    app.register_blueprint(admin_bp, url_prefix=admin_prefix)
    app.register_blueprint(frontend_bp)

    # 注册自定义过滤器
    from .utils.helpers import register_template_filters
    register_template_filters(app)

    # 初始化数据库表结构（不创建数据，首次访问由用户引导初始化）
    with app.app_context():
        from . import models  # noqa: F401  保证模型被导入
        db.create_all()

    # 未初始化拦截：后台与前台除初始化页外，都跳转
    @app.before_request
    def _check_initialized():
        from .models.user import User
        from sqlalchemy.exc import SQLAlchemyError

        # 允许访问静态资源、初始化路由与站点根文件（favicon/robots/sitemap）
        if request.endpoint in (
            'admin_auth.setup', 'admin_auth.captcha', 'static',
            'frontend.favicon', 'frontend.robots', 'frontend.sitemap',
        ):
            return

        try:
            initialized = User.query.filter_by(is_deleted=False).first() is not None
        except SQLAlchemyError:
            # 表不存在等情况：放行到 setup
            initialized = False

        if not initialized:
            return redirect(url_for('admin_auth.setup'))

    return app
