"""行业主题校验测试（v2.6.3）：education / catering 必备模板完整性。

v3.0.0 追加：第三方主题包内可选 builder/<scope>.json 必须随包通过
构建器布局校验；不携带 builder/ 目录的主题回退核心默认布局。
"""
import json
import os

import pytest


@pytest.mark.themes
class TestIndustryThemes:

    @pytest.fixture
    def theme_records(self, app):
        from app.utils.themes import list_theme_records
        with app.app_context():
            return list_theme_records()

    def test_education_theme_registered(self, theme_records):
        """education 主题被系统识别且为内置主题。"""
        edu = next((r for r in theme_records if r['slug'] == 'education'), None)
        assert edu is not None, 'education 主题未被发现'
        assert edu['builtin'] is True

    def test_education_theme_complete(self, theme_records):
        """education 主题必备模板完整无缺失。"""
        edu = next((r for r in theme_records if r['slug'] == 'education'), None)
        assert edu is not None
        assert len(edu['missing_required_files']) == 0, \
            f"education 缺失必备模板: {edu['missing_required_files']}"

    def test_catering_theme_registered(self, theme_records):
        """catering 主题被系统识别且为内置主题。"""
        cat = next((r for r in theme_records if r['slug'] == 'catering'), None)
        assert cat is not None, 'catering 主题未被发现'
        assert cat['builtin'] is True

    def test_catering_theme_complete(self, theme_records):
        """catering 主题必备模板完整无缺失。"""
        cat = next((r for r in theme_records if r['slug'] == 'catering'), None)
        assert cat is not None
        assert len(cat['missing_required_files']) == 0, \
            f"catering 缺失必备模板: {cat['missing_required_files']}"

    def test_education_templates_have_html(self, theme_records):
        """education 主题包含至少基础数量的模板文件。"""
        edu = next((r for r in theme_records if r['slug'] == 'education'), None)
        assert edu is not None
        assert edu['template_count'] >= 10

    def test_catering_templates_have_html(self, theme_records):
        """catering 主题包含至少基础数量的模板文件。"""
        cat = next((r for r in theme_records if r['slug'] == 'catering'), None)
        assert cat is not None
        assert cat['template_count'] >= 10


@pytest.mark.themes
class TestDeleteConfirmCaptcha:
    """删除主题/卸载插件确认弹窗必须渲染验证码 UI（v3.1.1 线上回归）。

    后端 theme_delete / plugin_delete 均校验一次性图片验证码
    （/captcha/delete-confirm），但两个页面此前均未渲染验证码图片与
    输入框，导致弹窗无码可看、提交必报「验证码已过期」。
    """

    def test_theme_page_renders_delete_captcha(self, admin_client):
        html = admin_client.get('/admin/themes').get_data(as_text=True)
        assert 'name="captcha"' in html
        assert '/captcha/delete-confirm' in html

    def test_plugin_page_renders_delete_captcha(self, admin_client):
        html = admin_client.get('/admin/plugins').get_data(as_text=True)
        assert 'name="captcha"' in html
        assert '/captcha/delete-confirm' in html

    def test_delete_captcha_image_endpoint(self, admin_client):
        resp = admin_client.get('/admin/captcha/delete-confirm')
        assert resp.status_code == 200
        assert resp.content_type == 'image/png'


# ------------------------------------------------------------
# v3.0.0 第三方主题包：builder 默认布局 fixture 随包校验
# ------------------------------------------------------------

def _make_theme_package(tmp_path, slug, builder_files=None):
    """构造形态 B（单层子目录含 manifest）的主题包根目录。"""
    pkg = tmp_path / 'unpacked' / slug
    pkg.mkdir(parents=True)
    (pkg / 'manifest.json').write_text(json.dumps({
        'slug': slug, 'name': '测试主题', 'version': '1.0'},
        ensure_ascii=False), encoding='utf-8')
    from app.utils.themes import THEME_REQUIRED_FILES
    for fname in THEME_REQUIRED_FILES:
        (pkg / fname).write_text('<!-- tpl -->', encoding='utf-8')
    if builder_files:
        (pkg / 'builder').mkdir()
        for name, content in builder_files.items():
            (pkg / 'builder' / name).write_text(content, encoding='utf-8')
    return tmp_path / 'unpacked'


