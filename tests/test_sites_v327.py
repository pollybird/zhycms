"""v3.2.7 站群部署与可观测回归测试。

覆盖：
  - nginx 站点配置生成（域名/子域/默认兜底/非法域名/幂等）
  - 后台部署指南与证书状态
  - 站点资源指标、可见范围、阈值告警与刷新
  - 每日指标快照幂等与单站失败隔离
  - 插件站点作用域审计与命令行退出码
  - 日志站点标签
  - 审计导出按站点过滤
"""
import html
import importlib.util
import io
import json
import logging
import re
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.extensions import db

pytestmark = pytest.mark.sites


# ============================================================
# 辅助
# ============================================================

def _uniq(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


def _mk_site(app, *, domain=None, subdomain=None, slug=None):
    from app.models.site import Site
    with app.app_context():
        site = Site(name=f'站点-{slug}', slug=slug,
                    domain=domain, subdomain=subdomain)
        db.session.add(site)
        db.session.commit()
        return site.id


def _mk_column(app, site_id, slug=None):
    from app.models.column import Column
    with app.app_context():
        column = Column(site_id=site_id, name='测试栏目',
                        slug=slug or _uniq('col'), type='list')
        db.session.add(column)
        db.session.commit()
        return column.id


def _mk_article(app, site_id, column_id, viewed=0):
    from app.models.article import Article
    with app.app_context():
        article = Article(site_id=site_id, column_id=column_id,
                          title=_uniq('文章'), viewed=viewed)
        db.session.add(article)
        db.session.commit()
        return article.id


def _role_id(code):
    from app.models.rbac import Role
    role = Role.query.filter_by(code=code, is_deleted=False).first()
    assert role is not None, f'预设角色缺失：{code}'
    return role.id


def _mk_user(app, username, assignments):
    from app.models.rbac import UserRole
    from app.models.user import User
    with app.app_context():
        user = User(username=username, is_deleted=False)
        user.set_password('Abcdef123456!')
        db.session.add(user)
        db.session.flush()
        for code, sid in assignments:
            db.session.add(UserRole(
                user_id=user.id, role_id=_role_id(code), site_id=sid))
        db.session.commit()
        return user.id


def _login(client, uid):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True


@pytest.fixture(autouse=True)
def _clean_v327(app):
    """清理本文件创建的站点/用户及指标、审计数据。"""
    yield
    from app.models.article import Article
    from app.models.audit import AuditLog
    from app.models.column import Column
    from app.models.rbac import UserRole
    from app.models.setting import Setting
    from app.models.site import Site
    from app.models.site_metric import SiteMetricSnapshot
    from app.models.user import User

    with app.app_context():
        site_ids = [s.id for s in Site.query.filter(
            Site.slug.like('v327-%')).all()]
        if site_ids:
            SiteMetricSnapshot.query.filter(
                SiteMetricSnapshot.site_id.in_(site_ids)).delete(
                synchronize_session=False)
            AuditLog.query.filter(
                AuditLog.site_id.in_(site_ids)).delete(
                synchronize_session=False)
            Article.query.filter(Article.site_id.in_(site_ids)).delete(
                synchronize_session=False)
            Column.query.filter(Column.site_id.in_(site_ids)).delete(
                synchronize_session=False)
        Site.query.filter(Site.slug.like('v327-%')).delete(
            synchronize_session=False)

        user_ids = [u.id for u in User.query.filter(
            User.username.like('v327-%')).all()]
        if user_ids:
            UserRole.query.filter(UserRole.user_id.in_(user_ids)).delete(
                synchronize_session=False)
            User.query.filter(User.id.in_(user_ids)).delete(
                synchronize_session=False)

        Setting.query.filter(Setting.key.like('site_metric_%')).delete(
            synchronize_session=False)
        db.session.commit()


# ============================================================
# 一、nginx 配置生成
# ============================================================

def test_render_domain_subdomain_and_default_fallback():
    from app.services.site_deploy import render_nginx_config

    sites = [
        SimpleNamespace(id=101, name='域名站', domain='a.example.com',
                        subdomain=None, is_default=False),
        SimpleNamespace(id=102, name='子域站', domain=None,
                        subdomain='news', is_default=False),
        SimpleNamespace(id=0, name='默认站', domain=None,
                        subdomain=None, is_default=True),
    ]
    # 基础域名允许直接传站点网址，渲染时只取主机名
    text, skipped = render_nginx_config(
        sites, base_domain='https://example.com/')

    assert skipped == []
    assert 'server_name a.example.com;' in text
    assert 'server_name news.example.com;' in text
    assert 'server_name _;' in text
    assert text.count('server {') == 3
    # 默认站点兜底块排在最后
    assert text.rfind('# zhycms site 0') > text.find('# zhycms site 101')


def test_render_skips_invalid_domain():
    from app.services.site_deploy import render_nginx_config

    sites = [
        SimpleNamespace(id=201, name='非法站', domain='bad;}.example.com',
                        subdomain=None, is_default=False),
        SimpleNamespace(id=202, name='正常站', domain='ok.example.com',
                        subdomain=None, is_default=False),
    ]
    text, skipped = render_nginx_config(sites, base_domain='example.com')

    assert 'bad;}' not in text
    assert 'ok.example.com' in text
    assert len(skipped) == 1
    assert skipped[0]['site_id'] == 201


def test_render_skips_site_without_hostname():
    from app.services.site_deploy import render_nginx_config

    sites = [
        SimpleNamespace(id=301, name='空站点', domain=None,
                        subdomain=None, is_default=False),
    ]
    text, skipped = render_nginx_config(sites, base_domain='example.com')

    assert text == ''
    assert skipped[0]['site_id'] == 301


def test_render_is_idempotent():
    from app.services.site_deploy import render_nginx_config

    sites = [
        SimpleNamespace(id=401, name='域名站', domain='idem.example.com',
                        subdomain=None, is_default=False),
    ]
    first, _ = render_nginx_config(sites, base_domain='example.com')
    second, _ = render_nginx_config(sites, base_domain='example.com')
    assert first == second


def test_generate_for_app_empty_and_script_exit(app, monkeypatch, capsys):
    from app.services.site_deploy import render_nginx_config

    text, skipped = render_nginx_config([])
    assert text == ''
    assert skipped == []

    spec = importlib.util.spec_from_file_location(
        'v327_nginx_script',
        'scripts/generate_nginx_sites.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr('app.create_app', lambda: app)
    assert module.main(
        ['--stdout', '--skip-validate', '--site-id', '999999']) == 0
    assert '无站点可生成' in capsys.readouterr().out


def test_deploy_page_matches_rendered_fragment(admin_client, app):
    from app.models.setting import Setting
    from app.services.site_deploy import render_site_block

    sid = _mk_site(app, domain='deploy.example.com', slug=_uniq('v327-dep'))
    from app.models.site import Site

    with app.app_context():
        Setting.set('site_url', 'example.com')
        db.session.commit()
        site = db.session.get(Site, sid)
        expected = render_site_block(
            site, base_domain='example.com', upload_max_mb=10)

    _login(admin_client, _admin_id(app))
    resp = admin_client.get(f'/admin/sites/{sid}/deploy')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    match = re.search(r'<pre id="nginx-snippet"[^>]*>(.*?)</pre>',
                      body, re.S)
    assert match is not None
    assert html.unescape(match.group(1)).strip() == expected.strip()


def _admin_id(app):
    from app.models.user import User
    with app.app_context():
        return User.query.filter_by(username='admin').first().id


def test_deploy_page_forbidden_for_content_editor(client, app):
    uid = _mk_user(app, _uniq('v327-editor'), [('content_editor', None)])
    _login(client, uid)
    sid = _mk_site(app, domain='deny.example.com', slug=_uniq('v327-deny'))
    resp = client.get(f'/admin/sites/{sid}/deploy')
    assert resp.status_code == 403


def test_deploy_page_shows_certificate_missing(admin_client, app):
    sid = _mk_site(app, domain='nocert.example.com', slug=_uniq('v327-cert'))
    _login(admin_client, _admin_id(app))
    resp = admin_client.get(f'/admin/sites/{sid}/deploy')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '未配置' in body
    assert 'nocert.example.com' in body


# ============================================================
# 二、站点指标
# ============================================================

def test_metrics_article_and_view_counts(app):
    from app.services.site_metrics import collect_site_metrics

    sid = _mk_site(app, slug=_uniq('v327-metric'))
    column_id = _mk_column(app, sid)
    for viewed in (7, 8, 9):
        _mk_article(app, sid, column_id, viewed=viewed)

    from app.services.site_metrics import format_bytes, format_number

    with app.app_context():
        metrics = collect_site_metrics(sid, refresh=True)
        missing = collect_site_metrics(999999, refresh=True)
    assert metrics['article_count'] == 3
    assert metrics['view_count'] == 24
    assert metrics['counts']['article'] == 3
    assert isinstance(metrics['cache_entries'], int)
    assert missing['article_count'] == 0
    assert missing['disk_bytes'] == 0
    assert missing['cache_entries'] is None or isinstance(
        missing['cache_entries'], int)
    assert format_bytes(None) == '--'
    assert format_number(None) == '--'


def test_metrics_disk_bytes(app, tmp_path, monkeypatch):
    from app.services.site_metrics import collect_site_metrics

    sid = _mk_site(app, slug=_uniq('v327-disk'))
    monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))

    target = tmp_path / f'site{sid}' / 'images' / '2026'
    target.mkdir(parents=True)
    (target / 'a.jpg').write_bytes(b'x' * 100)
    (target / 'b.jpg').write_bytes(b'y' * 50)

    with app.app_context():
        metrics = collect_site_metrics(sid, refresh=True)
    assert metrics['disk_bytes'] == 150


