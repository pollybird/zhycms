"""v3.0.0 页面构建器 —— 服务端渲染与前台双轨测试。

覆盖：
- 四作用域发布后前台走构建器、无布局回退手写模板、草稿匿名不可见
- 8 套主题矩阵渲染
- 分页不串页、伪静态 URL 复用
- 发布清缓存即时生效、文章详情全局布局回退
- localized 文案回退、会员/语言可见性
- 插件组件禁用：生产静默、预览占位；未知类型静默
- _tpl_base 注入（context_processor 变量在 partial 中可用）
"""
import json
import os
import uuid
from datetime import datetime

import pytest

from app.constants import Builder as B
from app.extensions import db
from tests.factories import make_column, make_article


# ------------------------------------------------------------
# 数据构造
# ------------------------------------------------------------

def _list_column(app, n_articles=6, page_size=10, prefix='ztl'):
    """创建唯一 list 栏目 + N 篇已发布文章，返回 (col_id, slug)。"""
    slug = f'{prefix}_{uuid.uuid4().hex[:8]}'
    with app.app_context():
        col = make_column(name='构建测试栏目-' + slug, slug=slug,
                          col_type='list')
        col.page_size = page_size
        db.session.commit()
        for i in range(n_articles):
            a = make_article(
                title=f'ZBW文章{slug[-4:]}-{i:02d}号', column_id=col.id,
                content=f'<p>正文内容 {i}</p>')
            a.published_at = datetime(2026, 1, 1, 12, 0, i)
        db.session.commit()
        return col.id, slug


def _page_column(app, prefix='ztp'):
    slug = f'{prefix}_{uuid.uuid4().hex[:8]}'
    with app.app_context():
        col = make_column(name='单页-' + slug, slug=slug, col_type='page')
        col.page_content = '<p>ZBW 单页正文</p>'
        db.session.commit()
        return col.id, slug


def _fixture(scope_name):
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'app', 'builder', 'fixtures', f'{scope_name}.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _publish(scope, column_id, layout):
    from app.builder import service
    page, _ = service.get_or_create_page(scope, column_id)
    rev, err = service.publish_page(page, layout)
    assert err is None, err
    return page


def _heading(text, nid=None):
    return {'id': nid or ('h_' + uuid.uuid4().hex[:8]),
            'type': 'heading', 'props': {'text': text, 'level': 2},
            'children': [], 'visibility': {}}


# ------------------------------------------------------------
# 双轨：HTTP 端到端
# ------------------------------------------------------------

