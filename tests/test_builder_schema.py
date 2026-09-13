"""v3.0.0 页面构建器 —— 布局 JSON 校验与规整测试。"""
import glob
import json
import os

import pytest

from app.builder.schema import (
    validate_layout, normalize_layout, new_node, find_node, find_parent,
    iter_nodes, LayoutError,
)
from app.constants import Builder as B

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(_APP_DIR, 'app', 'builder', 'fixtures')
THEMES_DIR = os.path.join(_APP_DIR, 'app', 'frontend', 'templates', 'themes')


def _node(t, **kw):
    n = {'id': kw.pop('id', 'n_' + t), 'type': t,
         'props': kw.pop('props', {}), 'children': kw.pop('children', [])}
    n.update(kw)
    return n


class TestFixtures:
    """四套默认布局必须合法。"""

    @pytest.mark.parametrize('name', ['home', 'page', 'list', 'article'])
    def test_fixture_valid(self, name):
        with open(os.path.join(FIXTURES_DIR, f'{name}.json'),
                  encoding='utf-8') as f:
            layout = json.load(f)
        out = validate_layout(layout)
        assert out['version'] == B.SCHEMA_VERSION

    def test_all_fixture_files_covered(self):
        files = sorted(os.path.basename(p) for p in
                       glob.glob(os.path.join(FIXTURES_DIR, '*.json')))
        assert files == ['article.json', 'home.json', 'list.json', 'page.json']

    def test_theme_fixture_overrides_valid(self):
        """themes/<theme>/builder/*.json 主题级默认布局必须全部合法。"""
        paths = sorted(glob.glob(os.path.join(
            THEMES_DIR, '*', 'builder', '*.json')))
        assert paths, '至少应有一个主题级 fixture 覆写'
        for path in paths:
            with open(path, encoding='utf-8') as f:
                layout = json.load(f)
            validate_layout(layout)


class TestValidateBasic:
    def test_minimal_valid(self):
        layout = {'root': [_node('heading', props={'text': 'x', 'level': 2})]}
        assert validate_layout(layout)['root'][0]['type'] == 'heading'

    def test_root_must_be_list(self):
        with pytest.raises(LayoutError):
            validate_layout({'root': {}})
        with pytest.raises(LayoutError):
            validate_layout({})

    def test_unknown_type_rejected(self):
        with pytest.raises(LayoutError):
            validate_layout({'root': [_node('not-exist')]})

    def test_missing_id_rejected(self):
        n = _node('heading')
        del n['id']
        with pytest.raises(LayoutError):
            validate_layout({'root': [n]})

    def test_int_select_value_accepted(self):
        """heading.level 以 int 存储（编辑器/默认值习惯），按 str 比较。"""
        out = validate_layout(
            {'root': [_node('heading', props={'level': 2})]})
        assert out['root'][0]['props']['level'] == 2

    def test_bad_select_rejected(self):
        with pytest.raises(LayoutError):
            validate_layout(
                {'root': [_node('heading', props={'level': 99})]})

    def test_toggle_must_be_bool(self):
        with pytest.raises(LayoutError):
            validate_layout({'root': [_node(
                'article-list', props={'show_pagination': 'yes'})]})

    def test_number_must_be_numeric(self):
        with pytest.raises(LayoutError):
            validate_layout({'root': [_node(
                'article-list', props={'limit': '六'})]})

    def test_unknown_prop_key_rejected(self):
        with pytest.raises(LayoutError):
            validate_layout({'root': [_node(
                'heading', props={'evil': '<script>'})]})

    def test_repeater_subkey_whitelist(self):
        good = _node('carousel', props={'items': [
            {'image': '/a.jpg', 'title': 't', 'subtitle': '', 'link': ''}]})
        validate_layout({'root': [good]})
        bad = _node('carousel', props={'items': [{'hack': 1}]})
        with pytest.raises(LayoutError):
            validate_layout({'root': [bad]})

    def test_fragment_prop_must_be_str(self):
        validate_layout({'root': [_node('fragment', props={'slug': 'contact'})]})
        validate_layout({'root': [_node('fragment', props={'slug': ''})]})
        with pytest.raises(LayoutError):
            validate_layout({'root': [_node('fragment', props={'slug': 123})]})

    def test_localized_dict_locales(self):
        validate_layout({'root': [_node('heading', props={
            'text': {'zh': '你好', 'en': 'hi'}, 'level': 2})]})
        with pytest.raises(LayoutError):
            validate_layout({'root': [_node('heading', props={
                'text': {'fr': 'x'}, 'level': 2})]})

    def test_children_constraint(self):
        # heading 不允许子组件
        with pytest.raises(LayoutError):
            validate_layout({'root': [_node(
                'heading', children=[_node('text', id='c1')])]})
        # grid-row 仅允许 grid-col
        with pytest.raises(LayoutError):
            validate_layout({'root': [_node(
                'grid-row', children=[_node('heading', id='c2')])]})


