"""插件全生命周期测试（v2.6.2 W2）。

以官方 banner 插件为被测对象，验证「启用 → 使用 → 禁用 → 重新启用」全链路：
- 启用：种子权限点、预设角色补授权、兜底建表、写启用清单，且幂等
- 使用：后台路由 200、编辑角色可访问、API 端点、模板全局函数、后台菜单
- 禁用：路由/API 404、菜单隐藏、模板函数回退空值、**数据保留**
- 重新启用：数据仍在、权限不重复、路由恢复
- 异常：不存在/未加载插件返回错误信息

禁用不删表不丢数据是硬约束（MEMORY：插件启停机制）。
"""
import uuid

import pytest
from sqlalchemy import inspect as sa_inspect

lifecycle = pytest.mark.lifecycle

PLUGIN = 'banner'


def _enable(app, slug=PLUGIN):
    from app.plugin_system import enable_plugin
    with app.app_context():
        err = enable_plugin(slug)
        assert err is None, f'启用插件失败: {err}'


def _disable(app, slug=PLUGIN):
    from app.plugin_system import disable_plugin
    with app.app_context():
        disable_plugin(slug)


def _clear_cache(app):
    """清空应用缓存，避免 API/模板函数缓存串生命周期阶段。"""
    with app.app_context():
        from app.extensions import cache
        cache.clear()


def _make_group(app, name='生命周期分组'):
    """创建轮播分组 + 一张外链图轮播项，返回 slug。"""
    from app.extensions import db
    from plugins.banner.models import BannerGroup, Banner
    slug = 'lc-' + uuid.uuid4().hex[:8]
    with app.app_context():
        g = BannerGroup(name=name, slug=slug, is_enabled=True)
        db.session.add(g)
        db.session.flush()
        db.session.add(Banner(group_id=g.id, title='测试图',
                              external_url='https://example.com/a.jpg',
                              is_enabled=True))
        db.session.commit()
    return slug


def _login(client, uid):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True
    return client


def _editor_uid(app):
    """创建 content_editor 角色用户（启用插件后预设授权含 banner:manage）。"""
    from app.extensions import db
    from app.models.rbac import Role
    from tests.factories import make_user
    with app.app_context():
        user = make_user(username='lc_' + uuid.uuid4().hex[:8],
                         role=Role.get_by_code('content_editor'))
        db.session.commit()
        return user.id


@lifecycle
class TestEnable:
    """启用：副作用完整且幂等。"""

    def test_enable_writes_setting_and_returns_none(self, app):
        from app.plugin_system import enabled_slugs
        _enable(app)
        with app.app_context():
            assert PLUGIN in enabled_slugs()

    def test_enable_seeds_permission_and_role_grants(self, app):
        from app.models.rbac import Permission, Role, RolePermission
        _enable(app)
        with app.app_context():
            assert Permission.query.filter_by(code='banner:manage').first() is not None
            for role_code in ('content_auditor', 'content_editor'):
                role = Role.query.filter_by(code=role_code).first()
                assert role is not None
                grant = RolePermission.query.filter_by(
                    role_id=role.id, permission_code='banner:manage').first()
                assert grant is not None, f'{role_code} 未获得 banner:manage'

    def test_enable_creates_plugin_tables(self, app):
        _enable(app)
        with app.app_context():
            from app.extensions import db as _db
            tables = set(sa_inspect(_db.engine).get_table_names())
            assert {'banner_groups', 'banners'} <= tables

    def test_enable_idempotent(self, app):
        """二次启用不报错、权限点不重复。"""
        from app.plugin_system import enable_plugin
        from app.models.rbac import Permission
        _enable(app)
        with app.app_context():
            assert enable_plugin(PLUGIN) is None
            assert Permission.query.filter_by(code='banner:manage').count() == 1

    def test_enable_unknown_slug_reports_error(self, app):
        from app.plugin_system import enable_plugin
        with app.app_context():
            assert enable_plugin('ghost_' + uuid.uuid4().hex[:6]) is not None


