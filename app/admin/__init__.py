from flask import Blueprint, abort, g, request, session

# 后台主蓝本（需要登录鉴权）
admin_bp = Blueprint('admin', __name__, template_folder='templates')

# 登录鉴权蓝本（独立注册，便于控制登录路由无需鉴权）
admin_auth_bp = Blueprint('admin_auth', __name__, template_folder='templates')


@admin_bp.before_request
def _enforce_admin_site_access():
    """v3.2.1：后台统一站点授权守卫。

    `select_site()` 已解析出当前站点，这里对所有后台路由（含插件后台路由）
    统一校验站点权限，避免仅靠 `?site=` 解析层而漏掉内容入口。
      - 显式访问无权站点（?site=）→ 403；
      - 会话中的站点被回收 → GET 自动回退到第一个可访问站点；
      - 写请求遇到无权站点 → 403（不在错误站点执行写操作）。
    """
    from flask_login import current_user
    from ..sites import (
        SESSION_KEY, accessible_sites, can_access_site, current_site_id,
    )

    if not current_user.is_authenticated or getattr(current_user, 'is_super', False):
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
