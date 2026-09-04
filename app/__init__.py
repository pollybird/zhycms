import os
import re
from datetime import datetime

from flask import Flask, redirect, url_for, request, g
from flask_login import current_user

from .config import config
from .extensions import db, login_manager, cache, set_scheduler, babel, migrate
from .i18n import select_locale, available_locales, current_locale, _p


# ============================================================
# 后台路由「即时生效」机制：动态替换 Jinja url_for 生成前缀
# ============================================================

class _AdminPrefixAwareFlask(Flask):
    """覆写 Flask 的 create_url_adapter 与 jinja_env 初始化，使 url_for('admin.*')
    自动使用 admin_config.json 中最新前缀，不必重启服务。"""

    def create_url_adapter(self, request=None):
        adapter = super().create_url_adapter(request)
        return adapter

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_url_for = self.jinja_env.globals.get('url_for')
        # 等模型加载后再注入我们的包装 url_for
        self.before_first_request_funcs = []  # 避免新版弃用告警，使用 app_context_pushed


def _patch_jinja_url_for(app):
    """把 Jinja 全局的 url_for 对 admin / admin_auth endpoint 自动替换为最新前缀。"""
    from .utils.admin_prefix import load_admin_prefix

    original = app.jinja_env.globals.get('url_for') or url_for

    def patched_url_for(endpoint, **values):
        url = original(endpoint, **values)
        if endpoint and (endpoint.startswith('admin.') or endpoint.startswith('admin_auth.')):
            current_prefix = load_admin_prefix()
            # 匹配启动时注册的旧前缀，替换成当前配置中的前缀
            url = re.sub(r'^/(?:[a-zA-Z0-9_-]{2,32})/', f'/{current_prefix}/', url, count=1)
        return url

    # 只在第一次调用 url_for 时做前缀替换（懒替换）
    app.jinja_env.globals['url_for'] = patched_url_for

    # 同时 patch flask.url_for 在 Python 代码里的调用
    import flask as _flask
    _orig_build_url = _flask.url_for

    def python_url_for(endpoint, **values):
        url = _orig_build_url(endpoint, **values)
        if endpoint and (endpoint.startswith('admin.') or endpoint.startswith('admin_auth.')):
            current_prefix = load_admin_prefix()
            url = re.sub(r'^/(?:[a-zA-Z0-9_-]{2,32})/', f'/{current_prefix}/', url, count=1)
        return url

    # 不 patch 全局 flask.url_for（会影响其他 blueprint），而是提供工具函数 admin_url_for
    app.config['_patched_admin_url'] = True


def admin_url_for(endpoint, **values):
    """在 Python 视图代码中使用，生成带最新前缀的后台 URL。"""
    from flask import url_for as _url_for
    from .utils.admin_prefix import load_admin_prefix
    url = _url_for(endpoint, **values)
    if endpoint.startswith('admin.') or endpoint.startswith('admin_auth.'):
        current_prefix = load_admin_prefix()
        url = re.sub(r'^/(?:[a-zA-Z0-9_-]{2,32})/', f'/{current_prefix}/', url, count=1)
    return url


