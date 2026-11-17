"""v3.2.0 站群（site group）站点隔离测试。

覆盖：
  - 默认站点恒为 0（无请求上下文 / 未知 Host 回退）
  - Host 精确域名与泛解析子域站点解析
  - 后台 ?site= 切换与会话保持
  - 栏目 slug 站点内唯一、栏目树按站点隔离
  - REST API 栏目/文章按站点隔离
  - 站点化配置读取与全局键（member_scope）不被站点覆盖
  - 站点关闭后前台 503
  - 站点管理 CRUD（超管）
"""
import pytest

from app.extensions import db
from app.models.site import Site, DEFAULT_SITE_ID

pytestmark = pytest.mark.sites


def _mk_site(app, slug='site-b', name='站点B', domain=None, subdomain=None,
             status='open', theme=None):
    """创建测试站点，返回 id。"""
    with app.app_context():
        site = Site(name=name, slug=slug, domain=domain, subdomain=subdomain,
                    status=status, theme=theme)
        db.session.add(site)
        db.session.commit()
        return site.id


@pytest.fixture(autouse=True)
def _clean_sites(app):
    """用例结束后清理非默认站点及其站点内内容/配置，避免污染其他用例。"""
    yield
    with app.app_context():
        from app.models.article import Article
        from app.models.column import Column
        from app.models.fragment import Fragment
        from app.models.rbac import UserSitePermission
        from app.models.setting import Setting
        Article.query.filter(Article.site_id != 0).delete()
        Column.query.filter(Column.site_id != 0).delete()
        Fragment.query.filter(Fragment.site_id != 0).delete()
        UserSitePermission.query.delete()
        Setting.query.filter(Setting.site_id != 0).delete()
        Site.query.filter(Site.id != 0).delete()
        db.session.commit()


# ============================================================
# 站点解析
# ============================================================

def test_default_site_constant(app):
    """无请求上下文时站点 id 恒为默认站点 0。"""
    with app.app_context():
        from app.sites import current_site_id
        assert DEFAULT_SITE_ID == 0
        assert current_site_id() == 0


def test_resolve_by_domain(app):
    """Host 精确匹配 sites.domain。"""
    sid = _mk_site(app, slug='site-b', domain='b.example.com')
    with app.test_request_context('/', headers={'Host': 'b.example.com'}):
        from app.sites import select_site, current_site_id
        assert select_site() is None
        assert current_site_id() == sid


def test_resolve_by_subdomain(app):
    """泛解析子域首标签匹配 sites.subdomain。"""
    sid = _mk_site(app, slug='site-c', subdomain='c')
    with app.test_request_context('/', headers={'Host': 'c.main.com'}):
        from app.sites import select_site, current_site_id
        select_site()
        assert current_site_id() == sid


def test_unknown_host_falls_back_default(app):
    """未命中任何站点时回退默认站点 0。"""
    _mk_site(app, slug='site-b', domain='b.example.com')
    with app.test_request_context('/', headers={'Host': 'unknown.example.com'}):
        from app.sites import select_site, current_site_id
        select_site()
        assert current_site_id() == DEFAULT_SITE_ID


def test_admin_switch_site(app, admin_client):
    """后台切换器写入 session，后续后台请求保持该站点。"""
    sid = _mk_site(app, slug='site-b')
    resp = admin_client.post('/admin/sites/switch', data={'site_id': sid})
    assert resp.status_code in (200, 302)
    with admin_client.session_transaction() as sess:
        assert sess.get('admin_site_id') == sid

    # 切换后后台页面可正常访问（会话站点被 select_site 接受）
    assert admin_client.get('/admin/sites').status_code == 200


# ============================================================
# 内容维度隔离
# ============================================================

def test_column_slug_reusable_per_site(app):
    """相同 slug 可在不同站点共存，栏目树按站点返回。"""
    sid = _mk_site(app, slug='site-b')
    with app.app_context():
        from app.models.column import Column
        db.session.add(Column(name='关于A', slug='sg-about', type='page',
                              site_id=0, is_enabled=True, is_deleted=False))
        db.session.add(Column(name='关于B', slug='sg-about', type='page',
                              site_id=sid, is_enabled=True, is_deleted=False))
        db.session.commit()

        tree_default = Column.get_tree(site_id=0)
        tree_b = Column.get_tree(site_id=sid)
        default_about = [c for c in tree_default if c.slug == 'sg-about']
        site_b_about = [c for c in tree_b if c.slug == 'sg-about']
        assert len(default_about) == 1
        assert len(site_b_about) == 1
        assert default_about[0].id != site_b_about[0].id
        assert {c.site_id for c in tree_b} == {sid}


def test_api_columns_isolated_by_host(app, client):
    """栏目 API 仅返回当前 Host 对应站点的栏目。"""
    sid = _mk_site(app, slug='site-b', domain='b.example.com')
    with app.app_context():
        from app.models.column import Column
        db.session.add(Column(name='A新闻', slug='sg-a-news', type='list',
                              site_id=0, is_enabled=True, is_deleted=False))
        db.session.add(Column(name='B新闻', slug='sg-b-news', type='list',
                              site_id=sid, is_enabled=True, is_deleted=False))
        db.session.commit()

    resp = client.get('/api/v1/columns', headers={'Host': 'b.example.com'})
    assert resp.status_code == 200
    slugs = {c['slug'] for c in resp.get_json()['data']}
    assert 'sg-b-news' in slugs
    assert 'sg-a-news' not in slugs


