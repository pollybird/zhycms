"""v3.2.11 OpenAPI 契约、写端点与 SDK 测试。"""
import sys
from pathlib import Path

import pytest
import requests

from app.extensions import db

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'sdk'))

pytestmark = pytest.mark.api

USER_PREFIX = 'v3211'
COL_SLUG_PREFIX = 'v3211-'


# ============================================================
# 辅助
# ============================================================

def _set(app, key, value):
    from app.models.setting import Setting
    with app.app_context():
        Setting.set(key, value)
        db.session.commit()


def _jwt(app, uid, token_type='access'):
    with app.app_context():
        from app.utils.api_jwt import create_token
        return create_token(str(uid), token_type)


def _bearer(token):
    return {'Authorization': f'Bearer {token}'}


def _mk_user(app, username, codes=(), is_super=False):
    """创建用户，可选授予权限点（全局角色，不绑定站点）。"""
    from app.models.rbac import Role, RolePermission, Permission, UserRole
    from app.models.user import User
    with app.app_context():
        Permission.ensure_presets()
        user = User(username=f'{USER_PREFIX}-{username}', is_super=is_super,
                    is_deleted=False)
        user.set_password('Abcdef123456!')
        db.session.add(user)
        db.session.flush()
        if codes:
            role = Role(code=f'{USER_PREFIX}-{username}', name=username)
            db.session.add(role)
            db.session.flush()
            for code in codes:
                db.session.add(RolePermission(role_id=role.id,
                                              permission_code=code))
            db.session.add(UserRole(user_id=user.id, role_id=role.id))
        db.session.commit()
        return user.id


def _mk_column(app, slug='v3211-col', name='测试栏目'):
    from app.models.column import Column
    with app.app_context():
        col = Column(name=name, slug=slug, type='list', is_enabled=True,
                     is_deleted=False)
        db.session.add(col)
        db.session.commit()
        return col.id


def _mk_article(app, column_id, title='测试文章', site_id=0):
    from app.models.article import Article
    from app.constants import Workflow
    with app.app_context():
        article = Article(title=title, column_id=column_id, site_id=site_id,
                          status=Workflow.STATUS_DRAFT, content='正文',
                          is_enabled=False, is_deleted=False)
        db.session.add(article)
        db.session.commit()
        return article.id


@pytest.fixture(autouse=True)
def _isolate(app):
    """每个用例前重置限流与开关，结束后清理 v3211 造的数据。"""
    from app.extensions import limiter
    with app.app_context():
        try:
            limiter.reset()
        except Exception:
            pass
        from app.models.setting import Setting
        Setting.set('api_enable', 'on')
        Setting.set('api_auth_mode', 'both')
        Setting.set('api_write_enable', 'off')
        db.session.commit()
    yield
    from app.models.article import (
        Article, ArticleFieldValue, ArticleTranslation,
    )
    from app.models.column import (
        Column, ColumnField, ColumnFieldValue, ColumnTranslation,
    )
    from app.models.fragment import Fragment
    from app.models.rbac import Role, RolePermission, UserRole
    from app.models.site import Site
    from app.models.user import User
    from app.models.workflow import ArticleVersion
    with app.app_context():
        try:
            limiter.reset()
        except Exception:
            pass
        col_ids = [c.id for c in Column.query.filter(
            Column.slug.like(f'{COL_SLUG_PREFIX}%')).all()]
        if col_ids:
            aids = [a.id for a in Article.query.filter(
                Article.column_id.in_(col_ids)).all()]
            if aids:
                ArticleFieldValue.query.filter(
                    ArticleFieldValue.article_id.in_(aids)).delete(
                        synchronize_session=False)
                ArticleTranslation.query.filter(
                    ArticleTranslation.article_id.in_(aids)).delete(
                        synchronize_session=False)
                ArticleVersion.query.filter(
                    ArticleVersion.article_id.in_(aids)).delete(
                        synchronize_session=False)
                Article.query.filter(Article.id.in_(aids)).delete(
                    synchronize_session=False)
            ColumnFieldValue.query.filter(
                ColumnFieldValue.column_id.in_(col_ids)).delete(
                    synchronize_session=False)
            ColumnTranslation.query.filter(
                ColumnTranslation.column_id.in_(col_ids)).delete(
                    synchronize_session=False)
            ColumnField.query.filter(
                ColumnField.column_id.in_(col_ids)).delete(
                    synchronize_session=False)
        Column.query.filter(Column.slug.like(f'{COL_SLUG_PREFIX}%')).delete(
            synchronize_session=False)
        Fragment.query.filter(Fragment.slug.like(f'{COL_SLUG_PREFIX}%')).delete(
            synchronize_session=False)
        uids = [u.id for u in User.query.filter(
            User.username.like(f'{USER_PREFIX}-%')).all()]
        if uids:
            from app.models.rbac import UserColumnPermission
            UserColumnPermission.query.filter(
                UserColumnPermission.user_id.in_(uids)).delete(
                    synchronize_session=False)
            UserRole.query.filter(UserRole.user_id.in_(uids)).delete(
                synchronize_session=False)
            User.query.filter(User.id.in_(uids)).delete(synchronize_session=False)
        role_ids = [r.id for r in Role.query.filter(
            Role.code.like(f'{USER_PREFIX}-%')).all()]
        if role_ids:
            RolePermission.query.filter(
                RolePermission.role_id.in_(role_ids)).delete(
                    synchronize_session=False)
        Role.query.filter(Role.code.like(f'{USER_PREFIX}-%')).delete(
            synchronize_session=False)
        Site.query.filter(Site.slug.like(f'{USER_PREFIX}-%')).delete(
            synchronize_session=False)
        from app.models.setting import Setting
        Setting.set('api_enable', 'on')
        Setting.set('api_write_enable', 'off')
        db.session.commit()


