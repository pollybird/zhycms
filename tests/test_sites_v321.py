"""v3.2.1 站群缺陷修复回归测试。

覆盖：
  - 站点权限：?site= 越权拦截、受限编辑入口 403、未绑定老账号零回归
  - 站点关闭：前台 503 / API JSON 503 / healthz 200 / 插件前台蓝本 503
  - 独立会员：跨站会话失效，共享模式保持
  - 站点 SEO：前台与 API 以站点字段优先
  - 0012 降级预检：跨站重复值可被识别
  - 边界项：域名/子域规范化、子域唯一、sort_order 校验、删站内容检查、site_url
"""
import importlib

import pytest

from app.extensions import db
from app.models.site import Site, DEFAULT_SITE_ID

pytestmark = pytest.mark.sites


def _mk_site(app, slug='site-b', name='站点B', domain=None, subdomain=None,
             status='open'):
    with app.app_context():
        site = Site(name=name, slug=slug, domain=domain, subdomain=subdomain,
                    status=status)
        db.session.add(site)
        db.session.commit()
        return site.id


def _mk_user(app, username, site_ids=()):
    """创建非超管用户；site_ids 非空时写入站点绑定（限制可见站点）。"""
    with app.app_context():
        from app.models.rbac import UserSitePermission
        from app.models.user import User
        user = User(username=username, is_super=False, is_deleted=False)
        user.set_password('Abcdef123456!')
        db.session.add(user)
        db.session.flush()
        for sid in site_ids:
            db.session.add(UserSitePermission(user_id=user.id, site_id=sid))
        db.session.commit()
        return user.id


def _login(client, uid):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True


@pytest.fixture(autouse=True)
def _clean_sites(app):
    yield
    with app.app_context():
        from app.models.article import Article
        from app.models.column import Column
        from app.models.fragment import Fragment
        from app.models.rbac import UserSitePermission
        from app.models.setting import Setting
        from app.models.user import User
        try:
            from plugins.member.models import Member
            Member.query.filter(Member.username.like('sg-%')).delete(
                synchronize_session=False)
        except (ImportError, RuntimeError):
            pass
        Article.query.filter(Article.site_id != 0).delete()
        Column.query.filter(Column.site_id != 0).delete()
        Fragment.query.filter(Fragment.site_id != 0).delete()
        UserSitePermission.query.delete()
        User.query.filter(User.username.like('sg-%')).delete(
            synchronize_session=False)
        Setting.query.filter(Setting.key.in_(('member_scope', 'site_url'))).delete(
            synchronize_session=False)
        Setting.query.filter(Setting.site_id != 0).delete()
        Site.query.filter(Site.id != 0).delete()
        db.session.commit()


# ============================================================
# A 站点权限
# ============================================================

def test_restricted_editor_cannot_switch_via_param(app, client):
    """只绑定默认站的编辑带 ?site= 访问他站 → 403，且不写入会话。"""
    sid = _mk_site(app, slug='site-b')
    uid = _mk_user(app, 'sg-restricted', site_ids=[DEFAULT_SITE_ID])
    _login(client, uid)

    resp = client.get(f'/admin/?site={sid}')
    assert resp.status_code == 403
    with client.session_transaction() as sess:
        assert sess.get('admin_site_id') != sid

    # 不带参数访问默认站点仍正常（不会因守卫误伤）
    assert client.get('/admin/').status_code == 200


def test_restricted_editor_content_route_blocked(app, client):
    """受限编辑访问他站栏目文章列表 → 403，响应不含他站内容。"""
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        from app.models.column import Column
        col = Column(name='B栏目', slug='sg-b-col', type='list',
                     site_id=sid, is_enabled=True, is_deleted=False)
        db.session.add(col)
        db.session.commit()
        col_id = col.id
    uid = _mk_user(app, 'sg-restricted2', site_ids=[DEFAULT_SITE_ID])
    _login(client, uid)

    resp = client.get(f'/admin/columns/{col_id}/articles?site={sid}')
    assert resp.status_code == 403


def test_unbound_user_has_no_site_access(app, client):
    """无任何角色或站点绑定的账号不再默认全站可见（fail-closed）。"""
    sid = _mk_site(app, slug='site-b')
    uid = _mk_user(app, 'sg-legacy')
    _login(client, uid)

    assert client.get(f'/admin/?site={sid}').status_code == 403


# ============================================================
# B 站点关闭
# ============================================================

def test_closed_site_api_returns_json_503(app, client):
    """关闭站点的内容 API 返回 503 JSON，而非 HTML 关闭页。"""
    _mk_site(app, slug='site-b', domain='b.example.com', status='closed')
    resp = client.get('/api/v1/columns', headers={'Host': 'b.example.com'})
    assert resp.status_code == 503
    assert resp.is_json
    assert resp.get_json()['code'] == 503