def test_metrics_cache_failure_degrades_to_none(app, monkeypatch):
    from app.services import site_metrics

    class _BrokenBackend:
        def scan_iter(self, **kwargs):
            raise RuntimeError('redis down')

    monkeypatch.setattr(
        site_metrics, 'cache', SimpleNamespace(cache=_BrokenBackend()))
    assert site_metrics._cache_entry_count(1) is None


def test_metrics_scope_for_site_admin(client, app):
    sid_a = _mk_site(app, slug=_uniq('v327-scope-a'))
    sid_b = _mk_site(app, slug=_uniq('v327-scope-b'))
    uid = _mk_user(app, _uniq('v327-siteadmin'), [('site_admin', sid_a)])
    _login(client, uid)

    resp = client.get('/admin/sites/metrics')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'v327-scope-a' in body
    assert 'v327-scope-b' not in body


def test_metrics_forbidden_for_content_editor(client, app):
    uid = _mk_user(app, _uniq('v327-metric-editor'), [('content_editor', None)])
    _login(client, uid)
    resp = client.get('/admin/sites/metrics')
    assert resp.status_code == 403


def test_metrics_threshold_and_refresh(admin_client, app):
    from app.models.setting import Setting

    sid = _mk_site(app, slug=_uniq('v327-warn'))
    column_id = _mk_column(app, sid)
    for _ in range(11):
        _mk_article(app, sid, column_id)

    with app.app_context():
        Setting.set('site_metric_article_warn', '1')
        db.session.commit()

    _login(admin_client, _admin_id(app))
    resp = admin_client.get('/admin/sites/metrics')
    body = resp.get_data(as_text=True)
    assert 'table-warning' in body
    assert '>11<' in body

    _mk_article(app, sid, column_id)
    resp = admin_client.get('/admin/sites/metrics?refresh=1')
    body = resp.get_data(as_text=True)
    assert '>12<' in body

    with app.app_context():
        Setting.set('site_metric_article_warn', '0')
        db.session.commit()
    resp = admin_client.get('/admin/sites/metrics?refresh=1')
    assert 'table-warning' not in resp.get_data(as_text=True)