def _admin_id(app):
    from app.models.user import User
    with app.app_context():
        return User.query.filter_by(username='admin').first().id


# ============================================================
# OpenAPI 契约
# ============================================================

def test_openapi_spec_covers_all_routes(app):
    """路由与 spec 双向一致。"""
    from app.api.openapi import OPENAPI_SKIP, _normalize_path, build_spec, iter_api_rules
    spec = build_spec(app)
    paths = spec['paths']
    for rule, methods, endpoint, _meta in iter_api_rules(app):
        if endpoint in OPENAPI_SKIP:
            continue
        path = _normalize_path(rule.rule)
        for method in methods:
            assert method.lower() in paths.get(path, {}), f'{method} {path} 未覆盖'


def test_openapi_skip_requires_reason():
    """排除项必须写明原因。"""
    from app.api import openapi as mod
    source = Path(mod.__file__).read_text(encoding='utf-8')
    for endpoint in mod.OPENAPI_SKIP:
        assert f"'{endpoint}'" in source


def test_openapi_endpoint_gated_by_api_enable(app, client):
    """api_enable=off 时 openapi.json 也 404。"""
    _set(app, 'api_enable', 'off')
    assert client.get('/api/v1/openapi.json').status_code == 404
    _set(app, 'api_enable', 'on')
    resp = client.get('/api/v1/openapi.json')
    assert resp.status_code == 200
    assert resp.get_json()['openapi'] == '3.0.3'


# ============================================================
# 写端点门控与权限
# ============================================================

def test_write_disabled_returns_404(app, client):
    """写开关默认关闭时，写端点返回 404。"""
    col_id = _mk_column(app)
    resp = client.post('/api/v1/articles', headers=_bearer(_jwt(app, _admin_id(app))),
                       json={'column_id': col_id, 'title': 'T'})
    assert resp.status_code == 404


def test_write_rejects_static_token(app, client):
    """开启写端点后，静态 X-API-Token 不能调用写接口。"""
    _set(app, 'api_write_enable', 'on')
    col_id = _mk_column(app)
    resp = client.post('/api/v1/articles', headers={'X-API-Token': 'any'},
                       json={'column_id': col_id, 'title': 'T'})
    assert resp.status_code == 403


def test_write_requires_bearer_jwt(app, client):
    """开启写端点后，缺少 Bearer JWT 一律 403。"""
    _set(app, 'api_write_enable', 'on')
    col_id = _mk_column(app)
    resp = client.post('/api/v1/articles',
                       json={'column_id': col_id, 'title': 'T'})
    assert resp.status_code == 403


def test_write_permission_denied(app, client):
    """JWT 有效但无 content:create 权限时 403。"""
    _set(app, 'api_write_enable', 'on')
    col_id = _mk_column(app)
    uid = _mk_user(app, 'no-perm')
    resp = client.post('/api/v1/articles', headers=_bearer(_jwt(app, uid)),
                       json={'column_id': col_id, 'title': 'T'})
    assert resp.status_code == 403