def test_closed_site_healthz_ok(app, client):
    """健康探针不受站点关闭影响（固定 200）。"""
    _mk_site(app, slug='site-b', domain='b.example.com', status='closed')
    resp = client.get('/healthz', headers={'Host': 'b.example.com'})
    assert resp.status_code == 200


def test_closed_site_plugin_frontend_blocked(app, client):
    """插件前台蓝本（member 等）在关闭站点下同样 503。"""
    _mk_site(app, slug='site-b', domain='b.example.com', status='closed')
    resp = client.get('/login', headers={'Host': 'b.example.com'})
    assert resp.status_code == 503


def test_closed_default_site_admin_still_accessible(app, admin_client):
    """默认站点关闭时后台仍可访问（关闭只作用于前台）。"""
    with app.app_context():
        from app.models.setting import Setting
        Setting.set('site_status', 'closed')
        db.session.commit()
    try:
        assert admin_client.get('/admin/').status_code == 200
    finally:
        with app.app_context():
            from app.models.setting import Setting
            Setting.set('site_status', 'open')
            db.session.commit()


# ============================================================
# C 独立会员会话
# ============================================================

def test_isolated_member_session_not_shared_across_sites(app):
    """isolated 模式下，A 站会员会话在 B 站失效，回到 A 站仍有效。"""
    _mk_site(app, slug='site-b', domain='b.example.com')
    from plugins.member.models import Member
    with app.app_context():
        from app.models.setting import Setting
        Setting.set('member_scope', 'isolated')
        member = Member(username='sg-mem-a', site_id=DEFAULT_SITE_ID,
                        is_enabled=True, is_deleted=False)
        member.set_password('Abcdef123456!')
        db.session.add(member)
        db.session.commit()
        mid = member.id

    from flask import session
    from app.sites import select_site
    from plugins.member.security import current_member

    with app.test_request_context('/', headers={'Host': 'b.example.com'}):
        session['member_id'] = mid
        select_site()
        assert current_member() is None
        assert session.get('member_id') is None

    with app.test_request_context('/'):
        session['member_id'] = mid
        select_site()
        assert current_member() is not None


def test_shared_member_session_keeps_working(app):
    """shared 模式（默认）下会员跨站仍保持登录（与现网一致）。"""
    _mk_site(app, slug='site-b', domain='b.example.com')
    from plugins.member.models import Member
    with app.app_context():
        member = Member(username='sg-mem-shared', site_id=DEFAULT_SITE_ID,
                        is_enabled=True, is_deleted=False)
        member.set_password('Abcdef123456!')
        db.session.add(member)
        db.session.commit()
        mid = member.id

    from flask import session
    from app.sites import select_site
    from plugins.member.security import current_member

    with app.test_request_context('/', headers={'Host': 'b.example.com'}):
        session['member_id'] = mid
        select_site()
        assert current_member() is not None


# ============================================================
# D 站点 SEO
# ============================================================

def test_site_seo_used_by_frontend_and_api(app, client):
    """站点 seo_title 覆盖全局设置，前台与 API 一致。"""
    sid = _mk_site(app, slug='site-b', domain='b.example.com')
    with app.app_context():
        from app.extensions import cache
        site = db.session.get(Site, sid)
        site.seo_title = 'SITE-SEO-TITLE'
        site.seo_keywords = 'SITE-KW'
        db.session.commit()
        cache.clear()

    data = client.get('/api/v1/site', headers={'Host': 'b.example.com'}).get_json()['data']
    assert data['site_id'] == sid
    assert data['seo']['title'] == 'SITE-SEO-TITLE'
    assert data['seo']['keywords'] == 'SITE-KW'
    assert data['seo_title'] == 'SITE-SEO-TITLE'

    # 前台 SEO 基线（主题首页 title 由主题自定义，这里直接校验 _seo 输出）
    with app.test_request_context('/', headers={'Host': 'b.example.com'}):
        from app.frontend.views import _seo
        from app.sites import select_site
        select_site()
        seo = _seo()
    assert seo['title'] == 'SITE-SEO-TITLE'
    assert seo['keywords'] == 'SITE-KW'


# ============================================================
# E 0012 降级预检
# ============================================================

