"""站群模式（v3.2.0）站点解析层。

设计：完全镜像 `app/i18n.py` 的 `select_locale()` 范式——
每请求首调一次、结果缓存于 `g.current_site_id`、无上下文兜底默认站点 0。

解析优先级：
  后台请求：`?site=<slug|id>` → `session['admin_site_id']` → 默认 0
  前台请求：`?site=<slug|id>`（仅登录后台用户可临时切换）→
            Host 精确匹配 `sites.domain` → 子域首标签匹配 `sites.subdomain` → 默认 0
"""
import logging

from flask import g, has_app_context, has_request_context, request, session

from .models.site import DEFAULT_SITE_ID

logger = logging.getLogger(__name__)

# 后台「当前站点」会话键
SESSION_KEY = 'admin_site_id'


def _is_admin_request():
    try:
        bp = request.blueprint or ''
        return bp == 'admin' or bp == 'admin_auth' or bp.startswith('admin')
    except RuntimeError:
        # 无请求上下文（启动期/脚本）时视为非后台请求
        return False


def _site_rows():
    """请求级缓存：返回未删除站点列表（每请求最多一次查询）。"""
    if not has_app_context():
        return []
    rows = g.get('_sites_all')
    if rows is not None:
        return rows
    try:
        from .models.site import Site
        rows = Site.active_sites()
    except Exception as e:
        # 迁移/初始化未完成阶段不可用：按单站点（默认 0）处理
        logger.debug('站点列表读取失败，回退默认站点：%s', e)
        rows = []
    setattr(g, '_sites_all', rows)
    return rows


def _match_site(rows, ident):
    if ident is None:
        return None
    ident = str(ident).strip()
    if not ident:
        return None
    for s in rows:
        if s.slug == ident:
            return s
    try:
        sid = int(ident)
    except (TypeError, ValueError):
        return None
    for s in rows:
        if s.id == sid:
            return s
    return None


def _user_can_access(site_id):
    """当前登录用户是否可访问指定站点（未登录/校验异常按放行处理）。"""
    try:
        from flask_login import current_user
        if not current_user.is_authenticated:
            return True
        return can_access_site(current_user, site_id)
    except Exception as e:
        logger.debug('站点权限校验失败，按放行处理：%s', e)
        return True


def _first_accessible_site(rows):
    for s in rows:
        if _user_can_access(s.id):
            return s
    return None


def _resolve_site_id():
    rows = _site_rows()
    if not rows:
        return DEFAULT_SITE_ID
    default_id = DEFAULT_SITE_ID
    for s in rows:
        if s.is_default:
            default_id = s.id
            break

    admin = _is_admin_request()

    # ① 显式 ?site=（后台任意页面；前台仅登录用户，避免访客篡改会话）
    raw = request.args.get('site')
    if raw and (admin or session.get('_user_id')):
        site = _match_site(rows, raw)
        if site is not None:
            # v3.2.1：切换前校验站点权限，避免 ?site= 越权写会话
            if _user_can_access(site.id):
                session[SESSION_KEY] = site.id
                return site.id
            if admin:
                # 显式指定无权站点：标记越权，由 admin 守卫返回 403
                g._site_access_denied = True
            logger.warning('拒绝切换到无权站点：user=%s site=%s',
                           session.get('_user_id'), site.id)

    # ② 后台以 session 为准（权限被回收后自动回退到可访问站点）
    if admin:
        if getattr(g, '_site_access_denied', False):
            # 显式越权：不再写会话/回退，交由 admin 守卫返回 403
            return default_id
        sid = session.get(SESSION_KEY)
        for s in rows:
            if s.id == sid:
                if _user_can_access(s.id):
                    return s.id
                break
        if sid is not None:
            fallback = _first_accessible_site(rows)
            if fallback is not None:
                session[SESSION_KEY] = fallback.id
                return fallback.id
        return default_id

    # ③ Host 精确匹配
    host = (request.host or '').split(':', 1)[0].strip().lower()
    if host:
        for s in rows:
            if s.domain and s.domain.strip().lower() == host:
                return s.id
        # ④ 子域首标签匹配（泛解析：b.main.com → subdomain=b）
        labels = host.split('.')
        # v3.2.1：开发环境允许两段式 b.localhost
        dev_two_label = len(labels) == 2 and labels[1] == 'localhost'
        if len(labels) >= 3 or dev_two_label:
            sub = labels[0]
            for s in rows:
                if s.subdomain and s.subdomain.strip().lower() == sub:
                    return s.id

    return default_id


def select_site():
    """每请求首调：解析并缓存当前站点 id。注册于 app.before_request。

    注意：作为 before_request 必须返回 None（返回非 None 会被 Flask 当作响应）。
    """
    if not has_app_context():
        return None
    sid = getattr(g, 'current_site_id', None)
    if sid is not None:
        return None
    try:
        sid = _resolve_site_id()
    except Exception as e:
        logger.warning('站点解析失败，回退默认站点：%s', e)
        sid = DEFAULT_SITE_ID
    g.current_site_id = sid
    return None


def current_site_id():
    """当前站点 id（无请求上下文/未解析时返回默认站点 0）。"""
    if has_app_context():
        sid = getattr(g, 'current_site_id', None)
        if sid is not None:
            return sid
    return DEFAULT_SITE_ID