# ============================================================
# 三、每日快照
# ============================================================

def test_snapshot_is_idempotent(app):
    from app.models.site_metric import SiteMetricSnapshot
    from app.services.site_metrics import snapshot_daily

    sid = _mk_site(app, slug=_uniq('v327-snap'))
    target = date(2026, 11, 18)

    with app.app_context():
        assert snapshot_daily(target) >= 1
        first = SiteMetricSnapshot.query.filter_by(
            site_id=sid, date=target).count()
        assert first == 1
        snapshot_daily(target)
        second = SiteMetricSnapshot.query.filter_by(
            site_id=sid, date=target).count()
    assert second == 1


def test_snapshot_continues_after_single_site_failure(app, monkeypatch):
    from app.models.site_metric import SiteMetricSnapshot
    from app.services import site_metrics

    sid_a = _mk_site(app, slug=_uniq('v327-snap-a'))
    sid_b = _mk_site(app, slug=_uniq('v327-snap-b'))
    original = site_metrics.collect_site_metrics

    def _flaky(site_id, refresh=False):
        if site_id == sid_a:
            raise RuntimeError('boom')
        return original(site_id, refresh=refresh)

    monkeypatch.setattr(site_metrics, 'collect_site_metrics', _flaky)
    target = date(2026, 11, 19)

    with app.app_context():
        written = site_metrics.snapshot_daily(target)
        assert written >= 1
        assert SiteMetricSnapshot.query.filter_by(
            site_id=sid_b, date=target).count() == 1
        assert SiteMetricSnapshot.query.filter_by(
            site_id=sid_a, date=target).count() == 0