class TestThemePackageBuilderFixtures:
    def _validate(self, tmp_path, slug='ztm_pkg', builder_files=None):
        from app.admin.system.themes import _validate_theme_package
        unpacked = _make_theme_package(tmp_path, slug,
                                       builder_files=builder_files)
        themes_dir = tmp_path / 'themes_target'
        themes_dir.mkdir()
        return _validate_theme_package(str(unpacked), str(themes_dir))

    def test_package_without_builder_dir_passes(self, tmp_path, app):
        """第三方主题不带 builder/ → 合法（构建器运行时回退核心默认）。"""
        with app.test_request_context():
            _root, slug, _mf, _meta = self._validate(tmp_path)
        assert slug == 'ztm_pkg'

    def test_valid_builder_fixture_passes(self, tmp_path, app):
        core = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'app', 'builder', 'fixtures', 'home.json')
        with open(core, encoding='utf-8') as f:
            home_json = f.read()
        with app.test_request_context():
            root, slug, _mf, _meta = self._validate(
                tmp_path, 'ztm_valid',
                builder_files={'home.json': home_json})
        assert slug == 'ztm_valid'
        assert os.path.isfile(os.path.join(root, 'builder', 'home.json'))

    def test_malformed_json_rejected(self, tmp_path, app):
        with app.test_request_context():
            with pytest.raises(ValueError, match='builder/home.json'):
                self._validate(tmp_path, 'ztm_bad1',
                               builder_files={'home.json': '{not json'})

    def test_unknown_widget_type_rejected(self, tmp_path, app):
        """引用未注册组件（如未安装插件的组件）→ 拒绝上传。"""
        layout = {'root': [{
            'id': 'x1', 'type': 'totally-unknown-widget',
            'props': {}, 'children': []}]}
        with app.test_request_context():
            with pytest.raises(ValueError, match='builder/home.json'):
                self._validate(tmp_path, 'ztm_bad2',
                               builder_files={'home.json':
                                              json.dumps(layout)})

    def test_unknown_scope_filename_rejected(self, tmp_path, app):
        with app.test_request_context():
            with pytest.raises(ValueError, match='home2.json'):
                self._validate(tmp_path, 'ztm_bad3',
                               builder_files={'home2.json': '{}'})


class TestActivateRejectsDirtyFixtures:
    """启用路由复检 builder fixture：上传校验上线前的脏目录也不能启用。"""

    def _plant(self, themes_root, slug='zt_dirty'):
        d = themes_root / slug
        d.mkdir()
        (d / 'manifest.json').write_text(json.dumps({
            'slug': slug, 'name': '脏主题', 'version': '1'},
            ensure_ascii=False), encoding='utf-8')
        from app.utils.themes import THEME_REQUIRED_FILES
        for fname in THEME_REQUIRED_FILES:
            (d / fname).write_text('<!-- x -->', encoding='utf-8')
        (d / 'builder').mkdir()
        (d / 'builder' / 'home.json').write_text(json.dumps(
            {'root': [{'id': 'x1', 'type': 'nope-widget',
                       'props': {}, 'children': []}]}), encoding='utf-8')
        return d

    def test_activate_blocked_for_dirty_theme(self, tmp_path, app,
                                               admin_client, monkeypatch):
        import app.utils.themes as themes_util
        import app.admin.system.themes as themes_admin
        self._plant(tmp_path)
        monkeypatch.setattr(themes_util, 'THEMES_DIR', str(tmp_path))
        monkeypatch.setattr(themes_admin, 'THEMES_DIR', str(tmp_path))

        from app.models import Setting
        with app.app_context():
            before = Setting.get('site_theme') or 'default'

        resp = admin_client.post('/admin/themes/zt_dirty/activate',
                                 follow_redirects=True)
        text = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert '无法启用' in text and 'builder/home.json' in text

        with app.app_context():
            assert (Setting.get('site_theme') or 'default') == before

    def test_activate_rejects_illegal_slug(self, tmp_path, app,
                                           admin_client, monkeypatch):
        import app.utils.themes as themes_util
        import app.admin.system.themes as themes_admin
        monkeypatch.setattr(themes_util, 'THEMES_DIR', str(tmp_path))
        monkeypatch.setattr(themes_admin, 'THEMES_DIR', str(tmp_path))
        # 含白名单外字符（点号）的 slug 必须拒绝且不触碰文件系统
        resp = admin_client.post('/admin/themes/a.b/activate',
                                 follow_redirects=True)
        assert '非法的主题标识' in resp.get_data(as_text=True)