def _register_dynamic_admin_rules(app, target_prefix=None):
    """当后台 prefix 变更后：为新前缀补充 URL rule，并移除旧前缀 rule，使地址即时切换。

    规则：
    1. 找出「当前 url_map 下 admin.* / admin_auth.* 的 rule 所使用的前缀集合」；
       如果 target_prefix 已经存在，仍然会清理其他非 target 前缀。
    2. 把所有非 target_prefix 的 admin 规则移除，仅保留一个活动前缀；
       若目标前缀不是启动默认前缀，则新增目标前缀下的 rule（等价注册）。
    """
    from .utils.admin_prefix import load_admin_prefix, DEFAULT_PREFIX
    if target_prefix is None:
        target_prefix = load_admin_prefix()

    admin_rules = [
        r for r in list(app.url_map.iter_rules())
        if r.endpoint not in (None, 'static')
        and (r.endpoint.startswith('admin.') or r.endpoint.startswith('admin_auth.'))
    ]

    # 识别启动时（原始）前缀：取第一个合法目录段且为 admin rules 中最常见的目录段
    prefix_hist = {}
    for r in admin_rules:
        parts = r.rule.strip('/').split('/')
        if not parts:
            continue
        cand = parts[0]
        if cand and re.match(r'^[a-zA-Z0-9_-]{2,32}$', cand):
            prefix_hist[cand] = prefix_hist.get(cand, 0) + 1
    base_prefix = max(prefix_hist, key=prefix_hist.get) if prefix_hist else DEFAULT_PREFIX

    # 缓存基准前缀下的原始 rule：后续按 target_prefix 做等价重建时使用
    base_template_rules = [
        r for r in admin_rules
        if r.rule == f'/{base_prefix}' or r.rule.startswith(f'/{base_prefix}/')
    ]

    # 移除现有 prefix_hist 中**不等于 target_prefix** 的所有 admin rule（保证唯一性）
    active_prefixes = set(prefix_hist.keys())
    prefixes_to_remove = active_prefixes - {target_prefix}
    for r in list(admin_rules):
        parts = r.rule.strip('/').split('/')
        if not parts:
            continue
        head = parts[0]
        if head in prefixes_to_remove:
            try:
                app.url_map._rules.remove(r)
            except (ValueError, AttributeError):
                pass
            try:
                ep_rules = app.url_map._rules_by_endpoint.get(r.endpoint) or []
                if r in ep_rules:
                    ep_rules.remove(r)
            except (AttributeError, ValueError):
                pass
    # Werkzeug 3.x 的 StateMachineMatcher 会把 rule 编译为状态机，只靠 Map.update() 无法
    # 让 matcher 丢弃已删除 rule，必须显式重建 matcher。
    try:
        if hasattr(app.url_map, '_matcher'):
            merge_slashes = getattr(app.url_map, 'merge_slashes', True)
            if hasattr(app.url_map._matcher, 'add') and hasattr(app.url_map._matcher, 'update'):
                # 新建 matcher
                from werkzeug.routing.matcher import StateMachineMatcher
                app.url_map._matcher = StateMachineMatcher(merge_slashes=merge_slashes)
                for r in app.url_map._rules:
                    app.url_map._matcher.add(r)
    except Exception:
        pass
    # 标记 + 触发常规索引更新（_rules_by_endpoint 排序等）
    try:
        if hasattr(app.url_map, '_remap'):
            app.url_map._remap = True
        if hasattr(app.url_map, 'update'):
            app.url_map.update()
    except Exception:
        pass

    # 如果 target_prefix 就是基准前缀，无需 add（remove 已保留它）
    if target_prefix == base_prefix:
        return

    # 否则：基于缓存的基准前缀模板 rule(base_template_rules)，按 target_prefix 替换前缀后等价注册。
    # 注意：Flask 3 之后 app.add_url_rule 在处理首次请求后 AssertionError，
    # 因此直接用 Werkzeug Rule 构造后塞进 url_map._rules / _rules_by_endpoint，再统一 rebuild matcher。
    try:
        from werkzeug.routing import Rule as _WZRule
    except Exception:
        _WZRule = None

    new_rules_added = []
    existing_rules = {(rr.rule, frozenset(rr.methods or set()))
                      for rr in app.url_map.iter_rules()}
    for r in base_template_rules:
        if r.rule == f'/{base_prefix}':
            new_rule_path = f'/{target_prefix}'
        elif r.rule.startswith(f'/{base_prefix}/'):
            new_rule_path = f'/{target_prefix}' + r.rule[len(f'/{base_prefix}'):]
        else:
            continue
        methods = frozenset(r.methods or {'GET'})
        if (new_rule_path, methods) in existing_rules:
            continue

        try:
            if _WZRule is not None:
                # Werkzeug Rule 原生只接受少量参数（与 Flask App.add_url_rule 不同层）。
                # endpoint 已在构造时传入，且 url_map.add/append 会自动绑定。
                kwargs = {}
                if r.methods:
                    kwargs['methods'] = list(r.methods - {'HEAD', 'OPTIONS'})
                if r.defaults:
                    kwargs['defaults'] = dict(r.defaults)
                if r.strict_slashes is not None:
                    kwargs['strict_slashes'] = r.strict_slashes
                new_r = _WZRule(new_rule_path, endpoint=r.endpoint, **kwargs)
                # 必须先 bind 到 url_map，StateMachineMatcher 才会接受该 rule
                new_r.bind(app.url_map)
                app.url_map._rules.append(new_r)
                ep_list = app.url_map._rules_by_endpoint.setdefault(r.endpoint, [])
                ep_list.append(new_r)
                new_rules_added.append(new_r)
                existing_rules.add((new_rule_path, methods))
            else:
                app.add_url_rule(
                    new_rule_path,
                    endpoint=r.endpoint,
                    methods=list(r.methods - {'HEAD', 'OPTIONS'}) if r.methods else None,
                    defaults=r.defaults if hasattr(r, 'defaults') else None,
                    strict_slashes=r.strict_slashes,
                )
                existing_rules.add((new_rule_path, methods))
        except Exception as _e:
            app.logger.warning('register dynamic admin rule failed: %s endpoint=%s err=%s',
                               new_rule_path, r.endpoint, repr(_e))
            pass

    # 新增完毕后：重建 StateMachineMatcher + update 索引，保证新 rule 可匹配且可 url_for
    if new_rules_added:
        try:
            if hasattr(app.url_map, '_matcher'):
                merge_slashes = getattr(app.url_map, 'merge_slashes', True)
                if hasattr(app.url_map._matcher, 'add'):
                    from werkzeug.routing.matcher import StateMachineMatcher
                    app.url_map._matcher = StateMachineMatcher(merge_slashes=merge_slashes)
                    for _r in app.url_map._rules:
                        app.url_map._matcher.add(_r)
        except Exception:
            pass
        try:
            if hasattr(app.url_map, '_remap'):
                app.url_map._remap = True
            if hasattr(app.url_map, 'update'):
                app.url_map.update()
        except Exception:
            pass


