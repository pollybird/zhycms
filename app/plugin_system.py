"""插件系统运行时（v2.2.0）：发现、加载、注册、启停门控。

机制概要（详见 DESIGN-v2.2.0.md §2.3）：
  - 启动时全量导入 plugins/ 下所有插件并注册（蓝图/模板全局/菜单/API/sitemap 钩子），
    单个插件导入失败仅记录错误并在管理页标红，不拖垮启动；
  - 运行时以 site_settings.enabled_plugins（逗号分隔 slug）门控，
    启停只改设置值，即时生效、无需重启、天然兼容多 worker；
  - 启用动作幂等：种子权限点 → 预设角色补授权 → db.create_all() 兜底建表。
"""
import os
import json
import importlib

from flask import g, has_app_context

from .plugin_api import PluginBase  # noqa: F401  供类型提示与外部 import

# 插件根目录（项目根 plugins/）
PLUGINS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'plugins'
)

SETTING_KEY = 'enabled_plugins'


# ============================================================
# 插件记录与注册表
# ============================================================

class PluginRecord:
    """单个插件的运行期记录。"""

    def __init__(self, slug):
        self.slug = slug
        self.manifest = {}          # manifest.json 内容
        self.instance = None        # PluginBase 实例
        self.error = None           # 导入/注册失败原因
        self.module = None

    @property
    def name(self):
        return (self.instance.name if self.instance else '') \
            or self.manifest.get('name', self.slug)

    @property
    def version(self):
        return (self.instance.version if self.instance else '') \
            or self.manifest.get('version', '')

    @property
    def description(self):
        return (self.instance.description if self.instance else '') \
            or self.manifest.get('description', '')

    @property
    def author(self):
        return (self.instance.author if self.instance else '') \
            or self.manifest.get('author', '')

    @property
    def loaded(self):
        return self.instance is not None


_registry = []   # [PluginRecord]
_by_slug = {}


def _record(slug):
    rec = _by_slug.get(slug)
    if rec is None:
        rec = PluginRecord(slug)
        _by_slug[slug] = rec
        _registry.append(rec)
    return rec


# ============================================================
# 启用清单（site_settings.enabled_plugins）
# ============================================================

def enabled_slugs():
    """读取当前启用插件 slug 集合。"""
    from .models.setting import Setting
    raw = Setting.get(SETTING_KEY, '') or ''
    return {s.strip() for s in raw.split(',') if s.strip()}


def set_enabled_slugs(slugs):
    """写入启用清单（不去校验存在性，调用方负责）。"""
    from .models.setting import Setting
    from .extensions import db
    Setting.set(SETTING_KEY, ','.join(sorted(set(slugs))))
    db.session.commit()
    # 清理请求级缓存
    if has_app_context():
        g.pop('_plugin_enabled_slugs', None)


def plugin_enabled(slug):
    """插件启用守卫（请求级 memo）。"""
    if not has_app_context():
        return False
    try:
        slugs = g.get('_plugin_enabled_slugs')
        if slugs is None:
            slugs = enabled_slugs()
            g._plugin_enabled_slugs = slugs
        return slug in slugs
    except Exception:
        return False


# ============================================================
# 发现与加载
# ============================================================

def discover():
    """扫描 plugins/ 目录，读取 manifest（不导入代码）。"""
    if not os.path.isdir(PLUGINS_DIR):
        return
    for entry in sorted(os.listdir(PLUGINS_DIR)):
        pkg_dir = os.path.join(PLUGINS_DIR, entry)
        manifest_path = os.path.join(pkg_dir, 'manifest.json')
        if not os.path.isdir(pkg_dir) or not os.path.isfile(manifest_path):
            continue
        rec = _record(entry)
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                rec.manifest = json.load(f)
        except Exception:
            rec.manifest = {}


def _guarded_global(record, fn, fallback):
    """把插件模板全局函数包上「插件启用」守卫：未启用返回安全空值，模板不崩。"""
    def wrapper(*args, **kwargs):
        if not plugin_enabled(record.slug):
            return fallback
        return fn(*args, **kwargs)
    wrapper.__name__ = getattr(fn, '__name__', 'plugin_global')
    wrapper.__doc__ = getattr(fn, '__doc__', '')
    return wrapper


