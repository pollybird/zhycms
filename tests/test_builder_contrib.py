"""插件向页面构建器贡献默认布局的测试（v3.0.0）。

覆盖：
- discover_package_layouts：合法片段发现 / 非法文件名、坏 JSON、结构错误拒绝
- compose_layout：prepend/append/锚点/锚点缺失回退/撞 id 重写/
  禁用不合并/坏片段隔离/入参不可变/非法作用域
- validation_error + validate_enable：片段非法时拒绝启用插件
- init_default_layout 快照集成：4 个内容型插件启用后首页草稿增补、
  禁用后重新初始化不再增补；发布后前台真实渲染
"""
import json
import uuid

import pytest

from app.builder import contrib

PLUGINS = ('banner', 'product', 'recruit', 'tutorial')
WIDGET_TYPES = {
    'banner': 'banner-hero',
    'product': 'product-list',
    'recruit': 'job-list',
    'tutorial': 'tutorial-list',
}


# ------------------------------------------------------------
# 辅助
# ------------------------------------------------------------

def _write_frag(directory, name='home.json', payload=None):
    builder_dir = directory / 'builder'
    builder_dir.mkdir(parents=True, exist_ok=True)
    fp = builder_dir / name
    if isinstance(payload, str):
        fp.write_text(payload, encoding='utf-8')
    else:
        fp.write_text(json.dumps(payload if payload is not None else {
            'version': 1, 'position': 'append',
            'root': [{'id': 'n_stub_h', 'type': 'heading',
                      'props': {'text': 'X'}, 'children': [],
                      'visibility': {}}],
        }), encoding='utf-8')
    return fp


def _frag(node_type='heading', nid='n_f_h', props=None, position='append',
          after=None):
    frag = {'version': 1, 'position': position,
            'root': [{'id': nid, 'type': node_type,
                      'props': props if props is not None
                      else {'text': 'T', 'level': 2},
                      'children': [], 'visibility': {}}]}
    if after:
        frag['after'] = after
    return frag


def _base():
    return {'version': 1, 'root': [
        {'id': 'b1', 'type': 'heading', 'props': {'text': 'B1'},
         'children': [], 'visibility': {}},
        {'id': 'b2', 'type': 'text', 'props': {'content': 'B2'},
         'children': [], 'visibility': {}},
    ]}


def _types(nodes):
    return [n.get('type') for n in nodes]


# ------------------------------------------------------------
# 发现
# ------------------------------------------------------------

class TestDiscover:
    def test_valid_scopes(self, tmp_path):
        _write_frag(tmp_path, 'home.json')
        _write_frag(tmp_path, 'page.json',
                    {'version': 1, 'root': [
                        {'id': 'p1', 'type': 'text',
                         'props': {'content': 'p'},
                         'children': [], 'visibility': {}}]})
        layouts = contrib.discover_package_layouts(str(tmp_path))
        assert set(layouts.keys()) == {'home', 'page'}
        assert layouts['home'][0]['position'] == 'append'

    def test_no_builder_dir(self, tmp_path):
        assert contrib.discover_package_layouts(str(tmp_path)) == {}

    def test_unknown_filename_rejected(self, tmp_path):
        _write_frag(tmp_path, 'shop.json')
        with pytest.raises(ValueError, match='不被识别'):
            contrib.discover_package_layouts(str(tmp_path))

    def test_bad_json_rejected(self, tmp_path):
        _write_frag(tmp_path, payload='{not json')
        with pytest.raises(ValueError, match='不是合法 JSON'):
            contrib.discover_package_layouts(str(tmp_path))

    def test_bad_structure_rejected(self, tmp_path):
        _write_frag(tmp_path, payload={'version': 1, 'root': []})
        with pytest.raises(ValueError, match='root'):
            contrib.discover_package_layouts(str(tmp_path))

    def test_bad_position_rejected(self, tmp_path):
        _write_frag(tmp_path, payload={
            'version': 1, 'position': 'middle',
            'root': [{'id': 'x', 'type': 'heading',
                      'props': {'text': 'x'}, 'children': [],
                      'visibility': {}}]})
        with pytest.raises(ValueError, match='position'):
            contrib.discover_package_layouts(str(tmp_path))


# ------------------------------------------------------------
# 合并引擎
# ------------------------------------------------------------