class TestDualTrack:
    def test_no_layout_falls_back_to_handwritten(self, app, client):
        _, slug = _list_column(app, n_articles=2)
        resp = client.get(f'/column/{slug}')
        assert resp.status_code == 200
        assert b'zbw-section' not in resp.data
        assert f'ZBW文章{slug[-4:]}-00号'.encode() in resp.data

    def test_draft_invisible_to_anonymous(self, app, client):
        cid, slug = _list_column(app, n_articles=2)
        with app.app_context():
            from app.builder import service
            page, err = service.init_default_layout('list', cid)
            assert err is None
        resp = client.get(f'/column/{slug}')
        assert b'zbw-section' not in resp.data

    def test_published_list_scope(self, app, client):
        cid, slug = _list_column(app, n_articles=3)
        with app.app_context():
            _publish('list', cid, _fixture('list'))
        resp = client.get(f'/column/{slug}')
        assert resp.status_code == 200
        assert b'zbw-section' in resp.data
        # 文章数据真实渲染
        assert f'ZBW文章{slug[-4:]}-02号'.encode() in resp.data
        # 默认布局对齐手写列表页：栏目标题 H1 + 图文行式列表（非卡片网格）
        assert ('构建测试栏目-' + slug).encode() in resp.data
        assert b'zbw-list-title' in resp.data
        assert b'zbw-article-row' in resp.data
        assert b'zbw-article-card' not in resp.data

    def test_published_page_scope(self, app, client):
        cid, slug = _page_column(app)
        with app.app_context():
            _publish('page', cid, _fixture('page'))
        resp = client.get(f'/column/{slug}')
        assert resp.status_code == 200
        assert b'zbw-section' in resp.data
        assert 'ZBW 单页正文' in resp.get_data(as_text=True)

    def test_published_article_scope_and_global_fallback(self, app, client):
        cid, slug = _list_column(app, n_articles=2)
        with app.app_context():
            from app.builder import service
            aid = db.session.execute(
                db.text('SELECT id FROM articles WHERE column_id=:c '
                        'ORDER BY id LIMIT 1'), {'c': cid}).scalar()
            # 先发布「全局」文章详情布局 → 该栏目自动回退命中
            _publish('article', None, _fixture('article'))
            assert service.get_published_layout('article', cid) is not None
        resp = client.get(f'/column/{slug}/article/{aid}')
        assert resp.status_code == 200
        assert b'zbw-section' in resp.data
        assert f'ZBW文章{slug[-4:]}-'.encode() in resp.data

    def test_published_home_scope(self, app, client):
        from app.models.builder import BuilderPage
        with app.app_context():
            _publish('home', None, _fixture('home'))
        try:
            resp = client.get('/')
            assert resp.status_code == 200
            assert b'zbw-section' in resp.data
        finally:
            with app.app_context():
                BuilderPage.query.filter_by(scope='home').delete()
                db.session.commit()
                db.session.execute(db.text('DELETE FROM builder_revisions'))
                db.session.commit()
            from app.extensions import cache
            cache.clear()

    def test_article_list_offset_partitions_articles(self, app, client):
        """offset 实现手写首页"首条大图 + 其余列表"：两条列表互不重叠。"""
        from app.models.builder import BuilderPage
        cid, _ = _list_column(app, n_articles=3)

        def _alist(nid, limit, offset):
            return {'id': nid, 'type': 'article-list', 'props': {
                'bind': 'select', 'column_id': cid, 'limit': limit,
                'offset': offset, 'layout': 'simple',
                'show_cover': False, 'show_date': False, 'show_summary': False,
                'show_more': False, 'show_pagination': False},
                'children': [], 'visibility': {}}

        with app.app_context():
            rows = db.session.execute(
                db.text('SELECT title FROM articles WHERE column_id=:c '
                        'ORDER BY sort_order DESC, published_at DESC, id DESC'),
                {'c': cid}).fetchall()
            titles = [r[0] for r in rows]
            _publish('home', None, {'root': [
                _alist('al_feat', 1, 0), _alist('al_rest', 5, 1)]})
        try:
            html = client.get('/').get_data(as_text=True)
            # 最新 1 条只在首条列表；其余列表从第 2 条开始，不重复
            assert html.count(titles[0]) == 1
            assert html.count(titles[1]) == 1
            assert titles[0] in html and titles[1] in html
        finally:
            with app.app_context():
                BuilderPage.query.filter_by(scope='home').delete()
                db.session.commit()
                db.session.execute(db.text('DELETE FROM builder_revisions'))
                db.session.commit()
            from app.extensions import cache
            cache.clear()

    def test_publish_clears_page_cache(self, app, client):
        cid, slug = _list_column(app, n_articles=1)
        marker_a = 'ZBW标记A-' + uuid.uuid4().hex[:6]
        marker_b = 'ZBW标记B-' + uuid.uuid4().hex[:6]
        with app.app_context():
            page = _publish('list', cid, {'root': [_heading(marker_a)]})
            pid = page.id
        resp = client.get(f'/column/{slug}')
        assert marker_a.encode() in resp.data
        with app.app_context():
            from app.builder import service
            from app.models.builder import BuilderPage
            page = db.session.get(BuilderPage, pid)
            service.publish_page(page, {'root': [_heading(marker_b)]})
        resp = client.get(f'/column/{slug}')
        assert marker_b.encode() in resp.data
        assert marker_a.encode() not in resp.data

    def test_pagination_does_not_leak_across_pages(self, app, client):
        cid, slug = _list_column(app, n_articles=7, page_size=3)
        # 文章按 sort_order/published_at desc：id 越大越靠前
        with app.app_context():
            layout = {'root': [{
                'id': 'al_pager', 'type': 'article-list',
                'props': {'bind': 'auto', 'limit': 3, 'layout': 'simple',
                          'show_pagination': True},
                'children': [], 'visibility': {}}]}
            _publish('list', cid, layout)
            rows = db.session.execute(
                db.text('SELECT title FROM articles WHERE column_id=:c '
                        'ORDER BY sort_order DESC, published_at DESC, id DESC'),
                {'c': cid}).fetchall()
            titles = [r[0] for r in rows]
        p1 = client.get(f'/column/{slug}')
        p2 = client.get(f'/column/{slug}?page=2')
        assert titles[0].encode() in p1.data
        assert titles[3].encode() not in p1.data
        assert titles[3].encode() in p2.data
        assert titles[0].encode() not in p2.data

    def test_seo_rewrite_url_reuses_builder_view(self, app, client):
        from app.models.setting import Setting
        cid, slug = _list_column(app, n_articles=1)
        with app.app_context():
            old = Setting.get('seo_rewrite_enable')
            Setting.set('seo_rewrite_enable', 'on')
            _publish('list', cid, _fixture('list'))
        try:
            resp = client.get(f'/{slug}.html')
            assert resp.status_code == 200
            assert b'zbw-section' in resp.data
        finally:
            with app.app_context():
                Setting.set('seo_rewrite_enable', old or 'off')
            from app.extensions import cache
            cache.clear()


