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

FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'app', 'builder', 'fixtures')


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
