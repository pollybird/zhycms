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

    def test_widgets_api_serves_style_schema(self, app):
        c = _role_client(app, 'content_editor')
        data = c.get('/admin/builder/api/widgets?scope=home').get_json()
        keys = {f['key'] for f in data['style_schema']}
        assert {'page_bg', 'footer_bg', 'heading_color',
                'border_width', 'shadow'} <= keys


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

    def test_new_page_auto_loads_handwritten_equivalent_layout(self, app):
        """新建构建页应自动载入与手写模板等价的默认布局，而非空白画布。"""
        c = _role_client(app, 'content_editor')

        def _create(scope, column_id=None):
            data = {'scope': scope}
            if column_id is not None:
                data['column_id'] = column_id
            resp = c.post('/admin/builder/pages/create', data=data)
            assert resp.status_code == 302
            pid = resp.headers['Location'].rstrip('/').split('/')[-1]
            return c.get(f'/admin/builder/api/pages/{pid}').get_json()['layout']

        def _types(nodes):
            found = set()
            stack = list(nodes)
            while stack:
                node = stack.pop()
                found.add(node.get('type'))
                stack.extend(node.get('children') or [])
            return found

        # 列表栏目页：面包屑 + 文章列表
        with app.app_context():
            col_list = make_column(slug='zadl_' + uuid.uuid4().hex[:8],
                                   col_type='list')
            col_page = make_column(slug='zadp_' + uuid.uuid4().hex[:8],
                                   col_type='page')
            db.session.commit()
            cid_list, cid_page = col_list.id, col_page.id

        layout = _create('list', cid_list)
        assert len(layout['root']) > 0
        assert {'section', 'breadcrumb', 'article-list'} <= _types(layout['root'])

        # 单页栏目：面包屑 + 栏目标题/正文
        layout = _create('page', cid_page)
        assert {'section', 'breadcrumb', 'page-content'} <= _types(layout['root'])

        # 首页与全局文章详情（测试库为共享库，先清掉其他用例留下的全局记录）
        from app.models.builder import BuilderPage
        with app.app_context():
            BuilderPage.query.filter(
                BuilderPage.scope.in_(['home', 'article']),
                BuilderPage.column_id.is_(None)).delete(synchronize_session=False)
            db.session.commit()

        layout = _create('home')
        assert 'section' in _types(layout['root']) and len(layout['root']) > 0
        layout = _create('article')
        assert {'section', 'breadcrumb', 'article-detail'} <= _types(
            layout['root'])

        # 草稿对前台仍不可见：未发布前回退手写模板
        from app.builder import service
        with app.app_context():
            assert service.get_published_layout('list', cid_list) is None

    def test_init_default_route_reloads_fixture(self, app):
        """编辑器工具栏「默认布局」：覆盖草稿为 fixture，受 builder:manage 保护。"""
        # 无权限 403
        denied = _role_client(app, 'readonly_viewer')
        pid0 = _make_page(app, scope='home')
        assert denied.post(
            f'/admin/builder/pages/{pid0}/init-default').status_code == 403

        c = _role_client(app, 'content_editor')
        with app.app_context():
            col = make_column(slug='zadi_' + uuid.uuid4().hex[:8],
                              col_type='list')
            db.session.commit()
            cid = col.id
        # 先建空记录并写入自定义草稿
        pid = _make_page(app, scope='list', column_id=cid)
        resp = c.post(f'/admin/builder/api/pages/{pid}/draft',
                      json={'layout': _heading('自定义内容')})
        assert resp.status_code == 200

        # 重新载入默认布局 → 302 回编辑器，草稿被 fixture 覆盖
        resp = c.post(f'/admin/builder/pages/{pid}/init-default')
        assert resp.status_code == 302
        assert f'/admin/builder/editor/{pid}' in resp.headers['Location']
        layout = c.get(f'/admin/builder/api/pages/{pid}').get_json()['layout']
        types = set()
        stack = list(layout['root'])
        while stack:
            node = stack.pop()
            types.add(node.get('type'))
            stack.extend(node.get('children') or [])
        assert {'section', 'breadcrumb', 'article-list'} <= types
        assert 'heading' not in types
        # 仅覆盖草稿，未产生发布
        from app.builder import service
        with app.app_context():
            assert service.get_published_layout('list', cid) is None

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


