"""v3.2.2 站群内容站点化回归测试。

覆盖：
  - 迁移 0014 链路与目标表
  - 教程：slug 站内唯一、演示数据只清理当前站点
  - 页面构建：按站点隔离、跨站编辑器 404、列表只含当前站点
  - 上传：去重按站点、物理路径带站点前缀
  - 删站检查：教程/构建页面阻止删除
  - 会员：第三方绑定站内唯一、删除接口站点校验
  - 缓存：站点前缀失效、浏览量按站分键与合并
  - 搜索：插件 sql_search 站点参数
  - 平台级后台入口豁免与备份权限收敛
"""
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

from app.extensions import db

pytestmark = pytest.mark.sites

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SITE_ID = 0


# ============================================================
# 辅助
# ============================================================

def _mk_site(app, slug='site-b', name='站点B', domain=None, subdomain=None):
    from app.models.site import Site
    with app.app_context():
        site = Site(name=name, slug=slug, domain=domain, subdomain=subdomain)
        db.session.add(site)
        db.session.commit()
        return site.id


def _mk_column(app, slug, site_id=DEFAULT_SITE_ID):
    from app.models.column import Column
    with app.app_context():
        col = Column(name=slug, slug=slug, type='list', site_id=site_id,
                     is_enabled=True, is_deleted=False)
        db.session.add(col)
        db.session.commit()
        return col.id


def _mk_article(app, title, column_id, site_id=DEFAULT_SITE_ID, viewed=0):
    from app.models.article import Article
    with app.app_context():
        a = Article(title=title, column_id=column_id,
                    site_id=site_id, status='published', is_deleted=False,
                    viewed=viewed, content='v322')
        db.session.add(a)
        db.session.commit()
        return a.id


def _set_admin_site(client, sid):
    with client.session_transaction() as sess:
        sess['admin_site_id'] = sid


def _mk_role_user(app, username, codes):
    """创建仅拥有指定权限的非超管用户。"""
    from app.models.rbac import (
        Role, RolePermission, Permission, UserRole, UserSitePermission,
    )
    from app.models.user import User
    with app.app_context():
        Permission.ensure_presets()
        role = Role(code=f'role-{username}', name=username)
        db.session.add(role)
        db.session.flush()
        for code in codes:
            db.session.add(RolePermission(role_id=role.id, permission_code=code))
        user = User(username=username, is_super=False, is_deleted=False)
        user.set_password('Abcdef123456!')
        db.session.add(user)
        db.session.flush()
        db.session.add(UserRole(user_id=user.id, role_id=role.id))
        db.session.add(UserSitePermission(user_id=user.id, site_id=DEFAULT_SITE_ID))
        db.session.commit()
        return user.id


def _login(client, uid):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True


@pytest.fixture(autouse=True)
def _clean_v322(app):
    yield
    from app.models.setting import Setting
    from app.models.site import Site
    from app.models.user import User
    from app.models.rbac import Role, RolePermission, UserRole, UserSitePermission
    from app.models.article import Article
    from app.models.column import Column
    with app.app_context():
        from app.models.upload import UploadedFile
        from app.models.builder import BuilderPage, BuilderRevision
        try:
            from plugins.tutorial.models import Tutorial, TutorialCategory
            Tutorial.query.delete(synchronize_session=False)
            TutorialCategory.query.delete(synchronize_session=False)
        except Exception:
            db.session.rollback()
        BuilderRevision.query.delete(synchronize_session=False)
        BuilderPage.query.delete(synchronize_session=False)
        UploadedFile.query.filter(UploadedFile.site_id != 0).delete(
            synchronize_session=False)
        Article.query.filter(Article.title.like('v322-%')).delete(
            synchronize_session=False)
        Column.query.filter(Column.slug.like('v322-%')).delete(
            synchronize_session=False)
        try:
            from plugins.member.models import Member, MemberOauth
            MemberOauth.query.delete(synchronize_session=False)
            Member.query.filter(Member.username.like('v322-%')).delete(
                synchronize_session=False)
        except Exception:
            db.session.rollback()
        for code in [r.code for r in Role.query.filter(
                Role.code.like('role-v322-%')).all()]:
            role = Role.query.filter_by(code=code).first()
            if role:
                UserRole.query.filter_by(role_id=role.id).delete()
                db.session.delete(role)
        UserSitePermission.query.delete()
        User.query.filter(User.username.like('v322-%')).delete(
            synchronize_session=False)
        Setting.query.filter(Setting.key.in_(('cache_enable', 'member_scope'))).delete(
            synchronize_session=False)
        Site.query.filter(Site.id != DEFAULT_SITE_ID).delete()
        db.session.commit()


# ============================================================
# 迁移
# ============================================================