# ============================================================
# 定时任务（模块4：自动备份 + 模块2：审计日志清理）
# ============================================================

def _setup_scheduler(app):
    """在单进程环境下启动 APScheduler（多进程请用外部 cron）。"""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        return None

    sched = BackgroundScheduler(daemon=True, timezone='Asia/Shanghai')

    # 任务1：定时自动备份
    def scheduled_backup_job():
        with app.app_context():
            from .utils.backup_utils import run_scheduled_backup
            try:
                run_scheduled_backup()
            except Exception:
                app.logger.exception('scheduled backup failed')

    # 任务2：清理过期审计日志 + 过期备份
    def cleanup_job():
        with app.app_context():
            from .models import AuditLog, BackupRecord, Setting
            try:
                keep = int(Setting.get('audit_log_keep_days', '90'))
                AuditLog.clean_expired(keep)
            except Exception:
                app.logger.exception('audit log cleanup failed')
            try:
                if Setting.get('backup_auto_clean') == 'on':
                    BackupRecord.cleanup_expired()
            except Exception:
                app.logger.exception('backup cleanup failed')

    # 每天 02:30 清理过期数据
    sched.add_job(cleanup_job, CronTrigger(hour=2, minute=30), id='zhycms_cleanup', replace_existing=True)
    # 备份任务在应用启动 + 每次设置保存时按配置 reschedule
    try:
        from .models import Setting
        mode = Setting.get('backup_schedule_mode', 'daily') or 'daily'
        time_str = Setting.get('backup_schedule_time', '03:00') or '03:00'
        hh, mm = 3, 0
        m = re.match(r'^(\d{1,2}):(\d{1,2})$', time_str)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
        if Setting.get('backup_enable_scheduled') == 'on':
            if mode == 'weekly':
                trig = CronTrigger(day_of_week='mon', hour=hh, minute=mm)
            else:
                trig = CronTrigger(hour=hh, minute=mm)
            sched.add_job(scheduled_backup_job, trig, id='zhycms_backup', replace_existing=True)
    except Exception:
        app.logger.exception('scheduled backup setup failed')

    # 只在 Werkzeug 主进程启动（非 reloader 子进程）时启动，避免双进程重复执行
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        try:
            sched.start()
        except Exception:
            return None
    set_scheduler(sched)
    return sched