class TestThemeFixtureResolution:
    """默认布局按「当前启用主题」解析：主题级 fixture 优先，核心回退。"""

    def test_resolve_fixture_path_priority(self, app):
        from app.builder import service
        with app.app_context():
            # 主题有覆写 → 命中主题文件
            p = service.resolve_fixture_path('home', 'manufacturing')
            assert p.replace('\\', '/').endswith(
                'themes/manufacturing/builder/home.json')
            # 官方主题均携带 home.json（规范必备）；
            # page/list/article 未覆写 → 回退核心
            for theme in ('default', 'blue'):
                assert service.resolve_fixture_path(
                    'home', theme).replace('\\', '/').endswith(
                    f'themes/{theme}/builder/home.json')
                for scope in ('page', 'list', 'article'):
                    p = service.resolve_fixture_path(scope, theme)
                    assert p.replace('\\', '/').endswith(
                        f'app/builder/fixtures/{scope}.json')
            # 其余仅有 home 覆写的主题，其他作用域同样回退核心
            for theme in ('catering', 'education', 'service',
                          'default_en', 'manufacturing_en'):
                assert service.resolve_fixture_path(
                    'home', theme).replace('\\', '/').endswith(
                    f'themes/{theme}/builder/home.json')
                assert service.resolve_fixture_path(
                    'list', theme).replace('\\', '/').endswith(
                    'app/builder/fixtures/list.json')
            # 未知主题 → 安全回退核心
            assert 'app/builder/fixtures/home.json' in \
                service.resolve_fixture_path('home', 'not-a-theme').replace('\\', '/')
            # 空主题 → 等价于「当前启用主题」解析（不报错、不拼空路径）
            assert service.resolve_fixture_path('home', '  ') == \
                service.resolve_fixture_path('home')
            # 第三方主题 slug 被污染（路径穿越/分隔符/超长）时不得拼接读文件，
            # 一律安全回退核心
            for bad in ('../default', '..', 'a/b', 'a\\b', 'x', 'x' * 33):
                p = service.resolve_fixture_path('home', bad).replace('\\', '/')
                assert p.endswith('app/builder/fixtures/home.json'), bad
            # 非法作用域
            assert service.resolve_fixture_path('evil', 'manufacturing') is None

    def test_init_default_layout_follows_active_theme(self, app):
        from app.builder import service
        from app.builder.schema import loads_layout
        from app.models.builder import BuilderPage
        from app.models.setting import Setting

        def _ids(page):
            return {n['id'] for n in
                    service.iter_layout_nodes(loads_layout(page.draft_json))}

        with app.app_context():
            old_theme = Setting.get('site_theme') or 'default'
            try:
                BuilderPage.query.filter_by(
                    scope='home', column_id=None).delete(
                    synchronize_session=False)
                db.session.commit()

                Setting.set('site_theme', 'manufacturing')
                page, err = service.init_default_layout('home')
                assert err is None
                assert 'n_mfg_prod_sec' in _ids(page)
                assert 'n_mfg_news_feat' in _ids(page)

                # 切换主题后重新初始化 → 载入新主题结构（旧草稿被覆盖）
                Setting.set('site_theme', 'catering')
                page, err = service.init_default_layout('home')
                assert err is None
                assert 'n_cat_dishes_sec' in _ids(page)
                assert 'n_mfg_prod_sec' not in _ids(page)

                # 显式 theme 参数优先于当前启用主题
                page, err = service.init_default_layout('home', theme='service')
                assert err is None
                assert 'n_svc_services_list' in _ids(page)

                # blue 自带 home.json（与核心同构）：不得出现 catering 节点
                page, err = service.init_default_layout('home', theme='blue')
                assert err is None
                ids = _ids(page)
                assert 'n_cat_dishes_sec' not in ids
                assert len(ids) > 0
            finally:
                Setting.set('site_theme', old_theme)

    def test_editor_create_route_uses_active_theme(self, app):
        """后台新建首页走当前启用主题的手写等价布局。"""
        from app.builder import service
        from app.models.builder import BuilderPage
        from app.models.setting import Setting
        from app.extensions import cache

        c = _role_client(app, 'content_editor')
        with app.app_context():
            old_theme = Setting.get('site_theme') or 'default'
            try:
                BuilderPage.query.filter_by(
                    scope='home', column_id=None).delete(
                    synchronize_session=False)
                db.session.commit()
                Setting.set('site_theme', 'education')
                cache.clear()

                resp = c.post('/admin/builder/pages/create',
                              data={'scope': 'home'})
                assert resp.status_code == 302
                pid = resp.headers['Location'].rstrip('/').split('/')[-1]
                layout = c.get(
                    f'/admin/builder/api/pages/{pid}').get_json()['layout']
                types = set()
                stack = list(layout['root'])
                while stack:
                    node = stack.pop()
                    types.add(node.get('type'))
                    stack.extend(node.get('children') or [])
                # 教育主题首页特征：数据统计条（手写 edu-stats 段）
                assert 'stat-numbers' in types
                assert 'cta-banner' in types
            finally:
                Setting.set('site_theme', old_theme)
                cache.clear()