# ============================================================
# 四、插件站点作用域审计
# ============================================================

def test_plugin_audit_builtin_results():
    from app.utils.plugin_site_scope import audit_plugins

    report = audit_plugins()
    statuses = {p['slug']: p['status'] for p in report['plugins']}
    assert len(statuses) == 11
    assert statuses['product'] == 'adapted'
    assert statuses['recruit'] == 'adapted'
    assert statuses['analytics'] == 'no_tables'
    assert 'unadapted' not in statuses.values()


def test_plugin_audit_cli_exit_codes(tmp_path):
    plugin = tmp_path / 'badplug'
    plugin.mkdir()
    (plugin / 'manifest.json').write_text(
        json.dumps({'name': '坏插件', 'version': '1.0.0'}),
        encoding='utf-8')
    (plugin / 'models.py').write_text(
        'from flask_sqlalchemy import SQLAlchemy\n'
        'db = SQLAlchemy()\n'
        'class BadDoc(db.Model):\n'
        "    __tablename__ = 'bad_docs'\n"
        '    id = db.Column(db.Integer, primary_key=True)\n'
        '    slug = db.Column(db.String(50), unique=True)\n',
        encoding='utf-8')

    spec = importlib.util.spec_from_file_location(
        'v327_plugin_audit', 'scripts/audit_plugins_site_scope.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.run(['--plugins-dir', str(tmp_path)]) == 2
    assert module.run(
        ['--plugins-dir', str(tmp_path), '--strict']) == 1
    assert module.run(
        ['--plugins-dir', str(tmp_path), '--json']) == 2


# ============================================================
# 五、日志站点标签
# ============================================================

def test_logging_adds_site_tag(app):
    from app.logging_ext import SiteContextFilter, install_logging

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter('%(site_id)s'))

    logger = logging.getLogger('v327.logtest')
    logger.handlers = [handler]
    logger.filters = [SiteContextFilter()]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    with app.test_request_context('/'):
        from flask import g
        g.current_site_id = 7
        logger.info('with site')
    logger.info('without site')

    lines = stream.getvalue().splitlines()
    assert lines[0] == '7'
    assert lines[1] == '-'

    install_logging(app)
    install_logging(app)
    filters = [f for f in handler.filters if isinstance(f, SiteContextFilter)]
    assert len(filters) <= 1


# ============================================================
# 六、审计导出按站点过滤
# ============================================================

def test_audit_export_scoped_by_site(client, app):
    from app.models.audit import AuditLog

    sid_a = _mk_site(app, slug=_uniq('v327-audit-a'))
    sid_b = _mk_site(app, slug=_uniq('v327-audit-b'))
    with app.app_context():
        db.session.add(AuditLog(
            site_id=sid_a, username='u-a', op_type='create',
            module='article', target_name='站A记录'))
        db.session.add(AuditLog(
            site_id=sid_b, username='u-b', op_type='create',
            module='article', target_name='站B记录'))
        db.session.commit()

    uid = _mk_user(app, _uniq('v327-audit-user'), [('site_admin', sid_a)])
    _login(client, uid)

    resp = client.get(f'/admin/audit-logs/export?site_id={sid_b}')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '站B记录' not in body
    disposition = resp.headers.get('Content-Disposition', '')
    assert f'audit-site{sid_b}-' in disposition
