"""站点部署配置渲染：把站点元数据转换成 nginx server 配置。

后台「部署指南」与 `scripts/generate_nginx_sites.py` 共用本模块，保证两处
输出逐字一致；渲染只读取传入的站点对象，不查询数据库、不修改服务器配置。
"""
import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy.exc import SQLAlchemyError

from ..models.site import Site

logger = logging.getLogger(__name__)

DEFAULT_UPSTREAM = '127.0.0.1:5000'
DEFAULT_UPLOAD_MAX_MB = 10
SUBDOMAIN_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')


def normalize_base_domain(value):
    """规范化泛解析基础域名；兼容 `https://example.com` 形式的站点网址。"""
    raw = str(value or '').strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    host = (parsed.netloc or parsed.path).split('/', 1)[0].split(':', 1)[0]
    host = Site.normalize_host(host)
    if not host or not Site.is_valid_domain(host):
        return None
    return host


def is_default_site(site):
    """默认站点判定：is_default=True 或主键为 0。"""
    return bool(getattr(site, 'is_default', False)) or getattr(site, 'id', None) == 0


def _own_domains(site):
    """站点自身独立域名（主域名 + 附加域名），非法值跳过。"""
    values = []
    sites = [getattr(site, 'domain', None)]
    for row in (getattr(site, 'domain_entries', None) or []):
        # 兼容 ORM 行对象与测试里的纯字符串
        values.append(getattr(row, 'domain', row))
    sites.extend(values)
    result = []
    for raw in sites:
        domain = Site.normalize_host(raw)
        if not domain:
            continue
        if not Site.is_valid_domain(domain):
            logger.warning('站点 %s 的域名不合法，已跳过：%r',
                           getattr(site, 'id', '?'), domain)
            continue
        if domain not in result:
            result.append(domain)
    return result


def site_hostnames(site, base_domain=None):
    """返回站点可用于 server_name 的主机名列表（v3.3.4）。

    - 主域名 + 附加域名（通过 DNS label 校验）→ 精确域名；
    - `subdomain` 存在时，为每个自身域名补 `{subdomain}.{域名}`，
      并兼容旧的 `{subdomain}.{base_domain}`（泛解析基础域）；
    - 非法值跳过并记录 warning，绝不原样写入 nginx 配置。
    """
    own = _own_domains(site)
    hosts = list(own)

    subdomain = Site.normalize_host(getattr(site, 'subdomain', None))
    if subdomain and SUBDOMAIN_RE.match(subdomain):
        for domain in own:
            sub_host = f'{subdomain}.{domain}'
            if sub_host not in hosts:
                hosts.append(sub_host)
        base = normalize_base_domain(base_domain)
        if base:
            sub_host = f'{subdomain}.{base}'
            if sub_host not in hosts:
                hosts.append(sub_host)
    return hosts


def _log_paths(site_id):
    return (
        f'/var/log/nginx/zhycms-site{site_id}.access.log',
        f'/var/log/nginx/zhycms-site{site_id}.error.log',
    )


_UPSTREAM_RE = re.compile(r'^[A-Za-z0-9.\-\[\]:]+$')


def normalize_upstreams(upstreams):
    """清洗多实例后端地址；非法片段直接丢弃。"""
    cleaned = []
    for raw in upstreams or []:
        item = str(raw or '').strip()
        if item and _UPSTREAM_RE.match(item) and item not in cleaned:
            cleaned.append(item)
    return cleaned


def render_upstream_block(upstreams):
    """生成多实例 upstream 块；少于两个地址时返回空字符串。"""
    cleaned = normalize_upstreams(upstreams)
    if len(cleaned) < 2:
        return ''
    servers = '\n'.join(f'    server {item};' for item in cleaned)
    return (
        '# zhycms 多实例后端（由站点部署脚本生成）\n'
        'upstream zhycms_backend {\n'
        f'{servers}\n'
        '    keepalive 32;\n'
        '}'
    )


def resolve_upstream(upstream=None, upstreams=None):
    """多实例时返回 upstream 组名，否则返回单个后端地址。"""
    cleaned = normalize_upstreams(upstreams)
    if len(cleaned) > 1:
        return 'zhycms_backend'
    if cleaned:
        return cleaned[0]
    return upstream or DEFAULT_UPSTREAM


def _proxy_location(upstream):
    return f"""    location / {{
        proxy_pass http://{upstream};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }}"""


def _server_body(server_names, site_id, upstream, upload_max_mb, ssl_cert=None):
    """生成 server 块内部公共行（listen/server_name 由调用方提供）。"""
    access_log, error_log = _log_paths(site_id)
    lines = [
        f'    server_name {server_names};',
    ]
    if ssl_cert:
        lines.extend([
            f'    ssl_certificate /etc/letsencrypt/live/{ssl_cert}/fullchain.pem;',
            f'    ssl_certificate_key /etc/letsencrypt/live/{ssl_cert}/privkey.pem;',
            '    ssl_protocols TLSv1.2 TLSv1.3;',
        ])
    lines.extend([
        f'    client_max_body_size {upload_max_mb}m;',
        '',
        f'    access_log {access_log};',
        f'    error_log {error_log};',
        '',
        '    location /.well-known/acme-challenge/ {',
        '        root /var/www/letsencrypt;',
        '    }',
        '',
        _proxy_location(upstream),
    ])
    return '\n'.join(lines)