# ------------------------------------------------------------
# 8 主题矩阵
# ------------------------------------------------------------

THEMES = ['default', 'blue', 'manufacturing', 'service', 'catering',
          'education', 'default_en', 'manufacturing_en']


@pytest.fixture
def theme_switch(app):
    """切换主题并在用例后还原 + 清缓存。"""
    from app.models.setting import Setting
    from app.extensions import cache
    with app.app_context():
        old = Setting.get('site_theme') or 'default'

    def switch(slug):
        with app.app_context():
            Setting.set('site_theme', slug)
        cache.clear()

    yield switch
    with app.app_context():
        Setting.set('site_theme', old)
    cache.clear()


@pytest.mark.parametrize('theme', THEMES)
def test_theme_matrix_render(theme, app, client, theme_switch):
    themes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'app', 'frontend', 'templates', 'themes')
    assert os.path.isdir(os.path.join(themes_dir, theme)), f'缺少主题 {theme}'
    cid, slug = _page_column(app)
    with app.app_context():
        _publish('page', cid, _fixture('page'))
    theme_switch(theme)
    resp = client.get(f'/column/{slug}')
    assert resp.status_code == 200, f'{theme} 主题渲染失败'
    assert b'zbw-section' in resp.data


# 每个主题手写首页的特征文案：发布该主题自身 fixture 后必须出现在首页
THEME_HOME_MARKERS = {
    'default': '欢迎访问我们的企业官网',
    'blue': '欢迎访问我们的企业官网',  # blue 首页结构同 default，fixture 同构
    'manufacturing': '产品展示',
    'manufacturing_en': 'Products',
    'catering': '招牌美食',
    'education': '让孩子赢在起跑线',
    'service': '经营范围',
    'default_en': 'Welcome to Our Company Website',
}


@pytest.mark.parametrize('theme', THEMES)
def test_theme_home_fixture_renders(theme, app, client, theme_switch):
    """各主题自己的 home fixture 必须在该主题下完整渲染（结构等价手写首页）。"""
    from app.builder import service
    with app.app_context():
        path = service.resolve_fixture_path('home', theme)
        with open(path, encoding='utf-8') as f:
            layout = json.load(f)
        _publish('home', None, layout)
    theme_switch(theme)
    resp = client.get('/')
    assert resp.status_code == 200, f'{theme} 主题首页 fixture 渲染失败'
    html = resp.get_data(as_text=True)
    assert 'zbw-page-root' in html
    assert THEME_HOME_MARKERS[theme] in html, \
        f'{theme} 主题首页缺少特征内容：{THEME_HOME_MARKERS[theme]}'


