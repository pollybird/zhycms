"""SDK HTTP 客户端：统一鉴权、响应包解析、刷新与重试策略。"""
from dataclasses import dataclass, field

import requests

from .exceptions import ZhyCMSAPIError

_UNSET = object()


@dataclass
class Page:
    """分页结果：items 为 data 列表，其余取自响应包 meta。"""
    items: list = field(default_factory=list)
    page: int = 1
    per_page: int = 0
    total: int = 0
    total_pages: int = 0

    @classmethod
    def from_payload(cls, payload):
        meta = payload.get('meta') or {}
        return cls(
            items=list(payload.get('data') or []),
            page=int(meta.get('page', 1) or 1),
            per_page=int(meta.get('per_page', 0) or 0),
            total=int(meta.get('total', 0) or 0),
            total_pages=int(meta.get('total_pages', 0) or 0),
        )


class Client:
    """ZhyCMS API 客户端。

    :param base_url: 站点根地址（如 ``https://example.com``）
    :param token: access token；也可稍后调用 ``login()``
    :param refresh_token: refresh token，用于 access token 过期后自动续期
    :param timeout: 单次请求超时秒数
    :param session: 可注入兼容 requests 的会话对象（测试用）
    :param max_retries: GET 请求遇到网络错误/5xx 时的额外重试次数（写请求不重试）
    """

    def __init__(self, base_url, *, token=None, refresh_token=None,
                 timeout=10, session=None, max_retries=1):
        self.base_url = str(base_url).rstrip('/')
        self.token = token
        self.refresh_token = refresh_token
        self.timeout = timeout
        self.session = session or requests.Session()
        self.max_retries = max(0, int(max_retries))
        self.content = None
        self.forms = None
        self.sites = None
        self._bind()

    def _bind(self):
        from .content import ContentClient
        from .forms import FormClient
        from .sites import SiteClient
        self.content = ContentClient(self)
        self.forms = FormClient(self)
        self.sites = SiteClient(self)

    # ---------- 底层请求 ----------

    def _send(self, method, url, *, params=None, json=None, token=_UNSET):
        headers = {'Accept': 'application/json'}
        use_token = self.token if token is _UNSET else token
        if use_token:
            headers['Authorization'] = f'Bearer {use_token}'
        kwargs = {'headers': headers, 'timeout': self.timeout}
        if params:
            kwargs['params'] = params
        if json is not None:
            kwargs['json'] = json
        return self.session.request(method, url, **kwargs)

    @staticmethod
    def _payload(resp):
        try:
            payload = resp.json()
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    def _raise_http(self, resp, payload):
        code = payload.get('code') if payload else resp.status_code
        message = (payload or {}).get('message') or getattr(resp, 'text', '') or 'HTTP 错误'
        raise ZhyCMSAPIError(resp.status_code, code, message, payload)

    def request(self, method, path, *, params=None, json=None, _retry_auth=True):
        """发送请求并返回完整响应包（dict），code != 0 时抛异常。"""
        method = method.upper()
        url = self.base_url + path
        attempts = 1 + (self.max_retries if method == 'GET' else 0)

        for attempt in range(attempts):
            try:
                resp = self._send(method, url, params=params, json=json)
            except requests.RequestException as exc:
                if attempt + 1 < attempts:
                    continue
                raise ZhyCMSAPIError(0, 0, f'网络请求失败：{exc}') from exc

            if resp.status_code == 401 and _retry_auth and self.refresh_token:
                # 401 表示请求未被受理，刷新后重放一次是安全的
                self.refresh()
                return self.request(method, path, params=params, json=json,
                                    _retry_auth=False)

            payload = self._payload(resp)
            if payload is None:
                if resp.status_code >= 500 and attempt + 1 < attempts:
                    continue
                self._raise_http(resp, None)
            if payload.get('code') != 0:
                self._raise_http(resp, payload)
            return payload

        raise ZhyCMSAPIError(0, 0, '请求失败')

    def get(self, path, params=None):
        return self.request('GET', path, params=params)

    def post(self, path, json=None):
        return self.request('POST', path, json=json)

    def put(self, path, json=None):
        return self.request('PUT', path, json=json)

    def delete(self, path):
        return self.request('DELETE', path)

    # ---------- 鉴权 ----------

    def login(self, username, password):
        """用户名密码登录，成功后保存 access / refresh token。"""
        payload = self.request('POST', '/api/v1/auth/login',
                               json={'username': username, 'password': password},
                               _retry_auth=False)
        data = payload.get('data') or {}
        self.token = data.get('access_token')
        self.refresh_token = data.get('refresh_token')
        return data

    def refresh(self):
        """用 refresh token 换取新的 access token。"""
        if not self.refresh_token:
            raise ZhyCMSAPIError(401, 401, '缺少 refresh token')
        resp = self._send('POST', self.base_url + '/api/v1/auth/refresh',
                          token=self.refresh_token)
        payload = self._payload(resp)
        if payload is None or payload.get('code') != 0:
            self._raise_http(resp, payload)
        self.token = (payload.get('data') or {}).get('access_token')
        return self.token

    def logout(self):
        """登出并清空本地 token。"""
        try:
            if self.token:
                self.request('POST', '/api/v1/auth/logout')
        finally:
            self.token = None
            self.refresh_token = None