# ============================================================
# v2.4.0：Alembic 迁移 bootstrap
# ============================================================

def _alembic_bootstrap(app):
    """在 create_app 的 app_context 内调用。
    检测数据库状态，执行 stamp 或 upgrade：
    - 新装（无核心表）：db.create_all() 已建表 → stamp baseline
    - 旧库（有核心表无 alembic_version）：stamp baseline → upgrade 增量
    - 已管理（有 alembic_version）：upgrade 增量
    """
    from sqlalchemy import inspect as sqla_inspect
    from flask_migrate import upgrade as flask_upgrade, stamp as flask_stamp

    engine = db.engine
    insp = sqla_inspect(engine)

    has_alembic = insp.has_table('alembic_version')
    has_users = insp.has_table('users')
    has_articles = insp.has_table('articles')

    if not has_users or not has_articles:
        # 全新安装：db.create_all() 已建全部表，仅 stamp baseline
        flask_stamp(directory='migrations', revision='0001')
        app.logger.info('[Alembic] 新装 stamp baseline 0001')
    elif not has_alembic:
        # v2.3.0 及更早旧库：stamp baseline 后执行增量
        flask_stamp(directory='migrations', revision='0001')
        app.logger.info('[Alembic] 旧库 stamp baseline 0001（v2.3.0 兼容）')
        flask_upgrade(directory='migrations')
        app.logger.info('[Alembic] 增量迁移完成')
    else:
        # 已纳入 Alembic 管理：执行增量
        flask_upgrade(directory='migrations')
        app.logger.info('[Alembic] 增量迁移完成')


# ============================================================
# 主入口
# ============================================================