def _register_instance(app, rec):
    """把插件实例的各钩子注册到应用。"""
    from .admin import admin_bp  # 核心后台蓝本（此时还未 register_blueprint）

    inst = rec.instance

    # 0) v2.3.0 插件国际化：如插件提供 translations/ 目录，则登记 slug 的翻译域
    try:
        i18n_dir = inst.get_i18n_dir() if hasattr(inst, 'get_i18n_dir') else None
        if i18n_dir and os.path.isdir(i18n_dir):
            from .i18n import register_plugin_i18n
            register_plugin_i18n(rec.slug, i18n_dir, domain='messages')
    except Exception:
        pass  # 单个插件 i18n 注册失败不拖垮整体

    # 1) 后台路由（挂在核心 admin_bp 上，endpoint 自动获得前缀即时生效机制）
    inst.get_admin_routes(admin_bp)

    # 2) 前台蓝本（模板 + 静态资源）
    fbp = inst.get_frontend_blueprint()
    if fbp is not None:
        app.register_blueprint(fbp)

    # 3) 模板全局函数（包裹启用守卫）
    fallbacks = inst.get_jinja_fallbacks() or {}
    for name, fn in (inst.get_jinja_globals() or {}).items():
        app.jinja_env.globals[name] = _guarded_global(rec, fn, fallbacks.get(name))

    # 4) 内容 API 端点（api_bp 已先于插件注册到 app）
    try:
        from .api import api_bp
        inst.get_api_routes(api_bp)
    except ImportError:
        pass

    # 5) v2.4.0 存储驱动（oss_storage 插件注册云端 OSS 驱动）
    try:
        from .utils import storage as _storage
        for drv_cls in (inst.get_storage_drivers() or []):
            _storage.register_driver(drv_cls)
    except Exception as e:
        app.logger.warning('插件 %s 存储驱动注册失败： %s', rec.slug, e)


def _import_plugin_models_recursive(base_module):
    """把插件包内的模型模块导入 metadata（仅用于 db.create_all()
    兜底建表，不做注册）。失败不影响启动，由 enable_plugin 再兜底。"""
    import pkgutil
    try:
        pkg_path = base_module.__path__
    except AttributeError:
        return
    for _finder, modname, ispkg in pkgutil.walk_packages(pkg_path, prefix=f'{base_module.__name__}.'):
        if ispkg or not modname.endswith('.models'):
            continue
        try:
            importlib.import_module(modname)
        except Exception:
            pass


def discover_and_load(app, import_models_only=False):
    """入口：扫描并导入全部插件，注册各钩子。在 create_app 中调用（须在
    register_blueprint(admin_bp) 之前、api 蓝本导入之后）。

    v2.4.0 兼容旧插件 db.create_all()：启动期 **先** 导入所有插件模型
    进入 ``db.metadata``，再 ``db.create_all()`` 建表；**之后** 才在
    ``enable_plugin()`` 再次执行 db.create_all() 幂等兜底；同时 Alembic
    迁移执行时也能看到插件模型表，避免 metadata 与 schema 不一致导致
    下一次 ``autogenerate`` 误报 DROP。

    :param import_models_only: 仅扫描并导入插件模型（建表/metadata 对齐
        用，不注册任何运行期钩子），用于启动期 pre-seed 场景。
    """
    discover()
    for rec in list(_registry):
        if import_models_only:
            # 仅导入插件包（触发顶层 import）并递归导入 models 子模块
            try:
                module = importlib.import_module(f'plugins.{rec.slug}')
                rec.module = module
            except Exception as e:
                rec.error = f'{type(e).__name__}: {e}'
                app.logger.warning('插件 %s 预加载模型失败（不影响启动）： %s',
                                   rec.slug, e)
                continue
            _import_plugin_models_recursive(module)
            continue
        if rec.loaded:
            continue
        try:
            module = importlib.import_module(f'plugins.{rec.slug}')
            rec.module = module
            inst = getattr(module, 'plugin', None)
            if inst is None and hasattr(module, 'Plugin'):
                inst = module.Plugin()
            if not isinstance(inst, PluginBase):
                raise RuntimeError('插件缺少 plugin 实例（须为 PluginBase 子类）')
            rec.instance = inst
            _register_instance(app, rec)
        except Exception as e:  # 单插件失败不影响整体启动
            rec.error = f'{type(e).__name__}: {e}'
            import traceback
            app.logger.error('插件 %s 加载失败： %s\n%s',
                             rec.slug, e, traceback.format_exc())