def test_article_api_cross_site_404(app, client):
    """其他站点的文章详情不可见（404），本站点可见。"""
    sid = _mk_site(app, slug='site-b', domain='b.example.com')
    with app.app_context():
        from app.models.article import Article
        from app.models.column import Column
        from app.models.workflow import STATUS_PUBLISHED
        col = Column(name='B新闻', slug='sg-b-news2', type='list',
                     site_id=sid, is_enabled=True, is_deleted=False)
        db.session.add(col)
        db.session.flush()
        article = Article(title='B站文章', column_id=col.id, site_id=sid,
                          status=STATUS_PUBLISHED, is_enabled=True,
                          is_deleted=False)
        db.session.add(article)
        db.session.commit()
        aid = article.id

    assert client.get(f'/api/v1/articles/{aid}').status_code == 404
    resp = client.get(f'/api/v1/articles/{aid}',
                      headers={'Host': 'b.example.com'})
    assert resp.status_code == 200


# ============================================================
# 站点化配置
# ============================================================

def test_setting_site_override(app):
    """站点键按当前站点读取覆盖值。"""
    sid = _mk_site(app, slug='site-b', domain='b.example.com')
    with app.app_context():
        from app.models.setting import Setting
        Setting.set_site_override('site_name', 'B站名', sid)
        db.session.commit()

    with app.test_request_context('/', headers={'Host': 'b.example.com'}):
        from app.models.setting import Setting
        from app.sites import select_site
        select_site()
        assert Setting.get('site_name') == 'B站名'


def test_global_key_ignores_site_override(app):
    """全局键（member_scope）始终读全局值，站点行不生效。"""
    sid = _mk_site(app, slug='site-b', domain='b.example.com')
    with app.app_context():
        from app.models.setting import Setting
        Setting.set_site_override('member_scope', 'isolated', sid)
        db.session.commit()

    with app.test_request_context('/', headers={'Host': 'b.example.com'}):
        from app.models.setting import Setting
        from app.sites import select_site
        select_site()
        assert Setting.get('member_scope') == 'shared'


# ============================================================
# 站点状态
# ============================================================

def test_closed_site_returns_503(app, client):
    """站点 status=closed 时前台返回 503。"""
    _mk_site(app, slug='site-b', domain='b.example.com', status='closed')
    resp = client.get('/', headers={'Host': 'b.example.com'})
    assert resp.status_code == 503


# ============================================================
# 后台站点管理
# ============================================================

def test_admin_site_list_requires_permission(app, client):
    """未登录访问站点管理跳转登录页。"""
    resp = client.get('/admin/sites')
    assert resp.status_code in (302, 401)


def test_admin_create_site(app, admin_client):
    """超管可创建站点，重复 slug 被拒绝。"""
    resp = admin_client.post('/admin/sites/create', data={
        'name': '新建站点', 'slug': 'site-new', 'status': 'open',
    })
    assert resp.status_code in (200, 302)

    with app.app_context():
        site = Site.query.filter_by(slug='site-new').first()
        assert site is not None
        assert site.is_default is False

    # 重复 slug：不新增站点
    admin_client.post('/admin/sites/create', data={
        'name': '重复站点', 'slug': 'site-new', 'status': 'open',
    })
    with app.app_context():
        assert Site.query.filter_by(slug='site-new').count() == 1


def test_user_site_permission_saved(app, admin_client):
    """账号编辑页可绑定站点专属权限（可审核/可发布）。"""
    from app.models.rbac import UserSitePermission
    from app.models.user import User

    sid = _mk_site(app, slug='site-b')
    resp = admin_client.post('/admin/users/create', data={
        'username': 'sguser',
        'password': 'Abcdef123456!',
        'confirm_password': 'Abcdef123456!',
        'is_active_flag': 'on',
        'site_ids[]': str(sid),
        'site_can_review_ids[]': [str(sid)],
        'site_can_publish_ids[]': [str(sid)],
    })
    assert resp.status_code in (200, 302)

    with app.app_context():
        user = User.query.filter_by(username='sguser').first()
        assert user is not None
        perm = UserSitePermission.query.filter_by(
            user_id=user.id, site_id=sid).first()
        assert perm is not None
        assert perm.can_review is True
        assert perm.can_publish is True
        # 清理测试账号（避免污染其他用例）
        UserSitePermission.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()


def test_audit_page_supports_site_filter(app, admin_client):
    """审计列表渲染正常且支持按站点筛选。"""
    sid = _mk_site(app, slug='site-b')
    assert admin_client.get('/admin/audit-logs').status_code == 200
    resp = admin_client.get(f'/admin/audit-logs?site_id={sid}')
    assert resp.status_code == 200
