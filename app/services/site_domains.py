"""站点域名工具（v3.3.4）：主域名 + 附加独立域名 + 子域作用域校验。

约定：
- `sites.domain` 仍是主域名（唯一），`site_domains` 只存附加域名；
- 站点的完整独立域名集合 = 主域名 ∪ 附加域名（`site_base_domains`）；
- 子域标签只在“所属域名”作用域内唯一：www.a.com 与 www.b.com 可分别
  归属不同站点；任一方没有独立域名（纯泛解析）时仍按全局唯一处理。
"""
import re

from flask import current_app, g, has_app_context

from ..extensions import db
from ..models.site import Site, SiteDomain

# 单站点附加域名上限
MAX_EXTRA_DOMAINS = 10

# 域名分隔符：换行、中英文逗号、分号、空白
_DOMAIN_SPLIT_RE = re.compile(r'[\s,，;；]+')


def _normalize(value):
    return Site.normalize_host(value)


def site_domain_map():
    """请求级缓存：{site_id: [附加域名]}（每请求最多一次查询）。"""
    if not has_app_context():
        return {}
    cached = g.get('_site_domains_map')
    if cached is not None:
        return cached
    mapping = {}
    try:
        for row in SiteDomain.query.all():
            mapping.setdefault(row.site_id, []).append(
                _normalize(row.domain))
    except Exception as e:
        current_app.logger.debug('附加域名读取失败，按空处理：%s', e)
        mapping = {}
    for domains in mapping.values():
        domains[:] = [d for d in domains if d]
    setattr(g, '_site_domains_map', mapping)
    return mapping


def invalidate_site_domain_cache():
    """站点域名变更后失效请求级缓存。"""
    if has_app_context():
        g.pop('_site_domains_map', None)


def site_base_domains(site, mapping=None):
    """返回站点完整独立域名集合（主域名 + 附加域名，去重保序）。"""
    if site is None:
        return []
    mapping = site_domain_map() if mapping is None else mapping
    result = []
    primary = _normalize(getattr(site, 'domain', None))
    if primary:
        result.append(primary)
    for domain in mapping.get(getattr(site, 'id', None), []):
        if domain and domain not in result:
            result.append(domain)
    return result


def _all_sites():
    try:
        return Site.query.all()
    except Exception as e:
        current_app.logger.debug('站点列表读取失败：%s', e)
        return []


def parse_domain_lines(raw):
    """解析附加域名输入（换行/逗号/分号分隔），返回 (domains, errors)。"""
    domains, errors = [], []
    for part in _DOMAIN_SPLIT_RE.split(raw or ''):
        part = (part or '').strip().lower().rstrip('.')
        if not part:
            continue
        if not Site.is_valid_domain(part):
            errors.append(f'域名格式不正确：{part}')
            continue
        if part not in domains:
            domains.append(part)
    if len(domains) > MAX_EXTRA_DOMAINS:
        errors.append(f'附加域名最多 {MAX_EXTRA_DOMAINS} 个')
    return domains, errors


def validate_domain_ownership(domains, site_id=None):
    """校验附加域名的全局唯一性（与其它站点主域名/附加域名不能重复）。"""
    normalized = [_normalize(d) for d in domains if _normalize(d)]
    if not normalized:
        return []
    errors = []
    others = [s for s in _all_sites() if s.id != site_id]
    used = {}
    for s in others:
        primary = _normalize(s.domain)
        if primary:
            used[primary] = s.name
    try:
        query = SiteDomain.query
        if site_id is not None:
            query = query.filter(SiteDomain.site_id != site_id)
        for row in query.all():
            domain = _normalize(row.domain)
            if domain:
                used[domain] = getattr(row.site, 'name', '') or ''
    except Exception as e:
        current_app.logger.warning('附加域名占用检查失败：%s', e)
    for domain in normalized:
        if domain in used:
            errors.append(f'域名已被占用：{domain}')
    return errors


def validate_subdomain_scope(subdomain, base_domains, site_id=None):
    """校验子域标签在“所属域名作用域”内唯一，返回错误文案或 None。

    规则：与其它站点子域同名时，仅当双方都有非空独立域名集合且集合不相交
    才允许重复；任一方无域名（纯泛解析）或域名有交集时仍视为冲突。
    """
    sub = _normalize(subdomain)
    if not sub:
        return None
    mine = {d for d in (base_domains or []) if d}
    mapping = {}
    try:
        for row in SiteDomain.query.filter(SiteDomain.site_id != site_id).all():
            mapping.setdefault(row.site_id, []).append(_normalize(row.domain))
    except Exception as e:
        current_app.logger.warning('子域作用域检查读取附加域名失败：%s', e)
    for other in _all_sites():
        if other.id == site_id:
            continue
        if _normalize(other.subdomain) != sub:
            continue
        theirs = set()
        primary = _normalize(other.domain)
        if primary:
            theirs.add(primary)
        theirs.update(d for d in mapping.get(other.id, []) if d)
        if not mine or not theirs or (mine & theirs):
            return f'子域标签已被占用：{sub}（同一域名作用域）'
    return None


def sync_site_domains(site, domains):
    """把站点的附加域名同步为 domains（差量增删），不 commit。"""
    target = []
    for value in domains or []:
        normalized = _normalize(value)
        if normalized and normalized not in target:
            target.append(normalized)
    existing = {row.domain: row for row in
                SiteDomain.query.filter_by(site_id=site.id).all()}
    for domain, row in existing.items():
        if domain not in target:
            db.session.delete(row)
    for domain in target:
        if domain not in existing:
            db.session.add(SiteDomain(site_id=site.id, domain=domain))
    invalidate_site_domain_cache()