class TestCompose:
    @pytest.fixture
    def owners(self):
        created = []

        def reg(owner, scope, fragments):
            contrib.register_owner_layouts(
                owner, {scope: fragments if isinstance(fragments, list)
                        else [fragments]})
            created.append(owner)

        yield reg
        for o in created:
            contrib.unregister_owner(o)

    def test_prepend_and_append_order(self, app, owners):
        owners('zzz_frag', 'home', _frag(nid='n_z', position='append'))
        owners('aaa_frag', 'home', _frag(nid='n_a', position='prepend'))
        out = contrib.compose_layout(_base(), 'home',
                                     enabled=['zzz_frag', 'aaa_frag'])
        ids = [n['id'] for n in out['root']]
        # prepend 按 slug 升序在最前，append 升序在最后
        assert ids == ['n_a', 'b1', 'b2', 'n_z']

    def test_disabled_owner_not_merged(self, app, owners):
        owners('off_frag', 'home', _frag(nid='n_off'))
        out = contrib.compose_layout(_base(), 'home', enabled=[])
        assert [n['id'] for n in out['root']] == ['b1', 'b2']

    def test_anchor_insertion(self, app, owners):
        owners('anc_frag', 'home', _frag(nid='n_anc', after='b1'))
        out = contrib.compose_layout(_base(), 'home', enabled=['anc_frag'])
        assert [n['id'] for n in out['root']] == ['b1', 'n_anc', 'b2']

    def test_missing_anchor_falls_back_to_tail(self, app, owners):
        owners('anc_frag', 'home', _frag(nid='n_anc', after='ghost'))
        out = contrib.compose_layout(_base(), 'home', enabled=['anc_frag'])
        assert [n['id'] for n in out['root']] == ['b1', 'b2', 'n_anc']

    def test_id_collision_rewritten(self, app, owners):
        owners('dup', 'home', _frag(nid='b1'))
        out = contrib.compose_layout(_base(), 'home', enabled=['dup'])
        ids = [n['id'] for n in out['root']]
        assert ids.count('b1') == 1
        assert 'n_dup__b1' in ids

    def test_bad_fragment_isolated(self, app, owners):
        owners('bad_frag', 'home', _frag(node_type='no-such-widget'))
        owners('ok_frag', 'home', _frag(nid='n_ok'))
        out = contrib.compose_layout(
            _base(), 'home', enabled=['bad_frag', 'ok_frag'])
        ids = [n['id'] for n in out['root']]
        assert 'n_ok' in ids
        assert all(n.get('type') != 'no-such-widget' for n in out['root'])

    def test_input_not_mutated(self, app, owners):
        owners('mut_frag', 'home', _frag(nid='n_mut'))
        base = _base()
        before = json.dumps(base, sort_keys=True)
        contrib.compose_layout(base, 'home', enabled=['mut_frag'])
        assert json.dumps(base, sort_keys=True) == before

    def test_unknown_scope_returns_base(self, app, owners):
        owners('sc_frag', 'home', _frag(nid='n_sc'))
        out = contrib.compose_layout(_base(), 'shop', enabled=['sc_frag'])
        assert [n['id'] for n in out['root']] == ['b1', 'b2']


# ------------------------------------------------------------
# 启用校验
# ------------------------------------------------------------

class TestEnableValidation:
    def test_official_fragments_valid(self, app):
        # 4 个内容型插件随包片段必须全部通过校验（锁定清单）
        for slug in PLUGINS:
            assert contrib.validation_error(slug) is None, slug

    def test_invalid_fragment_rejects_enable(self, app):
        from app.plugin_system import validate_enable
        owner = 'analytics'  # 已加载、无依赖的内置插件，借其记录跑校验链
        with app.app_context():
            try:
                contrib.register_owner_layouts(owner, {'home': [_frag(
                    node_type='no-such-widget', nid='n_bad')]})
                err = validate_enable(owner)
                assert err is not None
                assert '页面构建器布局片段不合法' in err
            finally:
                contrib.unregister_owner(owner)
            assert validate_enable(owner) is None

    def test_discovery_error_rejects_enable(self, app):
        from app.plugin_system import validate_enable
        owner = 'analytics'
        with app.app_context():
            try:
                contrib.register_owner_error(owner, 'builder/home.json 坏 JSON')
                err = validate_enable(owner)
                assert err is not None and '布局片段不合法' in err
            finally:
                contrib.unregister_owner(owner)


# ------------------------------------------------------------
# init_default_layout 快照集成 + 前台渲染
# ------------------------------------------------------------

