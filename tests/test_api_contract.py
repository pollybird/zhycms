"""API 契约测试（v2.6.2 W4）。

验证 /api/v1/ 端点的请求/响应契约：
- 统一响应包 {"code","message","data","meta"}，错误码与 HTTP 状态对应
- /site、/columns、/columns/<slug>、/columns/<slug>/articles、
  /articles/<aid> 的字段结构
- 门控：api_enable=off 全端点 404；api_token 缺失/错误 401
- CORS：api_cors_origins 白名单 / 通配
- 曝光规则：仅发布+未删除+启用栏目内容可见（草稿/删除/停用一律 404）
- 分页 meta 结构与 per_page 钳制（1..50）
"""
import uuid

import pytest

from app.models.workflow import STATUS_DRAFT, STATUS_PUBLISHED

contract = pytest.mark.contract


# ============================================================
# 数据助手（uuid 命名避开接口缓存串扰）
# ============================================================

def _col(app, col_type='list', enabled=True):
    from app.extensions import db
    from app.models.column import Column
    slug = 'ct-' + uuid.uuid4().hex[:8]
    with app.app_context():
        col = Column(name='契约栏目', slug=slug, type=col_type,
                     is_enabled=enabled, is_deleted=False)
        db.session.add(col)
        db.session.commit()
        cid = col.id
    return slug, cid


def _article(app, cid, status=STATUS_PUBLISHED, deleted=False, title=None):
    from app.extensions import db
    from app.models.article import Article
    with app.app_context():
        a = Article(title=title or '契约文章', column_id=cid, status=status,
                    content='<p>契约正文</p>', author='契约作者',
                    is_deleted=deleted, sort_order=0,
                    is_enabled=(status == STATUS_PUBLISHED))
        db.session.add(a)
        db.session.commit()
        return a.id


def _set_setting(app, key, value):
    from app.models.setting import Setting
    from app.extensions import db
    with app.app_context():
        Setting.set(key, value)
        db.session.commit()


def _clear_cache(app):
    with app.app_context():
        from app.extensions import cache
        cache.clear()


def _assert_envelope(data):
    """统一响应包结构契约。"""
    assert set(data.keys()) == {'code', 'message', 'data', 'meta'}
    assert isinstance(data['code'], int)
    assert isinstance(data['message'], str)


def _assert_column_brief(item):
    assert {'id', 'name', 'slug', 'type', 'summary',
            'sort_order', 'url'} <= set(item.keys())


def _assert_article_summary(item):
    assert {'id', 'title', 'summary', 'cover', 'author', 'source',
            'published_at', 'viewed', 'url',
            'column'} <= set(item.keys())
    assert {'id', 'name', 'slug'} <= set(item['column'].keys())


# ============================================================
# 响应包与端点结构
# ============================================================

@contract
class TestEnvelope:
    """统一响应包契约。"""

    def test_success_envelope(self, client):
        resp = client.get('/api/v1/site')
        assert resp.status_code == 200
        _assert_envelope(resp.get_json())
        assert resp.get_json()['code'] == 0

    def test_error_envelope_404(self, client):
        resp = client.get('/api/v1/articles/99999999')
        assert resp.status_code == 404
        data = resp.get_json()
        _assert_envelope(data)
        assert data['code'] == 404
        assert data['data'] is None


@contract
class TestSiteContract:
    """/site 字段契约。"""

    def test_site_fields(self, app, client):
        _set_setting(app, 'site_name', '契约企业')
        _clear_cache(app)
        resp = client.get('/api/v1/site')
        data = resp.get_json()['data']
        assert {'name', 'subtitle', 'logo', 'copyright', 'seo',
                'nav'} <= set(data.keys())
        assert data['name'] == '契约企业'
        assert {'title', 'keywords', 'description'} <= set(data['seo'].keys())
        for item in data['nav']:
            _assert_column_brief(item)


@contract
class TestColumnsContract:
    """/columns 系列字段契约。"""

    def test_columns_list_and_filter(self, app, client):
        list_slug, _ = _col(app, 'list')
        page_slug, _ = _col(app, 'page')
        link_slug, _ = _col(app, 'link')
        _clear_cache(app)

        resp = client.get('/api/v1/columns')
        data = resp.get_json()['data']
        slugs = {c['slug'] for c in data}
        assert {list_slug, page_slug, link_slug} <= slugs  # link 类型也在列表中
        for item in data:
            _assert_column_brief(item)

        # type 过滤：page / link 各自精确命中
        resp = client.get('/api/v1/columns?type=page')
        assert {c['slug'] for c in resp.get_json()['data']} == {page_slug}
        resp = client.get('/api/v1/columns?type=link')
        assert {c['slug'] for c in resp.get_json()['data']} == {link_slug}

    def test_column_detail_page_type(self, app, client):
        slug, _ = _col(app, 'page')
        _clear_cache(app)
        resp = client.get(f'/api/v1/columns/{slug}')
        assert resp.status_code == 200
        data = resp.get_json()['data']
        _assert_column_brief(data)
        assert 'page_content' in data
        assert 'fields' in data
        assert {'title', 'keywords', 'description'} <= set(data['seo'].keys())

    def test_disabled_column_404(self, app, client):
        slug, _ = _col(app, 'list', enabled=False)
        _clear_cache(app)
        resp = client.get(f'/api/v1/columns/{slug}')
        assert resp.status_code == 404
        assert resp.get_json()['code'] == 404