def render_site_block(site, base_domain=None, upstream=None, ssl=False,
                      upload_max_mb=None, is_default=None):
    """渲染单个站点的 nginx 配置块。

    非默认站点若没有任何可用主机名，抛 ValueError（由调用方跳过）；
    默认站点即使没有域名，也会生成 `server_name _;` 兜底块。
    """
    sid = getattr(site, 'id', 0)
    name = str(getattr(site, 'name', '') or '').replace('\r', ' ').replace('\n', ' ')
    hosts = site_hostnames(site, base_domain)
    default = is_default_site(site) if is_default is None else bool(is_default)
    if not hosts and not default:
        raise ValueError(f'站点 {sid} 未配置可用的域名或子域')

    server_names = ' '.join(hosts + (['_'] if default else []))
    max_mb = int(upload_max_mb or DEFAULT_UPLOAD_MAX_MB)
    upstream = upstream or DEFAULT_UPSTREAM
    header = f'# zhycms site {sid}: {name}'.rstrip()

    body = _server_body(server_names, sid, upstream, max_mb)
    http_block = f'server {{\n    listen 80;\n{body}\n}}'

    # SSL 仅对真实域名生效；默认站点无域名时无法指定证书，保持 HTTP。
    if ssl and hosts:
        cert = hosts[0]
        redirect_block = (
            'server {\n'
            '    listen 80;\n'
            f'    server_name {server_names};\n'
            '    return 301 https://$host$request_uri;\n'
            '}'
        )
        https_body = _server_body(
            server_names, sid, upstream, max_mb, ssl_cert=cert)
        https_block = f'server {{\n    listen 443 ssl;\n{https_body}\n}}'
        return f'{header}\n{redirect_block}\n\n{https_block}'

    return f'{header}\n{http_block}'


def render_site_entries(sites, base_domain=None, upstream=None, ssl=False,
                        upload_max_mb=None, upstreams=None):
    """渲染全部站点，返回 (entries, skipped)。

    entries: [{'site_id', 'name', 'filename', 'content'}]
    skipped: [{'site_id', 'name', 'reason'}]
    默认站点无论排序如何都排在最后，承接未匹配域名的请求。
    """
    ordered = [s for s in sites if not is_default_site(s)]
    ordered += [s for s in sites if is_default_site(s)]
    upstream = resolve_upstream(upstream, upstreams)

    entries, skipped = [], []
    for site in ordered:
        try:
            content = render_site_block(
                site, base_domain=base_domain, upstream=upstream,
                ssl=ssl, upload_max_mb=upload_max_mb)
        except ValueError as e:
            skipped.append({
                'site_id': getattr(site, 'id', '?'),
                'name': getattr(site, 'name', '') or '',
                'reason': str(e),
            })
            continue
        entries.append({
            'site_id': getattr(site, 'id', 0),
            'name': getattr(site, 'name', '') or '',
            'filename': f'zhycms-site{getattr(site, "id", 0)}.conf',
            'content': content,
        })
    return entries, skipped


def render_nginx_config(sites, base_domain=None, upstream=None, ssl=False,
                        upload_max_mb=None, upstreams=None):
    """渲染全部站点为单个配置文本，返回 (text, skipped)。"""
    entries, skipped = render_site_entries(
        sites, base_domain=base_domain, upstream=upstream, ssl=ssl,
        upload_max_mb=upload_max_mb, upstreams=upstreams)
    text = '\n\n'.join(e['content'] for e in entries)
    block = render_upstream_block(upstreams)
    if block:
        text = f'{block}\n\n{text}' if text else block
    if text:
        text += '\n'
    return text, skipped


def generate_for_app(app, base_domain=None, upstream=None, ssl=False,
                     site_id=None, upstreams=None):
    """在应用上下文中读取站点并渲染，返回 (text, entries, skipped)。"""
    from ..models.setting import Setting
    from ..models.site import Site

    with app.app_context():
        try:
            sites = Site.active_sites()
        except SQLAlchemyError as e:
            logger.warning('读取站点表失败，按无站点处理：%s', e)
            sites = []
        if site_id is not None:
            sites = [s for s in sites if s.id == site_id]
        try:
            base = base_domain or Setting.get('site_url') or ''
            max_mb = int(Setting.get('upload_single_max_size_mb', '10') or 10)
        except (SQLAlchemyError, TypeError, ValueError) as e:
            logger.warning('读取站点部署设置失败，使用默认值：%s', e)
            base = base_domain or ''
            max_mb = DEFAULT_UPLOAD_MAX_MB
        entries, skipped = render_site_entries(
            sites, base_domain=base, upstream=upstream, ssl=ssl,
            upload_max_mb=max_mb, upstreams=upstreams)
    text = '\n\n'.join(e['content'] for e in entries)
    block = render_upstream_block(upstreams)
    if block:
        text = f'{block}\n\n{text}' if text else block
    if text:
        text += '\n'
    return text, entries, skipped


def ssl_status(domain):
    """只读查询 Let's Encrypt 证书状态。

    返回 {'domain', 'configured', 'expires_at', 'days_left', 'error'}；
    证书不存在或读取失败时 configured=False，不抛异常。
    """
    host = Site.normalize_host(domain)
    result = {
        'domain': host,
        'configured': False,
        'expires_at': None,
        'days_left': None,
        'error': None,
    }
    if not host:
        return result

    from .site_ssl import certificate_root, read_certificate_expiry

    cert_path = os.path.join(certificate_root(), host, 'cert.pem')
    if not os.path.isfile(cert_path):
        return result

    result['configured'] = True
    try:
        expires = read_certificate_expiry(cert_path)
        result['expires_at'] = expires.strftime('%Y-%m-%d %H:%M:%S')
        result['days_left'] = (expires - datetime.now(timezone.utc)).days
    except (OSError, ValueError, AttributeError, TypeError) as e:
        result['error'] = str(e)
        logger.warning('读取证书 %s 失败：%s', cert_path, e)
    return result