class TestSelectorApis:
    """属性面板选择器数据源：栏目（链接选择器）/ 碎片下拉。"""

    def test_columns_all_returns_list_and_page(self, app):
        c = _role_client(app, 'content_editor')
        marker_list = 'ZBL' + uuid.uuid4().hex[:8]
        marker_page = 'ZBP' + uuid.uuid4().hex[:8]
        with app.app_context():
            make_column(name=marker_list, slug='zbl_' + uuid.uuid4().hex[:8],
                        col_type='list')
            make_column(name=marker_page, slug='zbp_' + uuid.uuid4().hex[:8],
                        col_type='page')
            db.session.commit()
        data = c.get('/admin/builder/api/columns?type=all').get_json()
        names = {x['name'] for x in data['columns']}
        assert marker_list in names and marker_page in names
        assert all(x['type'] in ('list', 'page') for x in data['columns'])
        # 旧行为不变：type=list 不含 page 栏目
        data_list = c.get('/admin/builder/api/columns?type=list').get_json()
        assert marker_page not in {x['name'] for x in data_list['columns']}

    def test_fragments_listing_and_rbac(self, app):
        from app.models.fragment import Fragment, FragmentGroup
        # 匿名 302、无权限 403
        anon = app.test_client()
        assert anon.get('/admin/builder/api/fragments').status_code == 302
        assert _role_client(app, 'readonly_viewer').get(
            '/admin/builder/api/fragments').status_code == 403

        c = _role_client(app, 'content_editor')
        slug = 'zbf_' + uuid.uuid4().hex[:8]
        with app.app_context():
            grp = FragmentGroup(name='ZB组' + uuid.uuid4().hex[:6])
            db.session.add(grp)
            db.session.flush()
            db.session.add(Fragment(
                name='测试碎片', slug=slug, field_type='text', value='v',
                group_id=grp.id, is_enabled=True, is_deleted=False,
                sort_order=0))
            # 禁用/删除碎片不应出现
            db.session.add(Fragment(
                name='禁用碎片', slug='zbf_off_' + uuid.uuid4().hex[:8],
                field_type='text', value='x', is_enabled=False,
                is_deleted=False, sort_order=0))
            db.session.commit()

        data = c.get('/admin/builder/api/fragments').get_json()
        assert data['ok'] is True
        row = next(x for x in data['fragments'] if x['slug'] == slug)
        assert row['name'] == '测试碎片'
        assert row['field_type'] == 'text'
        assert row['group'].startswith('ZB组')
        assert not any(x['slug'].startswith('zbf_off_')
                       for x in data['fragments'])