def test_migration_0014_chain():
    path = ROOT / 'migrations' / 'versions' / '0014_v3_2_2_site_scope_content.py'
    spec = importlib.util.spec_from_file_location('mig0014', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == '0014'
    assert mod.down_revision == '0013'
    assert set(mod._SCOPED_TABLES) == {
        'tutorial_categories', 'tutorials', 'builder_pages',
        'uploaded_files', 'member_oauths',
    }


# ============================================================
# 教程
# ============================================================

def test_tutorial_slug_unique_per_site(app):
    from sqlalchemy.exc import IntegrityError
    from plugins.tutorial.models import Tutorial, TutorialCategory
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        cat0 = TutorialCategory(name='A', slug='v322-cat-a', site_id=0)
        catb = TutorialCategory(name='B', slug='v322-cat-a', site_id=sid)
        db.session.add_all([cat0, catb])
        db.session.commit()
        db.session.add(Tutorial(title='A', slug='v322-t-a', category_id=cat0.id,
                                site_id=0, content='x'))
        db.session.add(Tutorial(title='B', slug='v322-t-a', category_id=catb.id,
                                site_id=sid, content='x'))
        db.session.commit()  # 跨站同 slug 允许
        db.session.add(Tutorial(title='A2', slug='v322-t-a', category_id=cat0.id,
                                site_id=0, content='x'))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_tutorial_demo_only_clears_current_site(app):
    from app.sites import set_current_site
    from plugins.tutorial.models import Tutorial, TutorialCategory
    from plugins.tutorial import demo
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        c0 = TutorialCategory(name='A', slug='v322-demo-a', site_id=0)
        cb = TutorialCategory(name='B', slug='v322-demo-b', site_id=sid)
        db.session.add_all([c0, cb])
        db.session.commit()
        db.session.add_all([
            Tutorial(title='A', slug='v322-demo-ta', category_id=c0.id,
                     site_id=0, content='x'),
            Tutorial(title='B', slug='v322-demo-tb', category_id=cb.id,
                     site_id=sid, content='x'),
        ])
        db.session.commit()

        set_current_site(sid)
        demo.generate('not-education')  # 非教育行业：只清理当前站点

        assert Tutorial.query.filter_by(site_id=0).count() == 1
        assert Tutorial.query.filter_by(site_id=sid).count() == 0
        from flask import g
        g.pop('current_site_id', None)


# ============================================================
# 页面构建
# ============================================================

def test_builder_page_isolated_per_site(app):
    from app.sites import set_current_site
    from app.models.builder import BuilderPage
    from app.builder import service
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        db.session.add_all([
            BuilderPage(site_id=0, scope='home', name='A 首页'),
            BuilderPage(site_id=sid, scope='home', name='B 首页'),
        ])
        db.session.commit()

        set_current_site(sid)
        page = service.get_page('home')
        assert page is not None and page.site_id == sid

        set_current_site(0)
        page = service.get_page('home')
        assert page is not None and page.site_id == 0

        by_scope, _cols = service.list_pages_grouped()
        assert [p.name for p in by_scope['home']] == ['A 首页']


def test_builder_editor_cross_site_404(admin_client, app):
    from app.models.builder import BuilderPage
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        page = BuilderPage(site_id=sid, scope='home', name='B 首页')
        db.session.add(page)
        db.session.commit()
        pid = page.id
    # 超管也必须在当前站点内访问：默认站点 0 打开 B 站页面 → 404
    resp = admin_client.get(f'/admin/builder/editor/{pid}')
    assert resp.status_code == 404


def test_pages_referencing_widget_types_cross_site(app):
    """插件组件卸载检查必须跨站点扫描（不能只看当前站点）。"""
    import json
    from app.models.builder import BuilderPage
    from app.builder import service
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        layout = {'version': 1, 'root': [{'type': 'demo_widget'}]}
        db.session.add(BuilderPage(
            site_id=sid, scope='home', name='B',
            draft_json=json.dumps(layout)))
        db.session.commit()
        hits = service.pages_referencing_widget_types(['demo_widget'])
        assert len(hits) == 1 and hits[0].site_id == sid


# ============================================================
# 上传
# ============================================================

def test_upload_dedup_is_site_scoped(app):
    from app.models.upload import UploadedFile
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        db.session.add(UploadedFile(
            site_id=0, original_name='a.png', stored_name='uploads/site0/a.png',
            content_hash='v322-hash', url='/static/uploads/site0/a.png',
            file_size=10, uploader_id=None, created_at=datetime.now()))
        db.session.commit()
        assert UploadedFile.find_by_hash('v322-hash', site_id=0) is not None
        assert UploadedFile.find_by_hash('v322-hash', site_id=sid) is None


def test_upload_path_has_site_prefix(admin_client, app):
    import io
    import json as _json
    sid = _mk_site(app, slug='site-b')
    _set_admin_site(admin_client, sid)
    png = bytes.fromhex(
        '89504e470d0a1a0a0000000d49484452000000010000000108020000'
        '00907753de0000000c494441540899636000000000020001e221bc33'
        '0000000049454e44ae426082')
    resp = admin_client.post(
        '/admin/upload',
        data={'type': 'image', 'file': (io.BytesIO(png), 'v322.png')},
        content_type='multipart/form-data')
    assert resp.status_code == 200
    payload = _json.loads(resp.get_data(as_text=True))
    assert payload['path'].startswith(f'uploads/site{sid}/image/')


# ============================================================
# 删站检查
# ============================================================

def test_site_delete_blocked_by_tutorial(admin_client, app):
    from app.models.site import Site
    from plugins.tutorial.models import Tutorial, TutorialCategory
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        cat = TutorialCategory(name='B', slug='v322-del-cat', site_id=sid)
        db.session.add(cat)
        db.session.commit()
        db.session.add(Tutorial(title='B', slug='v322-del-t', category_id=cat.id,
                                site_id=sid, content='x'))
        db.session.commit()
    resp = admin_client.post(f'/admin/sites/{sid}/delete')
    assert resp.status_code in (302, 200)
    with app.app_context():
        assert Site.query.get(sid) is not None


def test_site_delete_blocked_by_builder_page(admin_client, app):
    from app.models.site import Site
    from app.models.builder import BuilderPage
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        db.session.add(BuilderPage(site_id=sid, scope='home', name='B'))
        db.session.commit()
    resp = admin_client.post(f'/admin/sites/{sid}/delete')
    assert resp.status_code in (302, 200)
    with app.app_context():
        assert Site.query.get(sid) is not None


# ============================================================
# 会员绑定 / 会员删除
# ============================================================

def test_member_oauth_unique_per_site(app):
    from sqlalchemy.exc import IntegrityError
    from plugins.member.models import Member, MemberOauth
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        m0 = Member(username='v322-m0', site_id=0)
        mb = Member(username='v322-mb', site_id=sid)
        db.session.add_all([m0, mb])
        db.session.commit()
        db.session.add_all([
            MemberOauth(member_id=m0.id, provider='wechat', openid='v322-openid'),
            MemberOauth(member_id=mb.id, provider='wechat', openid='v322-openid',
                        site_id=sid),
        ])
        db.session.commit()
        db.session.add(MemberOauth(
            member_id=m0.id, provider='wechat', openid='v322-openid', site_id=0))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_member_delete_cross_site_404(client, app):
    from plugins.member.models import Member
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        m = Member(username='v322-m-del', site_id=sid)
        db.session.add(m)
        db.session.commit()
        mid = m.id
    uid = _mk_role_user(app, 'v322-member-admin', ['member:manage'])
    _login(client, uid)
    resp = client.post(f'/admin/members/{mid}/delete')
    # 会员插件未启用时路由不存在（404）；启用时应为 404/403，绝不能删除
    assert resp.status_code in (404, 403)
    with app.app_context():
        assert Member.query.get(mid).is_deleted is False


# ============================================================
# 缓存 / 浏览量
# ============================================================

def test_view_pending_key_per_site(app):
    from app.frontend.views import _view_pending_key
    with app.app_context():
        assert _view_pending_key(0) == 'article:viewed:pending:site0'
        assert _view_pending_key(7) == 'article:viewed:pending:site7'


def test_flush_site_views_only_touches_site(app):
    from app.extensions import cache
    from app.frontend.views import _flush_site_views, _view_pending_key
    from app.models.article import Article
    sid = _mk_site(app, slug='site-b')
    col0 = _mk_column(app, 'v322-col-a', 0)
    colb = _mk_column(app, 'v322-col-b', sid)
    a0 = _mk_article(app, 'v322-article-a', col0, 0)
    ab = _mk_article(app, 'v322-article-b', colb, sid)
    with app.app_context():
        cache.set(_view_pending_key(0), {a0: 5}, timeout=60)
        cache.set(_view_pending_key(sid), {ab: 9}, timeout=60)
        _flush_site_views(0)
        assert db.session.get(Article, a0).viewed == 5
        assert db.session.get(Article, ab).viewed == 0
        _flush_site_views(sid)
        assert db.session.get(Article, ab).viewed == 9


def test_clear_content_cache_uses_site_prefix(app, monkeypatch):
    from app.extensions import cache
    from app.models.setting import Setting
    from app.utils.helpers import clear_content_cache
    calls = []
    monkeypatch.setattr(cache, 'delete_pattern', lambda p: calls.append(p),
                        raising=False)
    with app.app_context():
        old = Setting.get('cache_enable')
        Setting.set('cache_enable', 'on')
        try:
            clear_content_cache()
        finally:
            Setting.set('cache_enable', old or 'off')
    assert 'frontend/site0/*' in calls


# ============================================================
# 搜索
# ============================================================

def test_search_provider_default_accepts_site_id():
    from app.utils.search import SearchProvider
    assert SearchProvider().sql_search('x', 'zh', 1, 10, site_id=0) == ([], 0)


def test_product_sql_search_filters_site(app):
    from plugins.product.models import Product
    from plugins.product.search import ProductSearchProvider
    sid = _mk_site(app, slug='site-b')
    col0 = _mk_column(app, 'v322-prod-a', 0)
    colb = _mk_column(app, 'v322-prod-b', sid)
    with app.app_context():
        db.session.add_all([
            Product(title='v322 产品A', column_id=col0, site_id=0,
                    is_enabled=True, is_deleted=False, updated_at=datetime.now()),
            Product(title='v322 产品B', column_id=colb, site_id=sid,
                    is_enabled=True, is_deleted=False, updated_at=datetime.now()),
        ])
        db.session.commit()
        items, total = ProductSearchProvider().sql_search(
            'v322', 'zh', page=1, per_page=10, site_id=0)
        assert total == 1
        assert all(i['site_id'] == 0 for i in items)

        items_b, total_b = ProductSearchProvider().sql_search(
            'v322', 'zh', page=1, per_page=10, site_id=sid)
        assert total_b == 1
        assert all(i['site_id'] == sid for i in items_b)


# ============================================================
# 平台级入口 / 备份权限
# ============================================================

def test_platform_endpoint_whitelist():
    from app.admin import _is_platform_endpoint
    for ep in ('admin.oss_storage_index', 'admin.db_migrator_index',
               'admin.auto_translate_index', 'admin.analytics_index',
               'admin.backup_index', 'admin.monitor_index',
               'admin.plugin_index', 'admin.site_index', 'admin.logout'):
        assert _is_platform_endpoint(ep), ep
    for ep in ('admin.member_index', 'admin.tutorial_index',
               'admin.builder_index', 'admin.article_index', 'admin.dashboard'):
        assert not _is_platform_endpoint(ep), ep


def test_backup_requires_platform_ops(client, app):
    uid = _mk_role_user(app, 'v322-backup-user', ['system:backup'])
    _login(client, uid)
    assert client.get('/admin/backups').status_code == 403
    assert client.get('/admin/monitor').status_code == 403


# ============================================================
# 后台域名解析（v3.2.2 实测缺陷）
# ============================================================

def _resolve_admin_host(app, monkeypatch, host, session_site=None, user_id=None):
    """在模拟后台请求（指定 Host）下解析站点 id。"""
    from app import sites as sites_mod
    from flask import session
    monkeypatch.setattr(sites_mod, '_is_admin_request', lambda: True)
    with app.test_request_context('/admin/', headers={'Host': host}):
        if session_site is not None:
            session['admin_site_id'] = session_site
        if user_id is not None:
            session['_user_id'] = str(user_id)
        return sites_mod._resolve_site_id()


def test_admin_host_defaults_to_domain_site(app, monkeypatch):
    """用非默认站点域名登录后台：未显式选过站点时默认管理该域名站点。"""
    sid = _mk_site(app, slug='site-b', domain='b.example.com')
    assert _resolve_admin_host(app, monkeypatch, 'b.example.com') == sid
    # 带端口的 Host 同样生效
    assert _resolve_admin_host(app, monkeypatch, 'b.example.com:8080') == sid
    # 未配置域名的 Host 回退默认站点
    assert _resolve_admin_host(app, monkeypatch, 'other.example.com') == 0


def test_admin_host_subdomain_match(app, monkeypatch):
    sid = _mk_site(app, slug='site-b', subdomain='b')
    assert _resolve_admin_host(app, monkeypatch, 'b.example.com') == sid


def test_admin_explicit_session_choice_beats_host(app, monkeypatch):
    """用户已用切换器显式选择站点：session 优先，域名不得覆盖切换器。"""
    sid = _mk_site(app, slug='site-b', domain='b.example.com')
    assert _resolve_admin_host(app, monkeypatch, 'b.example.com',
                               session_site=0) == 0
    assert _resolve_admin_host(app, monkeypatch, 'b.example.com',
                               session_site=sid) == sid


def test_admin_host_denied_site_falls_back(app, monkeypatch):
    """当前域名站点无权访问：回退到可访问站点，不进入无权站点。"""
    sid = _mk_site(app, slug='site-b', domain='b.example.com')
    uid = _mk_role_user(app, 'v322-host-user', ['system:backup'])  # 仅绑定默认站 0
    assert _resolve_admin_host(app, monkeypatch, 'b.example.com',
                               user_id=uid) == 0