# ============================================================
# 启停服务（插件管理页调用）
# ============================================================

def get_record(slug):
    return _by_slug.get(slug)


def get_plugin_records():
    """插件管理页数据：[{slug,name,version,description,author,enabled,error,menu}]"""
    current = enabled_slugs()
    result = []
    for rec in _registry:
        menu = []
        if rec.instance is not None:
            try:
                menu = rec.instance.get_admin_menu() or []
            except Exception:
                menu = []
        result.append({
            'slug': rec.slug,
            'name': rec.name,
            'version': rec.version,
            'description': rec.description,
            'author': rec.author,
            'enabled': rec.slug in current,
            'error': rec.error,
            'loaded': rec.loaded,
            'builtin': bool(rec.manifest.get('builtin')),
            'menu': menu,
            'permissions': getattr(rec.instance, 'permissions', []) if rec.instance else [],
        })
    return result


def _seed_plugin_permissions(inst):
    """幂等种子权限点 + 预设角色补授权。"""
    from .extensions import db
    from .models.rbac import Permission, Role, RolePermission

    for code, label, desc in (inst.permissions or []):
        item = Permission.query.filter_by(code=code).first()
        if item is None:
            group = code.split(':', 1)[0] if ':' in code else ''
            db.session.add(Permission(code=code, name=label, description=desc, group=group))
    db.session.flush()

    for role_code, perm_codes in (inst.preset_role_grants or {}).items():
        role = Role.query.filter_by(code=role_code).first()
        if role is None:
            continue
        for pc in perm_codes:
            exists = RolePermission.query.filter_by(
                role_id=role.id, permission_code=pc).first()
            if exists is None:
                db.session.add(RolePermission(role_id=role.id, permission_code=pc))
    db.session.commit()


def enable_plugin(slug):
    """启用插件：种子权限 + 兜底建表 + 写启用清单。返回错误信息或 None。"""
    rec = _by_slug.get(slug)
    if rec is None:
        return f'插件 {slug} 不存在'
    if not rec.loaded:
        return f'插件 {slug} 加载失败，无法启用：{rec.error or "未知原因"}'
    try:
        from .extensions import db
        _seed_plugin_permissions(rec.instance)
        db.create_all()  # 插件模型已随导入进入 metadata，幂等
    except Exception as e:
        from .extensions import db
        db.session.rollback()
        return f'启用失败：{e}'
    slugs = enabled_slugs()
    slugs.add(slug)
    set_enabled_slugs(slugs)
    return None


def disable_plugin(slug):
    """禁用插件：仅移出启用清单（不删表、不清数据、不回收权限绑定）。

    禁用后调用插件 ``on_disabled()`` 回调（如 oss_storage 会把存储驱动
    重置为本地，防止新上传指向已不可用的云端配置）；回调异常不影响禁用。
    """
    slugs = enabled_slugs()
    slugs.discard(slug)
    set_enabled_slugs(slugs)
    rec = _by_slug.get(slug)
    if rec is not None and rec.instance is not None:
        try:
            rec.instance.on_disabled()
        except Exception:
            pass


def remove_record(slug):
    """卸载插件后从运行期注册表移除记录（列表/菜单/聚合钩子立即消失），
    并清理 sys.modules 缓存，便于同进程内重新上传同名插件。"""
    import sys
    rec = _by_slug.pop(slug, None)
    if rec is not None:
        try:
            _registry.remove(rec)
        except ValueError:
            pass
    prefix = f'plugins.{slug}'
    for key in [k for k in sys.modules
                if k == prefix or k.startswith(prefix + '.')]:
        sys.modules.pop(key, None)
    return rec is not None


# ============================================================
# 聚合钩子（菜单 / 审计模块 / sitemap / 演示数据）
# ============================================================