def test_write_cross_site_404(app, client):
    """跨站点资源按不存在处理（404）。"""
    from app.models.column import Column
    from app.models.site import Site
    with app.app_context():
        site = Site(name='站点X', slug=f'{USER_PREFIX}-x', status='open')
        db.session.add(site)
        db.session.commit()
        sid = site.id
        col = Column(name='站内栏目', slug=f'{COL_SLUG_PREFIX}x', type='list',
                     is_enabled=True, is_deleted=False, site_id=sid)
        db.session.add(col)
        db.session.commit()
        col_id = col.id
    article_id = _mk_article(app, col_id, title='跨站文章', site_id=sid)
    _set(app, 'api_write_enable', 'on')
    resp = client.delete(f'/api/v1/articles/{article_id}',
                         headers=_bearer(_jwt(app, _admin_id(app))))
    assert resp.status_code == 404


# ============================================================
# 内容写端点语义
# ============================================================

def test_create_article_defaults_to_draft(app, client):
    """未指定 status 时创建为草稿。"""
    _set(app, 'api_write_enable', 'on')
    col_id = _mk_column(app)
    resp = client.post('/api/v1/articles', headers=_bearer(_jwt(app, _admin_id(app))),
                       json={'column_id': col_id, 'title': '新文章'})
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['status'] == 'draft'
    assert data['column_id'] == col_id


def test_update_published_requires_publish_permission(app, client):
    """无栏目发布标志时不允许直接置为已发布。"""
    from app.models.rbac import UserColumnPermission
    _set(app, 'api_write_enable', 'on')
    col_id = _mk_column(app)
    article_id = _mk_article(app, col_id)
    uid = _mk_user(app, 'editor', codes=['content:edit'])
    with app.app_context():
        db.session.add(UserColumnPermission(user_id=uid, column_id=col_id,
                                            can_publish=False))
        db.session.commit()
    resp = client.put(f'/api/v1/articles/{article_id}', headers=_bearer(_jwt(app, uid)),
                      json={'title': '改标题', 'status': 'published'})
    assert resp.status_code == 403


def test_delete_article_updates_search_index(app, client, monkeypatch):
    """软删除文章并同步移除搜索索引。"""
    _set(app, 'api_write_enable', 'on')
    col_id = _mk_column(app)
    article_id = _mk_article(app, col_id)
    removed = []
    monkeypatch.setattr('app.api.write.unindex_article',
                        lambda aid: removed.append(aid))
    resp = client.delete(f'/api/v1/articles/{article_id}',
                         headers=_bearer(_jwt(app, _admin_id(app))))
    assert resp.status_code == 200
    assert removed == [article_id]
    from app.models.article import Article
    with app.app_context():
        assert db.session.get(Article, article_id).is_deleted is True


def test_create_column_with_json_body(app, client):
    """JSON 请求体可创建栏目（save_column 需要 MultiDict 的 getlist）。"""
    _set(app, 'api_write_enable', 'on')
    resp = client.post('/api/v1/columns', headers=_bearer(_jwt(app, _admin_id(app))),
                       json={'name': 'API 栏目', 'slug': 'v3211-api',
                             'type': 'list', 'summary': '摘要'})
    assert resp.status_code == 200
    data = resp.get_json()['data']
    from app.models.column import Column
    with app.app_context():
        col = db.session.get(Column, data['id'])
        assert col.slug == 'v3211-api'
        assert col.is_enabled is True


def test_update_column_preserves_custom_fields(app, client):
    """更新栏目不会清空 API 未暴露的自定义字段。"""
    from app.models.column import Column, ColumnField
    _set(app, 'api_write_enable', 'on')
    col_id = _mk_column(app, slug='v3211-upd', name='旧名称')
    with app.app_context():
        db.session.add(ColumnField(column_id=col_id, field_key='author',
                                   label='作者', field_type='text',
                                   is_deleted=False))
        db.session.commit()
    resp = client.put(f'/api/v1/columns/{col_id}',
                      headers=_bearer(_jwt(app, _admin_id(app))),
                      json={'name': '新名称', 'slug': 'v3211-upd', 'type': 'list'})
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(Column, col_id).name == '新名称'
        kept = ColumnField.query.filter_by(column_id=col_id,
                                           field_key='author').first()
        assert kept is not None and kept.is_deleted is False


