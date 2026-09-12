"""v3.0.0 页面构建器 —— 后台路由 RBAC 与 API 契约测试。

角色矩阵：
- 匿名：全部后台入口 302 跳登录
- readonly_viewer：无 builder:manage → 403
- content_editor：builder:manage（可编辑/存草稿/预览），无 builder:publish
  （发布/回滚/删除 403）
- content_auditor：builder:manage + builder:publish 全放行
"""
import uuid

import pytest

from app.extensions import db
from tests.factories import make_user, make_column


def _role_client(app, role_code):
    """新客户端 + 指定预设角色用户（session 注入绕验证码）。"""
    from app.models.rbac import Role
    client = app.test_client()
    with app.app_context():
        user = make_user(
            username='bu_' + uuid.uuid4().hex[:10],
            role=Role.get_by_code(role_code))
        db.session.commit()
        uid = user.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True
    return client


def _make_page(app, scope='list', column_id=None):
    from app.builder import service
    with app.app_context():
        page, _ = service.get_or_create_page(scope, column_id)
        return page.id


def _heading(text=None):
    return {'root': [{
        'id': 'h_' + uuid.uuid4().hex[:8], 'type': 'heading',
        'props': {'text': text or 'RBAC标题', 'level': 2},
        'children': [], 'visibility': {}}]}


class TestAccessControl:
    def test_anonymous_redirects(self, client):
        for path in ('/admin/builder',
                     '/admin/builder/api/widgets?scope=home',
                     '/admin/builder/preview/1'):
            resp = client.get(path)
            assert resp.status_code == 302
            assert '/admin/login' in resp.headers['Location']

    def test_readonly_viewer_forbidden(self, app):
        c = _role_client(app, 'readonly_viewer')
        assert c.get('/admin/builder').status_code == 403
        pid = _make_page(app)
        assert c.get(f'/admin/builder/editor/{pid}').status_code == 403
        assert c.post(
            f'/admin/builder/api/pages/{pid}/draft',
            json={'layout': _heading()}).status_code == 403

    def test_editor_can_browse_and_edit_but_not_publish(self, app):
        c = _role_client(app, 'content_editor')
        assert c.get('/admin/builder').status_code == 200
        assert c.get(
            '/admin/builder/api/widgets?scope=home').status_code == 200

        pid = _make_page(app)
        assert c.get(
            f'/admin/builder/editor/{pid}').status_code == 200
        assert c.get(
            f'/admin/builder/api/pages/{pid}').status_code == 200

        # 草稿保存允许
        resp = c.post(f'/admin/builder/api/pages/{pid}/draft',
                      json={'layout': _heading('编辑草稿')})
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True

        # 发布 / 回滚 / 删除需要 builder:publish
        resp = c.post(f'/admin/builder/api/pages/{pid}/publish',
                      json={'layout': _heading()})
        assert resp.status_code == 403
        resp = c.post(f'/admin/builder/api/pages/{pid}/rollback',
                      json={'revision_id': 1})
        assert resp.status_code == 403
        resp = c.post(f'/admin/builder/pages/{pid}/delete')
        assert resp.status_code == 403

    def test_editor_invalid_draft_returns_400(self, app):
        c = _role_client(app, 'content_editor')
        pid = _make_page(app)
        resp = c.post(f'/admin/builder/api/pages/{pid}/draft',
                      json={'layout': {'root': [{'type': 'no-such-widget'}]}})
        assert resp.status_code == 400
        assert resp.get_json()['ok'] is False