def set_current_site(site_id):
    """显式设置当前站点（后台切换器/测试使用）。"""
    if has_app_context():
        g.current_site_id = int(site_id)
    if has_request_context():
        session[SESSION_KEY] = int(site_id)


def invalidate_site_cache():
    """站点 CRUD 后失效请求级站点缓存。"""
    if has_app_context():
        g.pop('_sites_all', None)
        g.pop('current_site_id', None)
        for k in [k for k in g if str(k).startswith('_accessible_sites_')]:
            g.pop(k, None)


def current_site():
    """返回当前站点 ORM 对象（不存在时 None）。"""
    sid = current_site_id()
    try:
        from .models.site import Site
        rows = _site_rows()
        for s in rows:
            if s.id == sid:
                return s
        return Site.query.filter_by(id=sid, is_deleted=False).first()
    except Exception as e:
        logger.debug('当前站点读取失败：%s', e)
        return None


def site_url(site_id, endpoint='frontend.index', **values):
    """生成跨站点绝对 URL（站群互链/站点导航用）。

    优先使用 `sites.domain`；仅有 `subdomain` 时基于 `Setting.site_url`
    的主机名拼子域；两者都无则回退相对 URL。
    """
    from flask import url_for
    path = url_for(endpoint, **values)
    if not site_id:
        return path
    try:
        from .models.site import Site
        site = Site.query.filter_by(id=site_id, is_deleted=False).first()
    except Exception as e:
        logger.debug('站点 URL 生成失败：%s', e)
        return path
    if site is None:
        return path

    host = Site.normalize_host(site.domain)
    scheme = 'https' if (has_request_context() and request.is_secure) else 'http'
    if not host and site.subdomain:
        from urllib.parse import urlparse
        from .models.setting import Setting
        base = (Setting.get('site_url') or '').strip()
        parsed = urlparse(base)
        base_host = (parsed.netloc or parsed.path).split('/', 1)[0].split(':', 1)[0]
        sub = Site.normalize_host(site.subdomain)
        if base_host and sub:
            host = f'{sub}.{base_host}'
            scheme = parsed.scheme or scheme
    if not host:
        logger.debug('站点 %s 未配置 domain/subdomain，跨站 URL 回退相对路径', site.id)
        return path
    return f'{scheme}://{host}{path}'


def can_access_site(user, site_id):
    """判断后台用户是否可访问指定站点。

    规则（镜像 `can_access_column`）：
      - 超级管理员 / `site:manage` 权限：全站点；
      - 只读查看员：默认全站点可见；
      - 其他角色：需有 `UserSitePermission` 绑定行，或全局
        `content_manage:all_columns` 且无任何站点绑定（向后兼容）。
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_super', False):
        return True
    if user.has_permission('site:manage'):
        return True
    from .models.rbac import UserSitePermission, ROLE_READONLY_VIEWER
    try:
        rows = UserSitePermission.query.filter_by(user_id=user.id).all()
    except Exception as e:
        logger.debug('站点权限表不可用，按全局权限判定：%s', e)
        rows = []
    if any(r.site_id == site_id for r in rows):
        return True
    # 只读查看员默认全站点可见
    role_codes = {getattr(r.role, 'code', '') for r in (user.role_assignments or [])
                  if getattr(r, 'role', None) is not None}
    if ROLE_READONLY_VIEWER in role_codes:
        return True
    # v3.2.1 向后兼容：未做任何站点绑定 → 保持 v3.2.0 前的全站可见语义，
    # 避免升级后把存量编辑锁死（需要限制时在账号页勾选站点即可）。
    if not rows:
        return True
    return False


def accessible_sites(user):
    """返回用户可见站点列表（后台切换器数据源）。

    v3.2.1：站点列表与站点权限各查一次，内存过滤（消除 N+1）；
    结果缓存在请求级 g，站点/用户权限变更后由 invalidate_site_cache() 清理。
    """
    from .models.site import Site
    try:
        sites = Site.active_sites()
    except Exception as e:
        logger.debug('站点表不可用：%s', e)
        return []
    if user is None or not getattr(user, 'is_authenticated', False):
        return []
    if getattr(user, 'is_super', False) or user.has_permission('site:manage'):
        return sites

    cache_key = f'_accessible_sites_{getattr(user, "id", 0)}'
    if has_app_context():
        cached = g.get(cache_key)
        if cached is not None:
            return cached

    from .models.rbac import UserSitePermission, ROLE_READONLY_VIEWER
    try:
        rows = UserSitePermission.query.filter_by(user_id=user.id).all()
    except Exception as e:
        logger.debug('站点权限表不可用，按全站可见处理：%s', e)
        return sites
    role_codes = {getattr(r.role, 'code', '') for r in (user.role_assignments or [])
                  if getattr(r, 'role', None) is not None}
    if not rows or ROLE_READONLY_VIEWER in role_codes:
        # 未绑定任何站点（legacy）或只读查看员：全站可见
        result = sites
    else:
        allowed = {r.site_id for r in rows}
        result = [s for s in sites if s.id in allowed]
    if has_app_context():
        setattr(g, cache_key, result)
    return result