class TestLimits:
    def test_depth_limit(self):
        # 第 9 层超出 MAX_DEPTH=8
        node = _node('section', id='d8')
        for i in range(8):
            node = _node('section', id=f'd{7 - i}', children=[node])
        with pytest.raises(LayoutError, match='深度'):
            validate_layout({'root': [node]})

    def test_depth_ok_at_boundary(self):
        node = _node('section', id='deep8')
        for _ in range(7):
            node = _node('section', children=[node])
        validate_layout({'root': [node]})

    def test_node_count_limit(self):
        nodes = [_node('heading', id=f'h{i}') for i in range(B.MAX_NODES + 1)]
        with pytest.raises(LayoutError, match='节点数'):
            validate_layout({'root': nodes})

    def test_payload_size_limit(self):
        big = 'x' * (B.MAX_PAYLOAD_BYTES + 10)
        with pytest.raises(LayoutError, match='KB'):
            validate_layout({'root': [
                _node('text', id='big', props={'content': big})]})


class TestHelpers:
    def test_normalize_drops_garbage(self):
        out = normalize_layout({'root': [
            'junk', 42, None, {}, {'no': 'type'},
            {'type': 'heading', 'props': {'level': 2}},
        ]})
        assert len(out['root']) == 1
        assert out['root'][0]['type'] == 'heading'
        assert out['root'][0]['props']['level'] == 2

    def test_normalize_repairs_bad_children(self):
        out = normalize_layout({'root': [
            {'type': 'section', 'children': 'nope'}]})
        assert out['root'][0]['children'] == []

    def test_normalize_empty(self):
        assert normalize_layout(None)['root'] == []

    def test_iter_find(self):
        layout = {'root': [
            _node('section', id='s1', children=[
                _node('grid-row', id='r1', children=[
                    _node('grid-col', id='c1', children=[
                        _node('heading', id='h1')])])])]}
        assert find_node(layout['root'], 'h1')['type'] == 'heading'
        assert find_node(layout['root'], 'zz') is None
        parent, node = find_parent(layout['root'], 'h1')
        assert node['id'] == 'h1' and parent['id'] == 'c1'
        assert len(list(iter_nodes(layout['root']))) == 4

    def test_new_node_roundtrip(self):
        section = new_node('section')
        section['children'].append(new_node('heading'))
        validate_layout({'root': [section]})


class TestGlobalStyles:
    def _layout(self, styles):
        return {'root': [_node('heading', props={'text': 'x', 'level': 2})],
                'styles': styles}

    def test_valid_styles_accepted(self):
        out = validate_layout(self._layout({
            'page_bg': '#ffffff', 'footer_bg': '#2C3E50',
            'heading_color': '#222222', 'radius': '8px',
            'border_width': '1px', 'border_color': '#dee2e6',
            'shadow': 'md',
        }))
        assert out['styles']['footer_bg'] == '#2C3E50'
        assert out['styles']['shadow'] == 'md'

    def test_empty_values_dropped(self):
        out = validate_layout(self._layout({'page_bg': '  ', 'shadow': ''}))
        assert out['styles'] == {}

    def test_bad_color_rejected(self):
        with pytest.raises(LayoutError, match='page_bg'):
            validate_layout(self._layout({'page_bg': 'red'}))
        with pytest.raises(LayoutError, match='颜色'):
            validate_layout(self._layout({'page_bg': '#fff'}))
        with pytest.raises(LayoutError):
            validate_layout(self._layout({'page_bg': '<script>'}))

    def test_bad_enum_rejected(self):
        with pytest.raises(LayoutError, match='radius'):
            validate_layout(self._layout({'radius': '99px'}))
        with pytest.raises(LayoutError, match='shadow'):
            validate_layout(self._layout({'shadow': 'huge'}))

    def test_unknown_style_key_rejected(self):
        with pytest.raises(LayoutError, match='不支持的全局样式项'):
            validate_layout(self._layout({'evil': '#000000'}))

    def test_styles_must_be_object(self):
        layout = self._layout(None)
        layout['styles'] = []
        with pytest.raises(LayoutError):
            validate_layout(layout)

    def test_normalize_passes_styles_through(self):
        out = normalize_layout(self._layout({'page_bg': '#f5f5f5'}))
        assert out['styles'] == {'page_bg': '#f5f5f5'}

    def test_normalize_drops_invalid_styles(self):
        out = normalize_layout(self._layout({'page_bg': 'red'}))
        assert 'styles' not in out

    def test_old_layout_without_styles_still_works(self):
        out = validate_layout({'root': [
            _node('heading', props={'text': 'x', 'level': 2})]})
        assert 'styles' not in out
        assert 'styles' not in normalize_layout(
            {'root': [_node('heading', props={'text': 'x', 'level': 2})]})
