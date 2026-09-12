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
