"""Redis 协议后端识别（v3.3.0）。

openAMDC 与 Redis 协议同构，缓存/会话/限流共用 redis-py，业务侧无需分支。
本模块仅在运行态通过 ``INFO server`` 识别后端类型与版本，供健康检查与
后台设置页展示使用；识别失败返回 ``unknown``，不影响启动与业务。
"""


def _server_info(client):
    """读取 ``INFO server`` 段；兼容不支持 section 参数的客户端。"""
    try:
        info = client.info(section='server')
    except TypeError:
        info = client.info()
    return info if isinstance(info, dict) else {}


def describe(client):
    """返回 ``{'flavor': ..., 'version': ...}``。

    flavor 取值：``openamdc`` / ``redis`` / ``unknown``。
    openAMDC 的 ``INFO server`` 输出 ``openamdc_version`` 且没有
    ``redis_version``，因此优先匹配 openAMDC 字段。
    """
    try:
        info = _server_info(client)
    except Exception:
        return {'flavor': 'unknown', 'version': None}

    version = info.get('openamdc_version')
    if version:
        return {'flavor': 'openamdc', 'version': str(version)}

    version = info.get('redis_version')
    if version:
        return {'flavor': 'redis', 'version': str(version)}

    return {'flavor': 'unknown', 'version': None}


def detect_flavor(client):
    """只返回后端类型，便于调用方做分支展示。"""
    return describe(client)['flavor']
