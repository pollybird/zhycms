"""数据库查询工具（v3.1.9 VULN-010）。

用户输入直接拼进 ``LIKE`` 时，``%`` / ``_`` 会被当作通配符放大结果集，
``\\`` 则可能破坏转义语义。统一用 :func:`escape_like` 转义，并在查询处
显式传入 ``escape='\\\\'``。
"""

LIKE_ESCAPE = '\\'


def escape_like(value):
    """转义 LIKE 通配符。

    与 ``.like(pattern, escape=LIKE_ESCAPE)`` 配合使用。
    """
    if value is None:
        return ''
    return (str(value)
            .replace('\\', '\\\\')
            .replace('%', '\\%')
            .replace('_', '\\_'))