def plugin_admin_menus():
    """后台侧边栏数据：启用插件（当前用户有权限的）的菜单项。
    返回 [{'slug','name','icon','items':[{'label','endpoint','permission','active_prefix'}]}]
    """
    from flask_login import current_user

    current = enabled_slugs()
    result = []
    for rec in _registry:
        if rec.slug not in current or rec.instance is None:
            continue
        try:
            items = rec.instance.get_admin_menu() or []
        except Exception:
            items = []
        visible = []
        for item in items:
            perm = item.get('permission')
            if perm and not (getattr(current_user, 'is_super', False)
                             or (current_user.is_authenticated
                                 and current_user.has_permission(perm))):
                continue
            _label = item.get('label') or ''
            if isinstance(_label, str) and _label:
                # v2.3.0：插件菜单 label 走插件翻译域（插件没 translations/ 时 fallback 原文）
                try:
                    from .i18n import plugin_gettext
                    _label = plugin_gettext(rec.slug, _label)
                except Exception:
                    pass
                try:
                    from flask_babel import gettext as _g
                    # 再查一次核心域（避免中文 label 实际来自 plugins/admin.py 视图变量）
                    # 只有插件翻译不命中（=原文）时再看核心，不重复翻译英文串
                    import re as _re
                    if _label and _re.search(r'[\u3400-\u9fff]', _label):
                        _core = _g(_label)
                        if _core and _core != _label:
                            _label = _core
                except Exception:
                    pass
            item = dict(item)
            item['label'] = _label
            visible.append(item)
        if visible:
            icon = (rec.instance.get_admin_menu_icon()
                    if hasattr(rec.instance, 'get_admin_menu_icon') else None) \
                or 'fa-plug'
            # v2.3.0：插件分组名（name）也翻译：先查插件翻译域，再回退核心域
            _name = rec.name
            if isinstance(_name, str) and _name:
                import re as _re2
                try:
                    from .i18n import plugin_gettext as _pg2
                    _name = _pg2(rec.slug, _name)
                except Exception:
                    pass
                try:
                    from flask_babel import gettext as _g2
                    if _re2.search(r'[\u3400-\u9fff]', _name):
                        _c2 = _g2(_name)
                        if _c2 and _c2 != _name:
                            _name = _c2
                except Exception:
                    pass
            result.append({'slug': rec.slug, 'name': _name,
                           'icon': icon, 'items': visible})
    return result


def plugin_audit_modules():
    """审计页筛选下拉聚合：启用插件的 [(module_code, label)]。"""
    current = enabled_slugs()
    mods = []
    for rec in _registry:
        if rec.slug not in current or rec.instance is None:
            continue
        try:
            mods.extend(rec.instance.audit_modules or [])
        except Exception:
            pass
    return mods


def plugin_frontend_menus():
    """前台导航聚合（v2.2.0）：启用插件贡献的菜单项。
    返回 [{'label', 'url', 'target'}, ...]，单个插件异常静默跳过。
    """
    current = enabled_slugs()
    items = []
    for rec in _registry:
        if rec.slug not in current or rec.instance is None:
            continue
        try:
            for m in (rec.instance.get_frontend_menu() or []):
                if not isinstance(m, dict):
                    continue
                label = (m.get('label') or '').strip()
                url = (m.get('url') or '').strip()
                if label and url:
                    items.append({
                        'label': label, 'url': url,
                        'target': (m.get('target') or '').strip(),
                    })
        except Exception:
            pass
    return items


def collect_sitemap_urls():
    """sitemap.xml 聚合：启用插件贡献的 URL。"""
    current = enabled_slugs()
    urls = []
    for rec in _registry:
        if rec.slug not in current or rec.instance is None:
            continue
        try:
            urls.extend(rec.instance.get_sitemap_urls() or [])
        except Exception:
            pass
    return urls


def run_demo_data_hooks(industry):
    """演示数据生成：调用启用插件的 demo_data 钩子。返回 [(slug, error)]。"""
    current = enabled_slugs()
    errors = []
    for rec in _registry:
        if rec.slug not in current or rec.instance is None:
            continue
        try:
            rec.instance.generate_demo_data(industry)
        except Exception as e:
            errors.append((rec.slug, f'{type(e).__name__}: {e}'))
    return errors
