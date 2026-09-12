"""v3.0.0 页面构建器 —— 组件注册表测试。

覆盖：核心组件数量与目录、作用域过滤、插件门控、owner 归属、
默认节点构造、父子约束声明。
"""
import pytest

from app.builder import registry
from app.builder.registry import (
    Widget, register_widget, unregister_owner, get_widget,
    widget_catalog, widget_owner, available_widget_types,
    core_widget_count,
)
from app.constants import Builder as B


def test_core_widgets_present():
    """24 个核心组件全部注册。"""
    assert core_widget_count() == 24
    for t in ('section', 'container', 'grid-row', 'grid-col', 'spacer', 'divider',
              'heading', 'text', 'richtext', 'image', 'button', 'icon-box',
              'alert', 'video-embed',
              'article-list', 'article-detail', 'page-content', 'breadcrumb',
              'fragment', 'carousel', 'contact-card', 'cta-banner',
              'friend-links', 'stat-numbers'):
        assert get_widget(t) is not None, f'缺少核心组件 {t}'


def test_catalog_grouping_and_scope_filter():
    cats = widget_catalog()
    assert set(cats) == {B.CAT_LAYOUT, B.CAT_BASIC, B.CAT_DATA}
    types_all = {w['type'] for grp in cats.values() for w in grp}
    assert 'section' in types_all

    home = {w['type'] for grp in widget_catalog(B.SCOPE_HOME).values() for w in grp}
    article = {w['type'] for grp in widget_catalog(B.SCOPE_ARTICLE).values()
               for w in grp}
    # article-detail 仅详情作用域；article-list 不出现在详情作用域
    assert 'article-detail' not in home
    assert 'article-detail' in article
    assert 'article-list' not in article


def test_plugin_widget_gating(monkeypatch):
    """插件组件：未启用时门控、目录标灰；启用后可用。"""

    class Demo(Widget):
        type = 'zbw-test-gated'
        label = '门控测试'
        category = B.CAT_BASIC
        scopes = B.SCOPES
        default_props = {}
        prop_schema = []

    register_widget(Demo, owner='zbw_test_plugin')
    try:
        assert widget_owner('zbw-test-gated') == 'zbw_test_plugin'
        # 插件未启用（不在 enabled_slugs 中）
        assert get_widget('zbw-test-gated') is None
        assert get_widget('zbw-test-gated', include_disabled=True) is not None
        assert 'zbw-test-gated' not in available_widget_types()

        grp = widget_catalog('home')
        item = [w for g in grp.values() for w in g
                if w['type'] == 'zbw-test-gated'][0]
        assert item['enabled'] is False

        # 模拟插件启用
        from app import plugin_system
        monkeypatch.setattr(
            plugin_system, 'plugin_enabled', lambda slug: slug == 'zbw_test_plugin')
        assert get_widget('zbw-test-gated') is not None
        assert 'zbw-test-gated' in available_widget_types()
    finally:
        unregister_owner('zbw_test_plugin')
    assert get_widget('zbw-test-gated', include_disabled=True) is None


def test_new_node_defaults_and_children():
    from app.builder.schema import new_node
    row = new_node('grid-row')
    assert row['type'] == 'grid-row'
    assert len(row['children']) == 2
    assert all(c['type'] == 'grid-col' for c in row['children'])
    # 每个节点 id 唯一
    ids = {c['id'] for c in row['children']}
    assert len(ids) == 2
    assert row['id'] not in ids

    heading = new_node('heading')
    assert heading['props']['level'] == 2
    assert heading['children'] == []


def test_allowed_children_declarations():
    section = get_widget('section')
    assert '*' in section.allowed_children
    assert get_widget('heading').allowed_children == ()
    assert get_widget('grid-col').allowed_children == ('*',)