# ------------------------------------------------------------
# 渲染器单元：可见性 / i18n / 门控 / 模板上下文
# ------------------------------------------------------------

class TestRendererUnit:
    def _html(self, app, root, **page_ctx):
        from app.builder.renderer import render_layout_html
        with app.test_request_context('/'):
            return str(render_layout_html({'root': root}, page_ctx))

    def test_localized_en_and_fallback(self, app):
        node = _heading({'zh': '中文标题', 'en': 'English Title'})
        assert 'English Title' in self._html(app, [node], locale='en')
        assert '中文标题' in self._html(app, [node], locale='zh')
        # 未知语言回退默认语言
        assert '中文标题' in self._html(app, [node], locale='ja')

    def test_member_only_visibility(self, app):
        node = _heading('会员专享内容')
        node['visibility'] = {'member_only': True}
        assert '会员专享内容' not in self._html(app, [node], is_member=False)
        assert '会员专享内容' in self._html(app, [node], is_member=True)

    def test_locale_whitelist(self, app):
        node = _heading('仅英文')
        node['visibility'] = {'locales': ['en']}
        assert '仅英文' not in self._html(app, [node], locale='zh')
        assert '仅英文' in self._html(app, [node], locale='en')

    def test_unknown_type_silent(self, app):
        node = {'id': 'x1', 'type': 'totally-unknown', 'props': {},
                'children': [], 'visibility': {}}
        assert self._html(app, [node]) == ''

    def test_disabled_plugin_placeholder(self, app, monkeypatch):
        from app.builder.registry import (
            Widget, register_widget, unregister_owner)
        from app.constants import Builder as BC

        class Demo(Widget):
            type = 'zbw-test-render'
            label = '渲染门控测试'
            category = BC.CAT_BASIC
            scopes = BC.SCOPES
            default_props = {}
            prop_schema = []

        register_widget(Demo, owner='zbw_test_render_plugin')
        node = {'id': 'd1', 'type': 'zbw-test-render', 'props': {},
                'children': [], 'visibility': {}}
        try:
            # 插件未启用：生产空、预览占位
            assert self._html(app, [node], preview=False) == ''
            preview_html = self._html(app, [node], preview=True)
            assert 'zbw-disabled-placeholder' in preview_html
            assert 'zbw_test_render_plugin' in preview_html
        finally:
            unregister_owner('zbw_test_render_plugin')

    def test_template_base_ctx_injection(self, app):
        """contact-card partial 引用 context_processor 的 site_fragments，
        验证 _tpl_base 注入后不再因 UndefinedError 被异常隔离吞掉。"""
        node = {'id': 'cc1', 'type': 'contact-card', 'props': {},
                'children': [], 'visibility': {}}
        html = self._html(app, [node])
        assert 'zbw-contact-card' in html


# ------------------------------------------------------------
# 全局样式：CSS 生成 + 预览/生产注入
# ------------------------------------------------------------

