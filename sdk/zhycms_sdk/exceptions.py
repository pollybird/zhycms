"""SDK 异常类型。"""


class ZhyCMSAPIError(Exception):
    """接口返回 ``code != 0`` 或 HTTP 层错误。

    status 为 HTTP 状态码（网络异常时为 0）；code 为响应包中的业务码
    （无响应包时与 HTTP 状态码一致）。
    """

    def __init__(self, status, code, message, payload=None):
        self.status = status
        self.code = code
        self.message = message
        self.payload = payload
        super().__init__(f'[{status}/{code}] {message}')
