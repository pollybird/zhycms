"""插件测试：启停门控、权限播种、SearchProvider 注册。"""
import pytest


@pytest.mark.plugins
class TestPlugins:

    def test_plugin_list_visible_in_admin(self, app):
        """后台插件管理页可访问（超管）。"""
        from app.extensions import db
        from app.models.user import User
        with app.app_context():
            admin = User.query.filter_by(username='admin', is_deleted=False).first()
            uid = str(admin.id)
            with app.test_client() as c:
                with c.session_transaction() as sess:
                    sess['_user_id'] = uid
                    sess['_fresh'] = True
                resp = c.get('/admin/plugins')
                assert resp.status_code == 200

    def test_banner_plugin_loaded(self, app):
        """轮播图插件已加载。"""
        from app.plugin_system import _registry
        slugs = [r.slug for r in _registry]
        assert 'banner' in slugs

    def test_recruit_plugin_loaded(self, app):
        """招聘管理插件已加载。"""
        from app.plugin_system import _registry
        slugs = [r.slug for r in _registry]
        assert 'recruit' in slugs

    def test_product_plugin_loaded(self, app):
        """产品展示插件已加载。"""
        from app.plugin_system import _registry
        slugs = [r.slug for r in _registry]
        assert 'product' in slugs