def test_delete_column_with_children_conflict(app, client):
    """栏目下有子栏目时删除返回 409。"""
    _set(app, 'api_write_enable', 'on')
    parent_id = _mk_column(app, slug='v3211-parent', name='父栏目')
    from app.models.column import Column
    with app.app_context():
        db.session.add(Column(name='子栏目', slug='v3211-child', type='list',
                              parent_id=parent_id, is_enabled=True,
                              is_deleted=False))
        db.session.commit()
    resp = client.delete(f'/api/v1/columns/{parent_id}',
                         headers=_bearer(_jwt(app, _admin_id(app))))
    assert resp.status_code == 409


# ============================================================
# 表单与站点计量
# ============================================================

def test_form_submissions_requires_jwt_and_permission(app, client):
    """表单提交：无 JWT 401；有 JWT 无权限 403。"""
    _set(app, 'api_write_enable', 'on')
    assert client.get('/api/v1/forms/demo/submissions').status_code == 401
    uid = _mk_user(app, 'formless')
    resp = client.get('/api/v1/forms/demo/submissions',
                      headers=_bearer(_jwt(app, uid)))
    assert resp.status_code == 403


def test_metrics_requires_superadmin(app, client):
    """站点计量仅超管可读。"""
    from app.models.site import Site
    with app.app_context():
        site = Site(name='计量站', slug=f'{USER_PREFIX}-m', status='open')
        db.session.add(site)
        db.session.commit()
        sid = site.id
    uid = _mk_user(app, 'metrics')
    assert client.get(f'/api/v1/sites/{sid}/metrics',
                      headers=_bearer(_jwt(app, uid))).status_code == 403
    resp = client.get(f'/api/v1/sites/{sid}/metrics',
                      headers=_bearer(_jwt(app, _admin_id(app))))
    assert resp.status_code == 200
    assert resp.get_json()['data'] == []


# ============================================================
# SDK（mock transport，不发真实请求）
# ============================================================

class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError('not json')
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(responses):
    from zhycms_sdk import Client
    session = _FakeSession(responses)
    return Client('https://example.com', token='old', refresh_token='refresh-token',
                  session=session), session


def test_sdk_client_parses_envelope():
    """成功包返回 data，失败包抛 ZhyCMSAPIError。"""
    from zhycms_sdk import ZhyCMSAPIError
    client, _ = _client([_FakeResponse(payload={'code': 0, 'data': {'ok': 1}})])
    assert client.get('/api/v1/site')['data'] == {'ok': 1}

    client, _ = _client([_FakeResponse(status_code=403,
                                       payload={'code': 403, 'message': '禁止'})])
    with pytest.raises(ZhyCMSAPIError) as exc:
        client.get('/api/v1/site')
    assert exc.value.status == 403 and exc.value.message == '禁止'


def test_sdk_refresh_once_on_401():
    """access token 401 时刷新一次并重放请求。"""
    client, session = _client([
        _FakeResponse(status_code=401, payload={'code': 401, 'message': '过期'}),
        _FakeResponse(payload={'code': 0, 'data': {'access_token': 'new'}}),
        _FakeResponse(payload={'code': 0, 'data': {'ok': 1}}),
    ])
    assert client.get('/api/v1/site')['data'] == {'ok': 1}
    assert len(session.calls) == 3
    assert session.calls[1][0] == 'POST'
    assert session.calls[1][1].endswith('/api/v1/auth/refresh')
    assert session.calls[1][2]['headers']['Authorization'] == 'Bearer refresh-token'
    assert client.token == 'new'


def test_sdk_no_retry_on_post():
    """写请求遇到网络错误不重试。"""
    from zhycms_sdk import ZhyCMSAPIError
    client, session = _client([requests.ConnectionError('boom')])
    with pytest.raises(ZhyCMSAPIError):
        client.post('/api/v1/articles', json={'title': 'T'})
    assert len(session.calls) == 1


def test_sdk_pagination_helper():
    """分页辅助正确读取 meta。"""
    from zhycms_sdk import Page
    page = Page.from_payload({
        'code': 0, 'data': [1, 2],
        'meta': {'page': 2, 'per_page': 10, 'total': 25, 'total_pages': 3},
    })
    assert page.items == [1, 2]
    assert (page.page, page.per_page, page.total, page.total_pages) == (2, 10, 25, 3)