def test_downgrade_precheck_detects_cross_site_duplicate(app):
    """跨站同名 slug 会被降级预检识别（避免半降级）。"""
    mod = importlib.import_module('migrations.versions.0012_v3_2_0_sites')
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        from app.models.column import Column
        db.session.add(Column(name='A同名', slug='sg-dup-slug', type='page',
                              site_id=DEFAULT_SITE_ID, is_enabled=True,
                              is_deleted=False))
        db.session.add(Column(name='B同名', slug='sg-dup-slug', type='page',
                              site_id=sid, is_enabled=True, is_deleted=False))
        db.session.commit()
        with db.engine.connect() as conn:
            conflicts = mod._find_downgrade_conflicts(conn)
    assert any('columns.slug=sg-dup-slug' in c for c in conflicts)


def test_downgrade_precheck_clean(app):
    """无重复值时预检不产生误报。"""
    mod = importlib.import_module('migrations.versions.0012_v3_2_0_sites')
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        from app.models.column import Column
        db.session.add(Column(name='A唯一', slug='sg-unique-slug', type='page',
                              site_id=DEFAULT_SITE_ID, is_enabled=True,
                              is_deleted=False))
        db.session.add(Column(name='B唯一', slug='sg-unique-slug-b', type='page',
                              site_id=sid, is_enabled=True, is_deleted=False))
        db.session.commit()
        with db.engine.connect() as conn:
            conflicts = mod._find_downgrade_conflicts(conn)
    assert not any('sg-unique-slug' in c for c in conflicts)


# ============================================================
# F 边界项
# ============================================================

def test_site_host_normalization_and_validation(app):
    """域名/子域规范化与 DNS label 校验。"""
    assert Site.normalize_host('  Example.COM.  ') == 'example.com'
    assert Site.normalize_host('') is None
    assert Site.normalize_host('   ') is None
    assert Site.is_valid_domain('www.example.com')
    assert Site.is_valid_domain('localhost')
    assert not Site.is_valid_domain('a..b')
    assert not Site.is_valid_domain('-bad.com')
    assert not Site.is_valid_domain('bad-.com')
    assert not Site.is_valid_domain('a' * 64 + '.com')


def test_subdomain_not_globally_unique(app):
    """v3.3.4：子域不再全局唯一（www.a.com / www.b.com 可共存）。

    唯一性改由站点保存校验按“所属域名作用域”保证，见
    tests/test_sites_v334.py。
    """
    _mk_site(app, slug='site-s1', domain='a.com', subdomain='dup-sub')
    with app.app_context():
        db.session.add(Site(name='重复子域', slug='site-s2',
                            domain='b.com', subdomain='dup-sub'))
        db.session.commit()
        assert Site.query.filter_by(subdomain='dup-sub').count() == 2


def test_site_create_invalid_sort_order(app, admin_client):
    """sort_order 非数字时表单提示且不创建站点，不触发 500。"""
    resp = admin_client.post('/admin/sites/create', data={
        'name': '非法排序站点', 'slug': 'site-x', 'sort_order': 'abc',
    })
    assert resp.status_code in (200, 302)
    with app.app_context():
        assert Site.query.filter_by(slug='site-x').first() is None


def test_delete_site_with_content_moves_to_recycle(app, admin_client):
    """站点下仍有内容时删除会移入回收站，内容保留以便恢复。"""
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        from app.models.column import Column
        db.session.add(Column(name='B栏目', slug='sg-del-col', type='page',
                              site_id=sid, is_enabled=True, is_deleted=False))
        db.session.commit()

    resp = admin_client.post(f'/admin/sites/{sid}/delete')
    assert resp.status_code in (200, 302)
    with app.app_context():
        from app.models.column import Column
        from app.models.site_recycle import SiteRecycleBin
        site = db.session.get(Site, sid)
        assert site is not None
        assert site.is_deleted is True
        assert Column.query.filter_by(site_id=sid).count() == 1
        assert SiteRecycleBin.query.filter_by(
            site_id=sid, restored_at=None).count() == 1


def test_site_url_supports_subdomain_only(app):
    """仅有子域的站点基于 Setting.site_url 主机名生成绝对 URL。"""
    sid = _mk_site(app, slug='site-b', subdomain='b')
    with app.app_context():
        from app.models.setting import Setting
        Setting.set('site_url', 'https://main.example.com')
        db.session.commit()

    with app.test_request_context('/'):
        from app.sites import site_url
        assert site_url(sid) == 'https://b.main.example.com/'


def test_dev_two_label_localhost_subdomain(app):
    """开发环境支持 b.localhost 两段式子域解析。"""
    sid = _mk_site(app, slug='site-b', subdomain='b')
    with app.test_request_context('/', headers={'Host': 'b.localhost'}):
        from app.sites import current_site_id, select_site
        select_site()
        assert current_site_id() == sid