class TestGlobalStylesCss:
    def test_empty_styles_output_nothing(self):
        from app.builder.styles import build_global_css
        assert build_global_css(None) == ''
        assert build_global_css({}) == ''
        assert build_global_css({'page_bg': ''}) == ''

    def test_page_and_footer_rules(self):
        from app.builder.styles import build_global_css
        css = build_global_css({
            'page_bg': '#f0f0f0', 'content_bg': '#ffffff',
            'text_color': '#333333', 'heading_color': '#222222',
            'link_color': '#0066cc',
            'footer_bg': '#2c3e50', 'footer_color': '#ffffff',
        })
        assert 'body { background-color: #f0f0f0; }' in css
        assert '.zbw-page-root {' in css
        assert 'color: #333333' in css
        assert '.zbw-heading' in css and 'h1' in css
        assert '.zbw-page-root a { color: #0066cc; }' in css
        # 渐变主题也需覆盖：去背景图 + !important
        assert 'footer.footer {' in css
        assert 'background-image: none !important' in css
        assert '#2c3e50 !important' in css
        assert 'footer.footer a' in css and '#ffffff' in css

    def test_container_decorations(self):
        from app.builder.styles import build_global_css
        css = build_global_css({
            'radius': '8px', 'border_width': '2px',
            'border_color': '#cccccc', 'shadow': 'lg',
        })
        assert '.zbw-page-root .zbw-container {' in css
        assert 'border-radius: 8px' in css
        assert 'border: 2px solid #cccccc' in css
        assert 'box-shadow:' in css
        # 设了边框宽度但没给颜色 → 使用安全的默认灰
        css2 = build_global_css({'border_width': '1px'})
        assert 'border: 1px solid #dee2e6' in css2
        # 无边框 / 无阴影 → 不输出对应声明
        css3 = build_global_css({'border_width': '0px', 'shadow': 'none',
                                 'radius': '0px'})
        assert 'border:' not in css3
        assert 'box-shadow' not in css3

    def test_garbage_styles_neutralized(self):
        from app.builder.styles import build_global_css
        # 非法输入不产生任何 CSS（渲染层防御，不抛异常）
        assert build_global_css({'page_bg': 'red'}) == ''
        assert build_global_css('not-a-dict') == ''


class TestGlobalStylesRender:
    def test_styles_injected_in_production_page(self, app, client):
        cid, slug = _page_column(app)
        layout = _fixture('page')
        layout['styles'] = {
            'page_bg': '#f8f8f8', 'footer_bg': '#34495e',
            'heading_color': '#111111', 'border_width': '1px',
            'border_color': '#dddddd', 'radius': '8px',
        }
        with app.app_context():
            _publish('page', cid, layout)
        resp = client.get(f'/column/{slug}')
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert 'data-zbw-global-styles="1"' in html
        assert 'body { background-color: #f8f8f8; }' in html
        assert '#34495e !important' in html
        # 生产内容被 .zbw-page-root 包裹
        assert 'class="zbw-page-root"' in html

    def test_no_style_tag_when_unset(self, app, client):
        cid, slug = _page_column(app)
        with app.app_context():
            _publish('page', cid, _fixture('page'))
        resp = client.get(f'/column/{slug}')
        html = resp.get_data(as_text=True)
        assert 'data-zbw-global-styles' not in html
        # 生产仍有根包裹（统一结构），预览态 data-zbw-root 属性不受影响
        assert 'class="zbw-page-root"' in html

    def test_styles_survive_draft_save_and_preview(self, app, client):
        """编辑器保存草稿：校验通过 + 预览页立即可见。"""
        from app.builder import service
        with app.app_context():
            page, _ = service.get_or_create_page('home')
            pid = page.id
        admin = _admin_client(app, client)
        layout = _fixture('home')
        layout['styles'] = {'page_bg': '#123456'}
        resp = admin.post(f'/admin/builder/api/pages/{pid}/draft',
                          json={'layout': layout})
        assert resp.status_code == 200
        preview = admin.get(f'/admin/builder/preview/{pid}')
        text = preview.get_data(as_text=True)
        assert 'data-zbw-global-styles="1"' in text
        assert '#123456' in text

    def test_invalid_color_draft_rejected(self, app, client):
        from app.builder import service
        with app.app_context():
            page, _ = service.get_or_create_page('home')
            pid = page.id
        admin = _admin_client(app, client)
        layout = _fixture('home')
        layout['styles'] = {'page_bg': 'expression(alert(1))'}
        resp = admin.post(f'/admin/builder/api/pages/{pid}/draft',
                          json={'layout': layout})
        assert resp.status_code == 400
        assert resp.get_json()['ok'] is False


def _admin_client(app, client):
    """注入一个超级管理员会话（绕验证码）。"""
    from tests.factories import make_user
    with app.app_context():
        user = make_user(username='zbw_style_admin_' + uuid.uuid4().hex[:8],
                         is_super=True)
        db.session.commit()
        uid = user.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True
    return client
