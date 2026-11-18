from flask import Blueprint, abort, g, request, session

# 后台主蓝本（需要登录鉴权）
admin_bp = Blueprint('admin', __name__, template_folder='templates')

# 登录鉴权蓝本（独立注册，便于控制登录路由无需鉴权）
admin_auth_bp = Blueprint('admin_auth', __name__, template_folder='templates')


# v3.2.2：平台级后台入口（与具体站点内容无关）。这些页面各自做权限校验，
# 站点守卫不应因会话站点被回收而 403，否则非超管无法进入/退出后台。
_PLATFORM_ENDPOINT_PREFIXES = (
    'admin.site_',            # 站点管理/切换（内部校验 site:manage）
    'admin.plugin_',          # 插件管理（安装/启停/删除）
    'admin.oss_storage_',     # 存储驱动全局配置
    'admin.db_migrator_',     # 数据库迁移工具
    'admin.auto_translate_',  # 翻译服务全局配置
    'admin.analytics_',       # 访问统计
    'admin.backup',           # 备份/恢复（内部要求平台级运维）
    'admin.setting_backup',   # 备份计划配置
    'admin.monitor',          # 系统监控
)
_PLATFORM_ENDPOINTS = frozenset({
    'admin.logout', 'admin.captcha',
})


def _is_platform_endpoint(endpoint):
    if not endpoint:
        return False
    if endpoint in _PLATFORM_ENDPOINTS:
        return True
    return any(endpoint.startswith(p) for p in _PLATFORM_ENDPOINT_PREFIXES)


@admin_bp.before_request
def _enforce_admin_site_access():
    """v3.2.1：后台统一站点授权守卫。

    `select_site()` 已解析出当前站点，这里对所有后台路由（含插件后台路由）
    统一校验站点权限，避免仅靠 `?site=` 解析层而漏掉内容入口。
      - 平台级入口（站点管理/插件/备份/存储等）直接放行；
      - 显式访问无权站点（?site=）→ 403；
      - 会话中的站点被回收 → GET 自动回退到第一个可访问站点；
      - 写请求遇到无权站点 → 403（不在错误站点执行写操作）。
    """
    from flask_login import current_user
    from ..sites import (
        SESSION_KEY, accessible_sites, can_access_site, current_site_id,
    )

    # 禁用/已删除账号交由登录装饰器登出，避免在此提前返回 403
    if (not current_user.is_authenticated
            or getattr(current_user, 'is_super', False)
            or not getattr(current_user, 'is_active_flag', True)
            or getattr(current_user, 'is_deleted', False)):
        return None

    if _is_platform_endpoint(request.endpoint):
        return None

    if getattr(g, '_site_access_denied', False):
        abort(403)

    sid = current_site_id()
    if can_access_site(current_user, sid):
        return None

    # 站点切换器自身允许访问（其内部已校验目标站点权限）
    if request.endpoint == 'admin.site_switch':
        return None

    if request.method == 'GET':
        allowed = accessible_sites(current_user)
        if allowed:
            g.current_site_id = allowed[0].id
            session[SESSION_KEY] = allowed[0].id
            return None
    abort(403)


# ---- 顶层模块（鉴权 / 首页 / 媒体 / 插件 / 二次确认）----
from . import auth  # noqa: E402,F401
from . import dashboard  # noqa: E402,F401
from . import upload  # noqa: E402,F401
from . import plugins  # noqa: E402,F401
from . import confirm  # noqa: E402,F401

# ---- v2.6.1：内容管理域（栏目 / 文章 / 碎片）----
from . import content  # noqa: E402,F401

# ---- v2.6.1：系统管理域（设置 / 用户 / 审计 / 备份 / 主题）----
from . import system  # noqa: E402,F401

# ---- v3.0.0：可视化页面构建器 ----
from . import builder  # noqa: E402,F401