class TestPublishWorkflow:
    def test_auditor_publish_revisions_rollback(self, app):
        c = _role_client(app, 'content_auditor')
        pid = _make_page(app)

        # 发布 v1
        resp = c.post(f'/admin/builder/api/pages/{pid}/publish',
                      json={'layout': _heading('版本一'), 'note': 'v1'})
        assert resp.status_code == 200
        rev1 = resp.get_json()['revision_id']

        # 发布 v2
        resp = c.post(f'/admin/builder/api/pages/{pid}/publish',
                      json={'layout': _heading('版本二'), 'note': 'v2'})
        assert resp.status_code == 200

        revs = c.get(f'/admin/builder/api/pages/{pid}/revisions').get_json()
        assert len(revs['revisions']) == 2

        # 回滚到 v1 → 立即生效并产生新快照
        resp = c.post(f'/admin/builder/api/pages/{pid}/rollback',
                      json={'revision_id': rev1})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        assert '版本一' in str(body['layout'])

        revs = c.get(f'/admin/builder/api/pages/{pid}/revisions').get_json()
        assert len(revs['revisions']) == 3

        # 回滚不存在的修订 → 400
        resp = c.post(f'/admin/builder/api/pages/{pid}/rollback',
                      json={'revision_id': 999999})
        assert resp.status_code == 400

    def test_publish_invalid_layout_400(self, app):
        c = _role_client(app, 'content_auditor')
        pid = _make_page(app)
        resp = c.post(f'/admin/builder/api/pages/{pid}/publish',
                      json={'layout': {'root': [{'type': 'evil'}]}})
        assert resp.status_code == 400

    def test_auditor_delete_fallback(self, app):
        c = _role_client(app, 'content_auditor')
        pid = _make_page(app)
        resp = c.post(f'/admin/builder/pages/{pid}/delete')
        assert resp.status_code == 302
        # 记录已删除，详情 404
        assert c.get(f'/admin/builder/api/pages/{pid}').status_code == 404

    def test_home_page_undeletable(self, app):
        c = _role_client(app, 'content_auditor')
        pid = _make_page(app, scope='home')
        resp = c.post(f'/admin/builder/pages/{pid}/delete',
                      follow_redirects=False)
        assert resp.status_code == 302
        # 记录仍然存在
        assert c.get(f'/admin/builder/api/pages/{pid}').status_code == 200


class TestCreateAndPreview:
    def test_create_page_flow(self, app):
        c = _role_client(app, 'content_editor')
        with app.app_context():
            col = make_column(slug='zbac_' + uuid.uuid4().hex[:8],
                              col_type='list')
            db.session.commit()
            cid = col.id
        resp = c.post('/admin/builder/pages/create',
                      data={'scope': 'list', 'column_id': cid})
        assert resp.status_code == 302
        assert '/admin/builder/editor/' in resp.headers['Location']

        # 重复创建 → 跳转到同一条记录
        resp2 = c.post('/admin/builder/pages/create',
                       data={'scope': 'list', 'column_id': cid})
        assert resp2.headers['Location'] == resp.headers['Location']

        # 非法作用域 → 回列表
        resp = c.post('/admin/builder/pages/create',
                      data={'scope': 'weird'})
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/admin/builder')

    def test_preview_requires_login_and_renders_markers(self, app):
        anon = app.test_client()
        pid = _make_page(app)
        assert anon.get(f'/admin/builder/preview/{pid}').status_code == 302

        c = _role_client(app, 'content_editor')
        # 先放一份草稿
        c.post(f'/admin/builder/api/pages/{pid}/draft',
               json={'layout': _heading('画布预览内容')})
        resp = c.get(f'/admin/builder/preview/{pid}')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-zbw-id' in html
        assert 'preview_bridge.js' in html
        assert '画布预览内容' in html
        # 生产标识不进入预览壳之外（预览页本身带编辑属性）
        assert 'zbw-preview-root' in html or 'data-zbw-root' in html

    def test_index_lists_unbuilt_columns(self, app):
        c = _role_client(app, 'content_editor')
        marker = 'ZBAC' + uuid.uuid4().hex[:8]
        with app.app_context():
            make_column(name=marker, slug='zbac_' + uuid.uuid4().hex[:8],
                        col_type='page')
            db.session.commit()
        html = c.get('/admin/builder').get_data(as_text=True)
        assert marker in html
