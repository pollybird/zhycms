"""主题切换缓存一致性回归测试（v2.6.3 修复）。

复现：开启前台整页缓存后，切换主题若不清缓存且缓存键不含主题，
旧主题渲染的整页 HTML 会在 TTL 内继续命中，导致不同页面主题不一致。
"""
import pytest


@pytest.fixture
def cache_isolation(app, client):
    """开启页面缓存，结束后恢复现场（主题 / 缓存开关 / 清空缓存）。"""
    from app.extensions import db, cache
    from app.models.setting import Setting
    with app.app_context():
        old_theme = Setting.get('site_theme') or 'default'
        old_cache_enable = Setting.get('cache_enable') or 'off'
        Setting.set('cache_enable', 'on')
        db.session.commit()
        cache.clear()
    yield client
    with app.app_context():
        Setting.set('site_theme', old_theme)
        Setting.set('cache_enable', old_cache_enable)
        db.session.commit()
        cache.clear()


def _set_theme(app, slug):
    from app.extensions import db
    from app.models.setting import Setting
    with app.app_context():
        Setting.set('site_theme', slug)
        db.session.commit()


class TestThemeSwitchCache:

    def test_cache_key_includes_theme_no_cross_leak(self, cache_isolation, app):
        """纵深防御：即使不清缓存，不同主题也不串页（缓存键含主题）。"""
        client = cache_isolation
        # 用 default 渲染并建立缓存
        _set_theme(app, 'default')
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'/themes/default/css/style.css' in resp.data

        # 直接改库（故意不触发清缓存），验证缓存键隔离使新主题不命中旧缓存
        _set_theme(app, 'education')
        resp2 = client.get('/')
        assert resp2.status_code == 200
        assert b'/themes/education/css/style.css' in resp2.data
        assert b'/themes/default/css/style.css' not in resp2.data

    def test_theme_activate_endpoint_clears_cache(self, cache_isolation, app,
                                                  admin_client):
        """后台激活主题后，已缓存页面立即呈现新主题。"""
        client = cache_isolation
        # 先用 default 建立首页缓存
        _set_theme(app, 'default')
        resp = client.get('/')
        assert b'/themes/default/css/style.css' in resp.data

        # 走后台激活路由（自带 cache.clear）
        resp_act = admin_client.post('/admin/themes/education/activate',
                                     follow_redirects=False)
        assert resp_act.status_code in (302, 303)

        # 切换后首页必须是新主题，而非命中旧缓存
        resp2 = client.get('/')
        assert resp2.status_code == 200
        assert b'/themes/education/css/style.css' in resp2.data
        assert b'/themes/default/css/style.css' not in resp2.data
