"""外部 URL 安全校验（v3.1.8，GitCode issue #12 VULN-004/005，SSRF 防护）。

规则：协议白名单 + 可选域名精确白名单 + 内网/保留 IP 黑名单。
v3.1.8 二次加固，封堵以下绕过：

- 非常规 IPv4 字面量：``socket.inet_aton`` 覆盖十进制（``2130706433``）、
  十六进制（``0x7f000001``）、八进制（``0177.0.0.1``）与段数省略
  （``127.1``）等 inet_aton 可解析的全部形式；
- IPv4-mapped IPv6：``::ffff:127.0.0.1`` 递归取其映射的 IPv4 再判定；
- DNS 重绑定：域名经 ``getaddrinfo`` 解析后逐条记录判定，任一解析到
  内网/保留地址即拒绝（解析失败 fail closed）。域名白名单精确命中的
  （如企业微信 webhook）跳过解析——攻击者无法控制白名单域名的 DNS 记录。

内网 IP 判定依据 ``ipaddress``：私有 / 回环 / 链路本地 / 保留 / 多播 /
未指定，另显式拒绝 0.0.0.0/8（"本网络"，is_private 各版本行为不一）。

注意：DNS 重绑定存在 TOCTOU 竞态（校验与请求之间 DNS 记录可能翻转），
彻底防御仍需出口防火墙兜底，见 SECURITY.md「安全配置基线」第 5 条。
"""
import ipaddress
import socket
from urllib.parse import urlparse

_THIS_NET = ipaddress.ip_network('0.0.0.0/8')


def _ip_is_forbidden(ip):
    """判定 IP 是否为内网/保留/不可路由地址（含 IPv4-mapped IPv6 递归）。"""
    mapped = getattr(ip, 'ipv4_mapped', None)
    if mapped is not None:
        ip = mapped
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified or ip in _THIS_NET
    )


def _resolve_host_ips(host, resolve_dns):
    """收集主机名对应的全部 IP（字面量 + 可选 DNS 解析）。

    resolve_dns=False 时仅识别 IP 字面量（含 inet_aton 非常规形式），
    域名不解析（用于白名单精确命中场景）。
    """
    ips = []
    # 1. 标准 IP 字面量（含 IPv6）
    try:
        ips.append(ipaddress.ip_address(host))
        return ips
    except ValueError:
        pass
    # 2. 非常规 IPv4 字面量：十进制 / 十六进制 / 八进制 / 段数省略
    try:
        packed = socket.inet_aton(host)
        ips.append(ipaddress.ip_address(packed))
        return ips
    except OSError:
        pass
    # 3. 域名：DNS 解析全部记录（防 DNS 重绑定）
    if resolve_dns:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as e:
            raise ValueError('域名解析失败，无法验证目标地址: {0}'.format(host)) from e
        for info in infos:
            try:
                ips.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
    return ips


def assert_safe_external_url(url, allowed_hosts=None, allow_schemes=('https', 'http')):
    """校验外部 URL 安全性：协议白名单 + 可选域名白名单 + 内网 IP 黑名单。

    校验通过返回原 URL，否则抛 ValueError。
    allowed_hosts 精确命中时跳过 DNS 解析检查（可信域名，见模块 docstring）。
    """
    parsed = urlparse(url)
    if parsed.scheme not in allow_schemes:
        raise ValueError(f'不允许的协议: {parsed.scheme}')
    host = parsed.hostname
    if not host:
        raise ValueError('缺少主机名')
    whitelisted = bool(allowed_hosts) and host in allowed_hosts
    if allowed_hosts and not whitelisted:
        raise ValueError(f'不在白名单: {host}')
    for ip in _resolve_host_ips(host, resolve_dns=not whitelisted):
        if _ip_is_forbidden(ip):
            raise ValueError(f'内网/保留地址: {ip}')
    return url
