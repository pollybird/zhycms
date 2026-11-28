"""v3.3.4：站点多独立域名 + 子域标签按域名作用域。

覆盖：
  - www.a.com / www.b.com 可分别归属不同站点（子域不再全局唯一）
  - 解析优先级：精确域名 → 域名作用域子域 → 唯一子域回落
  - 附加域名保存、解析、nginx server_name 输出与冲突校验
  - 0013/0021：子域唯一索引改为普通索引、site_domains 表建删
"""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.extensions import db
from app.models.site import Site, SiteDomain

pytestmark = pytest.mark.sites

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(ROOT, 'migrations')


def _mk_site(app, slug, domain=None, subdomain=None, extras=()):
    with app.app_context():
        site = Site(name=slug, slug=slug, domain=domain,
                    subdomain=subdomain, status='open')
        db.session.add(site)
        db.session.flush()
        for extra in extras:
            db.session.add(SiteDomain(site_id=site.id, domain=extra))
        db.session.commit()
        return site.id


def _resolve(app, host):
    with app.test_request_context('/', headers={'Host': host}):
        from app.sites import current_site_id, select_site
        select_site()
        return current_site_id()


@pytest.fixture(autouse=True)
def _cleanup_sites(app):
    yield
    with app.app_context():
        sites = Site.query.filter(Site.slug.like('v334-%')).all()
        for site in sites:
            db.session.delete(site)
        db.session.commit()


# ============================================================
# A 子域作用域
# ============================================================

def test_same_subdomain_on_different_domains_resolves(app):
    a = _mk_site(app, 'v334-a', domain='a-v334.com', subdomain='www')
    b = _mk_site(app, 'v334-b', domain='b-v334.com', subdomain='www')

    assert _resolve(app, 'a-v334.com') == a
    assert _resolve(app, 'b-v334.com') == b
    assert _resolve(app, 'www.a-v334.com') == a
    assert _resolve(app, 'www.b-v334.com') == b


def test_domain_owner_without_subdomain_does_not_fall_through(app):
    _mk_site(app, 'v334-own', domain='own-v334.com')
    b = _mk_site(app, 'v334-sub', domain='sub-v334.com', subdomain='www')

    # own-v334.com 已归属站点且未配置 www 子域：不得被其它站点的 www 抢走
    assert _resolve(app, 'www.own-v334.com') == 0
    assert _resolve(app, 'www.sub-v334.com') == b


def test_unique_subdomain_fallback_still_works(app):
    c = _mk_site(app, 'v334-wild', subdomain='v334uniq')
    # 父域不属于任何站点，且全站只有一个站点使用该标签 → 兼容回落
    assert _resolve(app, 'v334uniq.other-domain.com') == c


# ============================================================
# B 后台保存校验
# ============================================================

def test_admin_allows_same_subdomain_with_different_domains(app, admin_client):
    resp = admin_client.post('/admin/sites/create', data={
        'name': 'A站', 'slug': 'v334-adm-a',
        'domain': 'adm-a-v334.com', 'subdomain': 'www',
    })
    assert resp.status_code == 302
    resp = admin_client.post('/admin/sites/create', data={
        'name': 'B站', 'slug': 'v334-adm-b',
        'domain': 'adm-b-v334.com', 'subdomain': 'www',
    })
    assert resp.status_code == 302
    with app.app_context():
        a = Site.query.filter_by(slug='v334-adm-a').first()
        b = Site.query.filter_by(slug='v334-adm-b').first()
        assert a and b and a.subdomain == b.subdomain == 'www'


def test_admin_rejects_duplicate_subdomain_without_domains(app, admin_client):
    resp = admin_client.post('/admin/sites/create', data={
        'name': 'D1', 'slug': 'v334-dup-1', 'subdomain': 'v334dup',
    })
    assert resp.status_code == 302
    resp = admin_client.post('/admin/sites/create', data={
        'name': 'D2', 'slug': 'v334-dup-2', 'subdomain': 'v334dup',
    })
    assert resp.status_code == 200
    with app.app_context():
        assert Site.query.filter_by(slug='v334-dup-2').first() is None


# ============================================================
# C 多独立域名
# ============================================================

def test_extra_domains_saved_and_resolved(app, admin_client):
    resp = admin_client.post('/admin/sites/create', data={
        'name': '多域名站', 'slug': 'v334-multi', 'domain': 'multi-v334.com',
        'subdomain': 'www', 'domains': 'multi-v334.com.cn\nmulti-v334.net',
    })
    assert resp.status_code == 302
    with app.app_context():
        site = Site.query.filter_by(slug='v334-multi').first()
        assert site is not None
        assert sorted(r.domain for r in site.domain_entries) == [
            'multi-v334.com.cn', 'multi-v334.net']
        from app.services.site_deploy import site_hostnames
        hosts = site_hostnames(site, 'tzzhy.cn')
    assert 'multi-v334.com' in hosts
    assert 'multi-v334.com.cn' in hosts
    assert 'multi-v334.net' in hosts
    assert 'www.multi-v334.com.cn' in hosts
    assert _resolve(app, 'multi-v334.com.cn') == site.id
    assert _resolve(app, 'www.multi-v334.net') == site.id


def test_extra_domain_conflict_rejected(app, admin_client):
    _mk_site(app, 'v334-exist', domain='taken-v334.com')
    resp = admin_client.post('/admin/sites/create', data={
        'name': '冲突站', 'slug': 'v334-conflict', 'domain': 'conf-v334.com',
        'domains': 'taken-v334.com',
    })
    assert resp.status_code == 200
    with app.app_context():
        assert Site.query.filter_by(slug='v334-conflict').first() is None


def test_extra_domain_cannot_equal_primary(app, admin_client):
    resp = admin_client.post('/admin/sites/create', data={
        'name': '同域站', 'slug': 'v334-same', 'domain': 'same-v334.com',
        'domains': 'same-v334.com',
    })
    assert resp.status_code == 200
    with app.app_context():
        assert Site.query.filter_by(slug='v334-same').first() is None


# ============================================================
# D 迁移 0021
# ============================================================

def _cfg(db_path):
    cfg = Config()
    cfg.set_main_option('script_location', MIGRATIONS_DIR)
    cfg.set_main_option('sqlalchemy.url', f'sqlite:///{db_path}')
    return cfg


def _subdomain_indexes(db_path):
    insp = inspect(create_engine(f'sqlite:///{db_path}'))
    return [ix for ix in insp.get_indexes('sites')
            if (ix.get('column_names') or []) == ['subdomain']]


def test_migration_0021_upgrade_downgrade(tmp_path):
    from app import models  # noqa: F401  确保 metadata 完整
    db_path = str(tmp_path / 'mig.db')
    engine = create_engine(f'sqlite:///{db_path}')
    db.metadata.create_all(engine)
    engine.dispose()

    cfg = _cfg(db_path)
    command.stamp(cfg, '0020')
    command.upgrade(cfg, '0021')

    insp = inspect(create_engine(f'sqlite:///{db_path}'))
    assert insp.has_table('site_domains')
    assert not any(ix.get('unique') for ix in _subdomain_indexes(db_path))

    command.downgrade(cfg, '0020')
    insp = inspect(create_engine(f'sqlite:///{db_path}'))
    assert not insp.has_table('site_domains')
    assert any(ix.get('unique') for ix in _subdomain_indexes(db_path))