@contract
class TestArticlesContract:
    """文章列表/详情字段契约与曝光规则。"""

    def test_article_list_pagination_meta(self, app, client):
        slug, cid = _col(app, 'list')
        for i in range(3):
            _article(app, cid, title=f'分页文章{i}')
        _clear_cache(app)
        resp = client.get(f'/api/v1/columns/{slug}/articles?per_page=2&page=1')
        data = resp.get_json()
        assert data['code'] == 0
        meta = data['meta']
        assert {'page', 'per_page', 'total', 'total_pages'} <= set(meta.keys())
        assert meta == {'page': 1, 'per_page': 2, 'total': 3, 'total_pages': 2}
        assert len(data['data']) == 2
        for item in data['data']:
            _assert_article_summary(item)

    def test_per_page_clamped(self, app, client):
        slug, cid = _col(app, 'list')
        _article(app, cid)
        _clear_cache(app)
        resp = client.get(f'/api/v1/columns/{slug}/articles?per_page=999')
        assert resp.get_json()['meta']['per_page'] == 50

    def test_keyword_filter(self, app, client):
        slug, cid = _col(app, 'list')
        _article(app, cid, title='独特关键词甲')
        _article(app, cid, title='普通文章乙')
        _clear_cache(app)
        resp = client.get(f'/api/v1/columns/{slug}/articles?keyword=独特关键词甲')
        data = resp.get_json()['data']
        assert len(data) == 1
        assert data[0]['title'] == '独特关键词甲'

    def test_draft_and_deleted_not_exposed(self, app, client):
        """草稿与已删除文章不出现在列表与详情。"""
        slug, cid = _col(app, 'list')
        draft_id = _article(app, cid, status=STATUS_DRAFT)
        deleted_id = _article(app, cid, deleted=True)
        _clear_cache(app)

        resp = client.get(f'/api/v1/columns/{slug}/articles')
        ids = {a['id'] for a in resp.get_json()['data']}
        assert draft_id not in ids and deleted_id not in ids

        assert client.get(f'/api/v1/articles/{draft_id}').status_code == 404
        assert client.get(f'/api/v1/articles/{deleted_id}').status_code == 404

    def test_article_detail_contract(self, app, client):
        _, cid = _col(app, 'list')
        aid = _article(app, cid)
        _clear_cache(app)
        resp = client.get(f'/api/v1/articles/{aid}')
        assert resp.status_code == 200
        data = resp.get_json()['data']
        _assert_article_summary(data)
        assert 'content' in data and '契约正文' in data['content']
        assert {'title', 'keywords', 'description'} <= set(data['seo'].keys())
        assert isinstance(data['fields'], list)
        assert data['prev'] is None and data['next'] is None

    def test_disabled_column_articles_404(self, app, client):
        slug, cid = _col(app, 'list', enabled=False)
        _article(app, cid)
        _clear_cache(app)
        assert client.get(f'/api/v1/columns/{slug}/articles').status_code == 404


# ============================================================
# 门控与 CORS
# ============================================================

@contract
class TestGating:
    """api_enable / api_token 门控契约。"""

    def test_api_enable_off_returns_404_for_all(self, app, client):
        _set_setting(app, 'api_enable', 'off')
        _clear_cache(app)
        for path in ('/api/v1/site', '/api/v1/columns'):
            resp = client.get(path)
            assert resp.status_code == 404
            assert resp.get_json()['code'] == 404
        _set_setting(app, 'api_enable', 'on')
        _clear_cache(app)
        assert client.get('/api/v1/site').status_code == 200

    def test_api_token_required(self, app, client):
        _set_setting(app, 'api_token', 'secret-token-123')
        _clear_cache(app)
        # 缺失 token
        resp = client.get('/api/v1/site')
        assert resp.status_code == 401
        assert resp.get_json()['code'] == 401
        # 错误 token
        resp = client.get('/api/v1/site',
                          headers={'X-API-Token': 'wrong'})
        assert resp.status_code == 401
        # 正确 token
        resp = client.get('/api/v1/site',
                          headers={'X-API-Token': 'secret-token-123'})
        assert resp.status_code == 200
        _set_setting(app, 'api_token', '')
        _clear_cache(app)


@contract
class TestCors:
    """CORS 响应头契约。"""

    def test_no_cors_by_default(self, app, client):
        _clear_cache(app)
        resp = client.get('/api/v1/site')
        assert 'Access-Control-Allow-Origin' not in resp.headers

    def test_wildcard_origin(self, app, client):
        _set_setting(app, 'api_cors_origins', '*')
        _clear_cache(app)
        resp = client.get('/api/v1/site', headers={'Origin': 'https://a.com'})
        assert resp.headers.get('Access-Control-Allow-Origin') == '*'
        _set_setting(app, 'api_cors_origins', '')
        _clear_cache(app)

    def test_whitelist_origin(self, app, client):
        _set_setting(app, 'api_cors_origins', 'https://a.com, https://b.com')
        _clear_cache(app)
        # 白名单内：回显 Origin
        resp = client.get('/api/v1/site', headers={'Origin': 'https://a.com'})
        assert resp.headers.get('Access-Control-Allow-Origin') == 'https://a.com'
        # 白名单外：不追加头
        resp = client.get('/api/v1/site', headers={'Origin': 'https://evil.com'})
        assert 'Access-Control-Allow-Origin' not in resp.headers
        _set_setting(app, 'api_cors_origins', '')
        _clear_cache(app)