@lifecycle
class TestEnabledUsage:
    """启用中：路由、权限、模板函数、菜单、API 可用。"""

    def test_admin_route_200(self, app, admin_client):
        _enable(app)
        assert admin_client.get('/admin/banners').status_code == 200

    def test_editor_via_preset_grant_200(self, app, client):
        """启用后 content_editor 预设补授权 banner:manage → 编辑可进管理页。"""
        _enable(app)
        uid = _editor_uid(app)
        _login(client, uid)
        assert client.get('/admin/banners').status_code == 200

    def test_jinja_global_returns_real_data(self, app):
        """启用时模板函数返回分组真实数据（非 fallback 空值路径）。"""
        _enable(app)
        slug = _make_group(app)
        _clear_cache(app)
        with app.app_context():
            fn = app.jinja_env.globals['banner_items']
            items = fn(slug)
            assert len(items) == 1
            assert items[0]['image_url'] == 'https://example.com/a.jpg'

    def test_admin_menu_visible(self, app):
        from app.plugin_system import plugin_admin_menus
        from app.models.user import User
        from flask_login import login_user
        _enable(app)
        with app.test_request_context('/admin/'):
            admin = User.query.filter_by(username='admin').first()
            login_user(admin)
            menus = {m['slug']: m for m in plugin_admin_menus()}
            assert PLUGIN in menus
            endpoints = [i.get('endpoint') for i in menus[PLUGIN]['items']]
            assert 'admin.banner_group_index' in endpoints

    def test_api_endpoint_serves_group(self, app, client):
        _enable(app)
        slug = _make_group(app)
        _clear_cache(app)
        resp = client.get(f'/api/v1/banners/{slug}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['code'] == 0
        assert len(data['data']) == 1


@lifecycle
class TestDisable:
    """禁用：门控生效，数据保留。"""

    def test_disable_removes_setting(self, app):
        from app.plugin_system import enabled_slugs
        _enable(app)
        _disable(app)
        with app.app_context():
            assert PLUGIN not in enabled_slugs()

    def test_admin_route_404_when_disabled(self, app, admin_client):
        _enable(app)
        _disable(app)
        assert admin_client.get('/admin/banners').status_code == 404

    def test_editor_route_404_when_disabled(self, app, client):
        _enable(app)
        uid = _editor_uid(app)
        _disable(app)
        _login(client, uid)
        assert client.get('/admin/banners').status_code == 404

    def test_jinja_global_falls_back_empty_when_disabled(self, app):
        """禁用后模板函数走 fallback 返回空列表，真实数据被隐藏。"""
        _enable(app)
        slug = _make_group(app)
        _clear_cache(app)
        _disable(app)
        with app.app_context():
            from app.extensions import db
            from plugins.banner.models import BannerGroup
            assert BannerGroup.query.filter_by(slug=slug).first() is not None  # 数据仍在
            fn = app.jinja_env.globals['banner_items']
            assert fn(slug) == []

    def test_api_404_when_disabled(self, app, client):
        _enable(app)
        slug = _make_group(app)
        _disable(app)
        _clear_cache(app)
        resp = client.get(f'/api/v1/banners/{slug}')
        assert resp.status_code == 404
        assert resp.get_json()['code'] == 404

    def test_menu_hidden_when_disabled(self, app):
        from app.plugin_system import plugin_admin_menus
        from app.models.user import User
        from flask_login import login_user
        _enable(app)
        _disable(app)
        with app.test_request_context('/admin/'):
            admin = User.query.filter_by(username='admin').first()
            login_user(admin)
            menus = {m['slug'] for m in plugin_admin_menus()}
            assert PLUGIN not in menus

    def test_data_and_tables_preserved(self, app):
        """禁用不删表不丢数据（硬约束）。"""
        _enable(app)
        slug = _make_group(app)
        _disable(app)
        with app.app_context():
            from app.extensions import db
            from plugins.banner.models import BannerGroup
            tables = set(sa_inspect(db.engine).get_table_names())
            assert {'banner_groups', 'banners'} <= tables
            assert BannerGroup.query.filter_by(slug=slug).first() is not None


@lifecycle
class TestReEnable:
    """重新启用：数据延续、权限幂等、功能恢复。"""

    def test_reenable_restores_route_and_data(self, app, admin_client):
        _enable(app)
        slug = _make_group(app)
        _disable(app)
        _clear_cache(app)
        _enable(app)
        assert admin_client.get('/admin/banners').status_code == 200
        with app.app_context():
            from plugins.banner.models import BannerGroup
            g = BannerGroup.query.filter_by(slug=slug).first()
            assert g is not None
            assert g.items.count() == 1  # 轮播项数据完好

    def test_reenable_does_not_duplicate_grants(self, app):
        from app.models.rbac import Role, RolePermission
        _enable(app)
        _disable(app)
        _enable(app)
        with app.app_context():
            role = Role.query.filter_by(code='content_editor').first()
            assert RolePermission.query.filter_by(
                role_id=role.id, permission_code='banner:manage').count() == 1

    def test_full_cycle_api_consistency(self, app, client):
        """启用 200 → 禁用 404 → 再启用 200，同一资源一致。"""
        _enable(app)
        slug = _make_group(app)
        _clear_cache(app)
        assert client.get(f'/api/v1/banners/{slug}').status_code == 200
        _disable(app)
        _clear_cache(app)
        assert client.get(f'/api/v1/banners/{slug}').status_code == 404
        _enable(app)
        _clear_cache(app)
        assert client.get(f'/api/v1/banners/{slug}').status_code == 200
