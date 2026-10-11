"""CSRF 同步 Token 防护（v3.1.1，GitCode issue #1 H2）。

机制：
  - 首次渲染页面时经 Jinja 全局函数 ``csrf_token()`` 生成随机 Token 并存入
    用户 Session（``_csrf_token``）；
  - 前后台所有 base 模板注入 ``<meta name="csrf-token">`` 与全局提交捕获
    脚本，表单提交时自动附加 ``_csrf_token`` 隐藏字段；
  - ``before_request`` 对 POST/PUT/PATCH/DELETE 请求做恒时比较校验，
    未携带或错误 → 403。

豁免：
  - /api/* REST 内容 API：以 X-API-Token / Bearer JWT 头鉴权，不依赖
    Cookie，无 CSRF 风险；
  - /healthz 健康检查；
  - Session 中尚无 Token 时（首个匿名 POST，如登录/初始化）：放行并
    借机把生成的 Token 写入 Session，后续请求开始强制校验。

注意：依赖 Session Cookie（登录后台/前台表单场景均成立）。
"""
import hmac
import secrets

from flask import abort, request, session


def generate_csrf_token():
    """取当前 Session 的 CSRF Token，没有则生成并写入。"""
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


def csrf_token():
    """Jinja 全局函数别名，模板中 {{ csrf_token() }} 使用。"""
    return generate_csrf_token()


def _csrf_skipped_path():
    path = request.path
    return path.startswith('/api/') or path.startswith('/healthz')


def validate_csrf():
    """before_request 钩子：状态变更请求强制校验 CSRF Token。"""
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
    if _csrf_skipped_path():
        return
    expected = session.get('_csrf_token')
    if not expected:
        # 首个匿名请求（尚未渲染过任何带 Token 的页面，如登录表单首次
        # 提交）：放行，同时生成 Token 供后续校验。
        generate_csrf_token()
        return
    provided = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token') or ''
    if not provided or not hmac.compare_digest(expected, provided):
        abort(403, description='CSRF 校验失败，请刷新页面重试')
