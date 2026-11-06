"""外部 URL 安全校验（v3.1.8，GitCode issue #12 VULN-004 / VULN-005）。

所有「由配置驱动、服务端主动发起」的外发请求（Webhook、短信接口等）在发送前
必须经过本模块校验，防御 SSRF：
  - 协议白名单（默认仅 http/https）；
  - 可选域名白名单（hostname 精确匹配，杜绝子串绕过）；
  - 内网/回环/链路本地/保留 IP 黑名单（IPv4 + IPv6）。

注意：hostname 为域名时无法穷尽其解析结果，DNS 重绑定（域名先解析公网 IP 过检、
后切内网 IP）需结合出口防火墙兜底；本模块保证「配置值字面安全」。
"""
import ipaddress
from urllib.parse import urlparse


def assert_safe_external_url(url, allowed_hosts=None, allow_schemes=('https', 'http')):
    """校验外部 URL 安全性，不安全抛 ValueError，安全返回原 URL。

    参数：
      url:           待校验 URL 字符串
      allowed_hosts: 可选，hostname 白名单（集合/列表），精确匹配（小写）
      allow_schemes: 允许的 scheme 元组，默认 https/http
    """
    if not url or not isinstance(url, str):
        raise ValueError('URL 为空')
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in allow_schemes:
        raise ValueError('不允许的协议: {0}'.format(parsed.scheme or '(空)'))
    host = (parsed.hostname or '').lower()
    if not host:
        raise ValueError('URL 缺少主机名')
    if allowed_hosts is not None:
        allowed = {h.lower() for h in allowed_hosts}
        if host not in allowed:
            raise ValueError('域名不在白名单: {0}'.format(host))
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # 域名而非 IP 字面量：协议与白名单校验已通过
        return url
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        raise ValueError('目标为内网/保留地址: {0}'.format(ip))
    return url