def create_app(config_name=None):
    if config_name is None:
        # ZHOCMS_ 为 v2.1 前旧前缀（历史拼写差异），保留兼容回退
        config_name = (os.environ.get('ZHYCMS_ENV')
                       or os.environ.get('ZHOCMS_ENV', 'default'))

    app = _AdminPrefixAwareFlask(__name__, instance_relative_config=False)
    app.config.from_object(config[config_name])

    config[config_name].init_app(app)

    # 初始化扩展
    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)
    cache.init_app(app, config={
        'CACHE_TYPE': app.config.get('CACHE_TYPE', 'SimpleCache'),
        'CACHE_DEFAULT_TIMEOUT': app.config.get('CACHE_DEFAULT_TIMEOUT', 3600),
        'CACHE_DIR': app.config.get('CACHE_DIR'),
    })

    # v2.3.0 国际化：初始化 Babel 并注册 locale 选择器
    # （须在 db 之后：selector 内读 Setting；在蓝图注册之前）
    babel.init_app(app, locale_selector=select_locale)

    # 注册用户加载器
    from .models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    # 登录视图名：需要兼容自定义前缀，login_manager.login_view 使用 endpoint，故保持默认即可
    login_manager.login_view = 'admin_auth.login'
    from flask_babel import lazy_gettext
    login_manager.login_message = lazy_gettext('请先登录后再访问该页面')
    login_manager.login_message_category = 'warning'

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
            cms_version=Setting.CMS_VERSION,
        )

    # v2.2.0 插件菜单（启用 + 有权限才显示；后台模板使用）
    @app.context_processor
    def inject_plugin_menus():
        try:
            from .plugin_system import plugin_admin_menus
            return dict(plugin_admin_menus=plugin_admin_menus())
        except Exception:
            return dict(plugin_admin_menus=[])

    # 注册蓝本
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

    # 后台路由前缀：启动时注册一次
    admin_prefix = get_admin_url_prefix()
    app.register_blueprint(admin_auth_bp, url_prefix=admin_prefix)
    app.register_blueprint(admin_bp, url_prefix=admin_prefix)
    app.register_blueprint(frontend_bp)
    app.register_blueprint(content_api_bp, url_prefix='/api/v1')
    _register_cors(app)

    # 应用 url_for 动态前缀（模块5：路由修改即时生效）
    _patch_jinja_url_for(app)
    # 为当前 prefix 可能对应的老环境补充路由
    _register_dynamic_admin_rules(app)

    # 注册自定义过滤器
    from .utils.helpers import register_template_filters
    register_template_filters(app)

    # 把 admin_url_for 暴露给模板与 python 层
    app.jinja_env.globals['admin_url_for'] = admin_url_for
    # 模块8：前台列表分页 URL（伪静态 /{slug}-{N}.html 与动态 ?page=N 自动切换）
    from .frontend.views import frontend_pager_url
    app.jinja_env.globals['frontend_pager_url'] = frontend_pager_url

    # v2.3.0 国际化：注入切换器渲染函数与插件翻译 _p（_ 由 Flask-Babel 自动注入）
    app.jinja_env.globals['available_locales'] = available_locales
    app.jinja_env.globals['current_locale'] = current_locale
    app.jinja_env.globals['_p'] = _p

    # 初始化数据库表结构
    #
    # v2.4.0 兼容旧插件 db.create_all()：
    #   早期插件（banner/product/friend_link/form 等）在 v2.2/v2.3 时代通过
    #   enable_plugin() 调用 db.create_all() 建自己的模型表，启动期
    #   create_all 并没有把插件模型纳入 db.metadata。
    #   兼容策略：
    #     1) 先 discover_and_load(import_models_only=True)，把所有插件包的
    #        models.py 导入 db.metadata（仅导入模型，不做蓝图/路由注册）。
    #     2) 再 db.create_all()：核心表 + 插件模型表一次性补齐，Alembic
    #        bootstrap 之前 schema 已成型，不会出现「运行到一半某插件表
    #        不存在」的情况。
    #     3) 后续标准的 discover_and_load 注册蓝图、后台菜单等钩子——
    #        已导入的插件模块会被 Python import 缓存，不会重复导入。
    #     4) enable_plugin() 和 admin 初始化向导内的 db.create_all()
    #        仍保留作为二次兜底，对已经存在的表完全幂等。
    with app.app_context():
        from . import models  # noqa: F401  保证模型被导入
        from .plugin_system import discover_and_load
        discover_and_load(app, import_models_only=True)
        db.create_all()

        # ===== v2.4.0：Alembic 迁移 bootstrap =====
        # 新装：db.create_all() 已建全部表，stamp baseline
        # 旧库（v2.3.0 及更早）：检测已有核心表但无 alembic_version 表 → stamp
        # 然后执行增量迁移（0002 search_index 表、0003 搜索设置种子等）
        try:
            _alembic_bootstrap(app)
        except Exception as e:
            app.logger.warning('Alembic bootstrap 跳过（非致命）: %s', e)

        # ===== 幂等：初始化 RBAC 预设角色与权限 =====
        try:
            from .models.rbac import Role, Permission
            Permission.ensure_presets()
            Role.ensure_presets()
            db.session.commit()
        except Exception:
            db.session.rollback()

        # ===== 兼容旧 Article 数据：补 status 字段值 =====
        try:
            from .models.article import Article
            Article.ensure_status_column()
        except Exception:
            pass

        # ===== v2.2 升级兼容：老站点一次性自动启用内置友情链接插件 =====
        # 新装站点在初始化向导中写入 friend_link_plugin_migrated 标记，
        # 只有缺失该标记的已初始化站点（v2.1 及以前升级）才自动启用一次；
        # 表名/审计模块代码与核心版一致，老数据与历史审计无缝保留。
        try:
            from .models.setting import Setting
            from .plugin_system import enable_plugin
            if (User.query.filter_by(is_deleted=False).first() is not None
                    and not Setting.get('friend_link_plugin_migrated')):
                enable_plugin('friend_link')
                Setting.set('friend_link_plugin_migrated', '1')
                db.session.commit()
        except Exception:
            db.session.rollback()

        # ===== v2.3 升级兼容：老站点一次性自动启用内置表单插件 =====
        # 新装站点在初始化向导中写入 form_plugin_migrated 标记，避免误触发；
        # 仅已初始化站点（v2.2 及以前升级，缺本标记）才自动启用一次。
        # 表名/审计模块代码/后台路由路径/权限点与核心版完全一致，
        # 老站表单数据、提交记录与历史审计日志无缝保留。
        try:
            from .models.setting import Setting
            from .plugin_system import enable_plugin
            if (User.query.filter_by(is_deleted=False).first() is not None
                    and not Setting.get('form_plugin_migrated')):
                enable_plugin('form')
                Setting.set('form_plugin_migrated', '1')
                db.session.commit()
        except Exception:
            db.session.rollback()

        # ===== v2.4：oss_storage 对象存储插件一次性自动启用 =====
        # 启用后存储驱动仍为本地（storage_driver=local），不配置凭证不产生
        # 任何云端调用；仅为后台增加「对象存储」配置菜单。禁用插件会自动把
        # 存储驱动重置回本地。
        try:
            from .models.setting import Setting
            from .plugin_system import enable_plugin
            if (User.query.filter_by(is_deleted=False).first() is not None
                    and not Setting.get('oss_storage_plugin_seeded')):
                enable_plugin('oss_storage')
                Setting.set('oss_storage_plugin_seeded', '1')
                db.session.commit()
        except Exception:
            db.session.rollback()

    # 未初始化拦截：后台与前台除初始化页外，都跳转
    @app.before_request
    def _check_initialized():
        from sqlalchemy.exc import SQLAlchemyError

        # 允许访问静态资源、初始化路由与站点根文件（favicon/robots/sitemap）
        if request.endpoint in (
            'admin_auth.setup', 'admin_auth.captcha', 'static',
            'frontend.favicon', 'frontend.robots', 'frontend.sitemap',
            'frontend.captcha', 'frontend.healthz',
        ):
            return

        try:
            initialized = User.query.filter_by(is_deleted=False).first() is not None
        except SQLAlchemyError:
            initialized = False

        if not initialized:
            return redirect(url_for('admin_auth.setup'))

    # 后台请求路径分发：兼容修改后即时生效（若启动时 prefix=A，用户改为 prefix=B，补充 B 前缀的所有 rule）
    @app.before_request
    def _dispatch_dynamic_admin_prefix():
        from .utils.admin_prefix import load_admin_prefix
        target = load_admin_prefix()
        path = request.path.rstrip('/') or '/'
        if path.startswith(f'/{target}') or path == f'/{target}':
            # 若当前 prefix 的规则已存在（注册时或上次补充过），直接放行由 WSGI router 匹配
            return
        # 新前缀未注册规则：在此一次性补上
        _register_dynamic_admin_rules(app, target_prefix=target)

    # 调度器初始化（模块4 自动备份 + 清理）
    with app.app_context():
        try:
            _setup_scheduler(app)
        except Exception:
            app.logger.exception('scheduler init failed (non-fatal)')

    return app


__all__ = ['create_app', 'admin_url_for']
