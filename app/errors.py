"""统一异常处理与全局异常捕获（v2.6.0）。

按请求上下文分发三种协议：
  - /api/ 前缀或 JSON 请求 → api_err JSON 响应
  - /admin/ 前缀 → 后台风格错误页
  - 其余 → 前台主题错误页（403/404/500）

取代此前分散在 frontend/views.py 的 app_errorhandler（仅 404/500，缺 403）。
"""
from http import HTTPStatus

from flask import (
    render_template, request,
)
from werkzeug.exceptions import HTTPException


def register_error_handlers(app):
    """在 create_app 中注册全局错误处理器。"""

    @app.errorhandler(400)
    def _400(e):
        return _handle(e, 400)

    @app.errorhandler(403)
    def _403(e):
        return _handle(e, 403)

    @app.errorhandler(404)
    def _404(e):
        return _handle(e, 404)

    @app.errorhandler(405)
    def _405(e):
        return _handle(e, 405)

    @app.errorhandler(500)
    def _500(e):
        return _handle(e, 500)

    @app.errorhandler(HTTPException)
    def _http_exception(e):
        # 兜底其他 HTTP 异常（如 401/406/413 等），复用同协议分发
        code = e.code or 500
        return _handle(e, code)

    @app.errorhandler(Exception)
    def _unhandled(e):
        # 非 HTTPException 的未知异常：记录堆栈后返回 500
        if app.debug:
            raise  # DEBUG 模式保留 Werkzeug 调试器
        app.logger.exception(
            'Unhandled exception: %s %s',
            request.method, request.path,
            exc_info=e,
        )
        return _handle(e, 500)


def _resolve_protocol():
    """判断当前请求应返回哪种协议：'api' / 'admin' / 'frontend'。"""
    path = request.path
    if path.startswith('/api/'):
        return 'api'
    # X-Requested-With: XMLHttpRequest 或 Accept: application/json
    accept = request.accept_mimetypes
    if (request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or accept.best == 'application/json'):
        return 'api'
    if path.startswith('/admin'):
        return 'admin'
    return 'frontend'


def _handle(e, code):
    """统一分发入口。"""
    protocol = _resolve_protocol()

    if protocol == 'api':
        return _handle_api(e, code)

    if protocol == 'admin':
        return _handle_admin(e, code)

    return _handle_frontend(e, code)


def _handle_api(e, code):
    """API JSON 错误响应。"""
    message = getattr(e, 'description', None) or HTTPStatus(code).phrase
    # 复用 api_err 的响应结构
    from .api.views import api_err
    return api_err(code, message, http=code)


def _handle_admin(e, code):
    """后台 HTML 错误页。"""
    description = getattr(e, 'description', None) or HTTPStatus(code).phrase
    # 后台错误模板目录：admin/errors/{code}.html
    template = f'admin/errors/{code}.html'
    try:
        return render_template(template, error_code=code,
                               error_description=description), code
    except Exception:
        # 模板不存在时回退到简单文本
        return (f'<h1>{code}</h1><p>{description}</p>',
                code, {'Content-Type': 'text/html; charset=utf-8'})


def _handle_frontend(e, code):
    """前台主题 HTML 错误页。"""
    # 前台 403/404/500 均有主题模板
    # 复用 frontend/views.py 的辅助函数构建上下文
    try:
        from .frontend.views import _build_nav, _seo
        from .utils.themes import theme_template
        nav = _build_nav()
        seo = _seo()
    except Exception:
        nav = []
        seo = {}

    description = getattr(e, 'description', None) or HTTPStatus(code).phrase

    # 403/404/500 有专用模板；其他码回退到 500 模板
    template_name = str(code) if code in (403, 404, 500) else '500'
    try:
        return render_template(theme_template(template_name),
                               nav=nav, seo=seo,
                               error_code=code,
                               error_description=description), code
    except Exception:
        # 主题模板缺失时回退到纯文本
        return (f'<h1>{code}</h1><p>{description}</p>',
                code, {'Content-Type': 'text/html; charset=utf-8'})
