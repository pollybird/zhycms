"""插件依赖 / 继承 / 最低核心版本校验测试（v2.6.4）。

验证：
- 版本号解析与比较
- 启用时 min_core_version 校验
- 启用时 requires 依赖校验（缺失/未启用/已满足）
- 启用时 extends 父插件校验（未安装/未启用/已启用）
- 禁用时反向依赖校验（被依赖插件不可禁用）
"""
import pytest


@pytest.mark.plugins
class TestVersionComparison:

    def test_parse_and_compare(self):
        from app.plugin_system import parse_version, version_cmp
        assert parse_version('2.6.3') == (2, 6, 3)
        assert parse_version('') == (0,)
        assert parse_version('2.6') == (2, 6)
        assert version_cmp('2.6.3', '2.6.3') == 0
        assert version_cmp('2.6.3', '2.7.0') == -1
        assert version_cmp('2.6.3', '2.6.2') == 1
        assert version_cmp('2.6', '2.6.0') == 0   # 缺位补 0
        assert version_cmp('10.1', '9.9') == 1     # 字符串比较陷阱


@pytest.mark.plugins
class TestPluginDependencyValidation:

    def _patch_manifest(self, slug, **fields):
        from app import plugin_system as ps
        rec = ps.get_record(slug)
        saved = rec.manifest.copy()
        rec.manifest.update(fields)
        return rec, saved

    def test_min_core_version_too_high_blocked(self, app):
        from app import plugin_system as ps
        with app.app_context():
            rec, saved = self._patch_manifest('banner', min_core_version='99.0.0')
            ps.disable_plugin('banner')
            try:
                err = ps.enable_plugin('banner')
                assert err is not None and '低于' in err
            finally:
                rec.manifest = saved

    def test_min_core_version_satisfied(self, app):
        from app import plugin_system as ps
        with app.app_context():
            rec, saved = self._patch_manifest('banner', min_core_version='1.0.0')
            ps.disable_plugin('banner')
            try:
                assert ps.enable_plugin('banner') is None
            finally:
                rec.manifest = saved

    def test_requires_missing_dependency_blocked(self, app):
        from app import plugin_system as ps
        with app.app_context():
            rec, saved = self._patch_manifest('banner', requires=['not_installed_dep'])
            ps.disable_plugin('banner')
            try:
                err = ps.enable_plugin('banner')
                assert err is not None and '缺少依赖' in err
            finally:
                rec.manifest = saved

    def test_requires_disabled_dependency_blocked(self, app):
        from app import plugin_system as ps
        with app.app_context():
            ps.disable_plugin('form')
            rec, saved = self._patch_manifest('banner', requires=['form'])
            ps.disable_plugin('banner')
            try:
                err = ps.enable_plugin('banner')
                assert err is not None and '先启用依赖' in err
            finally:
                rec.manifest = saved

    def test_requires_enabled_dependency_passes(self, app):
        from app import plugin_system as ps
        with app.app_context():
            ps.enable_plugin('form')
            rec, saved = self._patch_manifest('banner', requires=['form'])
            ps.disable_plugin('banner')
            try:
                assert ps.enable_plugin('banner') is None
            finally:
                rec.manifest = saved

    def test_extends_parent_not_installed_blocked(self, app):
        from app import plugin_system as ps
        with app.app_context():
            rec, saved = self._patch_manifest('banner', extends='nonexistent_parent')
            ps.disable_plugin('banner')
            try:
                err = ps.enable_plugin('banner')
                assert err is not None and '未安装' in err
            finally:
                rec.manifest = saved

    def test_extends_parent_not_enabled_blocked(self, app):
        from app import plugin_system as ps
        with app.app_context():
            ps.disable_plugin('form')
            rec, saved = self._patch_manifest('banner', extends='form')
            ps.disable_plugin('banner')
            try:
                err = ps.enable_plugin('banner')
                assert err is not None and '先启用父插件' in err
            finally:
                rec.manifest = saved

    def test_extends_parent_enabled_passes(self, app):
        from app import plugin_system as ps
        with app.app_context():
            ps.enable_plugin('form')
            rec, saved = self._patch_manifest('banner', extends='form')
            ps.disable_plugin('banner')
            try:
                assert ps.enable_plugin('banner') is None
            finally:
                rec.manifest = saved

    def test_disable_depended_plugin_blocked(self, app):
        """被其他已启用插件 requires/extends 的插件不可禁用。"""
        from app import plugin_system as ps
        with app.app_context():
            ps.enable_plugin('form')
            rec, saved = self._patch_manifest('banner', requires=['form'])
            try:
                ps.enable_plugin('banner')
                err = ps.disable_plugin('form')
                assert err is not None and '依赖' in err
                # 先禁用 banner，再禁用 form 成功
                assert ps.disable_plugin('banner') is None
                assert ps.disable_plugin('form') is None
            finally:
                rec.manifest = saved

    def test_existing_plugins_all_enable(self, app):
        """现有插件（min_core_version 均 ≤ 当前版本）可正常启用。"""
        from app import plugin_system as ps
        with app.app_context():
            for slug in ('banner', 'form', 'product', 'member'):
                assert ps.enable_plugin(slug) is None, f'{slug} 应能启用'