class TestDefaultLayoutSnapshot:
    @staticmethod
    def _set_enabled(app, slugs):
        from app.plugin_system import (enable_plugin, disable_plugin,
                                       enabled_slugs)
        with app.app_context():
            for slug in list(enabled_slugs()):
                disable_plugin(slug)
            for slug in slugs:
                assert enable_plugin(slug) is None, slug

    def test_enable_then_init_augments_home(self, app):
        from app.builder import service
        from app.builder.service import loads_layout, iter_layout_nodes
        self._set_enabled(app, PLUGINS)
        try:
            with app.app_context():
                page, err = service.init_default_layout('home')
                assert err is None
                layout = loads_layout(page.draft_json)
                all_types = {n.get('type')
                             for n in iter_layout_nodes(layout)}
                for t in WIDGET_TYPES.values():
                    assert t in all_types
                root = layout['root']
                # banner 为 prepend：位于根节点首位
                assert root[0]['type'] == 'banner-hero'
                # append 三个 section 按 slug 升序收尾，组件节点在其内部
                assert [root[-3]['id'], root[-2]['id'], root[-1]['id']] == \
                    ['n_prd_sec', 'n_job_sec', 'n_tut_sec']
        finally:
            self._set_enabled(app, ())

    def test_disabled_plugins_not_in_snapshot(self, app):
        from app.builder import service
        from app.builder.service import loads_layout, iter_layout_nodes
        self._set_enabled(app, ['banner'])
        try:
            with app.app_context():
                page, err = service.init_default_layout('home')
                assert err is None
                layout = loads_layout(page.draft_json)
                all_types = {n.get('type')
                             for n in iter_layout_nodes(layout)}
                assert 'banner-hero' in all_types
                assert 'product-list' not in all_types
                assert 'job-list' not in all_types
                assert 'tutorial-list' not in all_types
        finally:
            self._set_enabled(app, ())

    def test_widget_catalog_enabled_flag(self, app):
        from app.builder.registry import widget_catalog
        self._set_enabled(app, ['banner'])
        try:
            with app.app_context():
                catalog = widget_catalog('home')
                flat = {w['type']: w for group in catalog.values()
                        for w in group}
                assert flat['banner-hero']['enabled'] is True
                assert flat['banner-hero']['owner'] == 'banner'
                assert flat['product-list']['enabled'] is False
        finally:
            self._set_enabled(app, ())

    def test_published_home_renders_plugin_widgets(self, app, client):
        from app.builder import service
        from app.builder.service import loads_layout
        from app.extensions import db
        from app.models.column import Column
        from plugins.banner.models import BannerGroup, Banner
        from plugins.product.models import Product
        from plugins.recruit.models import RecruitJob
        from plugins.tutorial.models import Tutorial, TutorialCategory
        tag = uuid.uuid4().hex[:6]
        self._set_enabled(app, PLUGINS)
        try:
            with app.app_context():
                page, err = service.init_default_layout('home')
                assert err is None
                layout = loads_layout(page.draft_json)
                rev, err = service.publish_page(page, layout)
                assert err is None
                # banner 轮播数据
                g = BannerGroup(name='快照分组' + tag, slug='home-hero',
                                is_enabled=True)
                db.session.add(g)
                db.session.flush()
                db.session.add(Banner(group_id=g.id, title='快照轮播图' + tag,
                                      external_url='https://example.com/x.jpg',
                                      link_target='_blank', is_enabled=True))
                # product 数据（复用核心栏目树）
                col = Column(name='快照产品线' + tag, slug='cp-' + tag,
                             type='list', is_enabled=True, is_deleted=False)
                db.session.add(col)
                db.session.flush()
                db.session.add(Product(column_id=col.id,
                                       title='快照产品' + tag,
                                       summary='产品简介', is_enabled=True))
                # recruit 数据
                db.session.add(RecruitJob(title='快照岗位' + tag,
                                          department='研发部', location='北京',
                                          salary='20-30k', is_enabled=True))
                # tutorial 数据
                tc = TutorialCategory(name='快照分类' + tag,
                                      slug='cc-' + tag, is_enabled=True)
                db.session.add(tc)
                db.session.flush()
                db.session.add(Tutorial(category_id=tc.id,
                                        title='快照教程' + tag,
                                        slug='ct-' + tag, content='<p>正文</p>',
                                        summary='教程简介',
                                        difficulty='beginner', duration=30,
                                        is_enabled=True))
                db.session.commit()
            resp = client.get('/')
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)
            # 组件容器与真实数据
            assert 'zbw-banner-hero' in html
            assert '快照轮播图' + tag in html
            assert 'zbw-product-list' in html
            assert '快照产品' + tag in html
            assert 'zbw-job-list' in html
            assert '快照岗位' + tag in html
            assert '更多职位' in html
            assert 'zbw-tutorial-list' in html
            assert '快照教程' + tag in html
            assert '进入教程中心' in html
            # 三个 append 区块标题
            assert '产品中心' in html
            assert '招贤纳士' in html
            assert '教程中心' in html
        finally:
            self._set_enabled(app, ())


# ------------------------------------------------------------
# 随包片段文件存在性（新增插件片段时显式可见）
# ------------------------------------------------------------

def test_official_plugin_fragment_files(app):
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for slug in PLUGINS:
        fp = os.path.join(root, 'plugins', slug, 'builder', 'home.json')
        assert os.path.isfile(fp), slug
