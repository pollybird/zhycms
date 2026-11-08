"""v3.1.9 安全加固测试（GitCode issue #14 + SAST 续项）。

覆盖：
  - VULN-022：插件 AST 审计的 import 别名 / 赋值传播 / 危险 getattr
  - VULN-007：JWT 登出后 jti 黑名单即时失效；Redis 故障降级不 500
  - VULN-008：登录前清空会话（会话固定）
  - VULN-010：SQL LIKE 通配符转义
  - VULN-011：Meilisearch 服务地址校验（允许内网）
  - VULN-012：生产环境 DEBUG 阻断
  - VULN-013：数据库连接错误信息脱敏
  - VULN-020：验证码使用 secrets
  - VULN-021：fragment 删除/启停审计日志
"""
import pytest

from app.extensions import db
from app.models.setting import Setting


security = pytest.mark.security


# ============================================================
# VULN-022：插件 AST 审计（别名 / 传播 / getattr）
# ============================================================

@security
class TestVuln022PluginAliasBypass:

    def test_alias_and_assignment_payloads_rejected(self):
        from app.utils.plugin_safety import audit_python_source
        payloads = (
            'import os as x\nx.system("id")',
            'from os import system as s\ns("id")',
            'import os\nx = os\nx.system("id")',
            'import os\nx = os.system\nx("id")',
            'import os\nx = os.system\ny = x\ny("id")',
            'import os\ngetattr(os, "system")("id")',
            'import os\nx = os\ngetattr(x, "system")("id")',
            'f = eval\nf("1")',
        )
        for bad in payloads:
            ok, reason = audit_python_source(bad)
            assert not ok, f'间接引用绕过未被拦截: {bad!r}'

    def test_legit_aliases_not_rejected(self):
        from app.utils.plugin_safety import audit_python_source
        for good in ('import os.path as p\np.join("a", "b")',
                     'from os import path as os_path\nos_path.join("a")',
                     'from os import path\npath.exists("a")',
                     'import json as j\nj.dumps({})'):
            ok, reason = audit_python_source(good)
            assert ok, f'合法别名被误伤: {good!r} -> {reason}'


# ============================================================
# VULN-007：JWT 服务端吊销
# ============================================================

class _FakeRedis:
    def __init__(self):
        self.store = {}

    def setex(self, key, ttl, value):
        self.store[key] = value

    def exists(self, key):
        return 1 if key in self.store else 0


class _BrokenRedis:
    def setex(self, *args, **kwargs):
        raise RuntimeError('redis down')

    def exists(self, *args, **kwargs):
        raise RuntimeError('redis down')


def _api_login(client):
    resp = client.post('/api/v1/auth/login',
                       json={'username': 'admin', 'password': 'admin123'})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()['data']['access_token']


@security
class TestVuln007JWTRevocation:

    def test_logout_revokes_token_via_redis(self, app, client):
        old = app.config.get('JWT_BLOCKLIST_REDIS')
        app.config['JWT_BLOCKLIST_REDIS'] = _FakeRedis()
        try:
            token = _api_login(client)
            headers = {'Authorization': f'Bearer {token}'}
            assert client.get('/api/v1/site', headers=headers).status_code == 200
            assert client.post('/api/v1/auth/logout',
                               headers=headers).status_code == 200
            assert client.get('/api/v1/site', headers=headers).status_code == 401
        finally:
            app.config['JWT_BLOCKLIST_REDIS'] = old

    def test_redis_failure_degrades_without_500(self, app, client):
        old = app.config.get('JWT_BLOCKLIST_REDIS')
        app.config['JWT_BLOCKLIST_REDIS'] = _BrokenRedis()
        try:
            token = _api_login(client)
            headers = {'Authorization': f'Bearer {token}'}
            # Redis 故障：登出不报错，token 仍可用（降级为短期 token 语义）
            assert client.post('/api/v1/auth/logout',
                               headers=headers).status_code == 200
            assert client.get('/api/v1/site', headers=headers).status_code == 200
        finally:
            app.config['JWT_BLOCKLIST_REDIS'] = old

    def test_logout_without_token_still_ok(self, client):
        assert client.post('/api/v1/auth/logout').status_code == 200


# ============================================================
# VULN-008：会话固定
# ============================================================

@security
class TestVuln008SessionFixation:

    def test_admin_login_clears_pre_login_session(self, client):
        with client.session_transaction() as sess:
            sess['captcha'] = 'abcd'
            sess['attacker_preset'] = 'pwned'
        resp = client.post('/admin/login', data={
            'username': 'admin',
            'password': 'admin123',
            'captcha': 'abcd',
        })
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert 'attacker_preset' not in sess, '登录前预置 session 未被清除'
            assert sess.get('_user_id'), '登录态未建立'
        # 登录后访问登录页应跳转（已认证）
        assert client.get('/admin/login').status_code == 302

    def test_member_login_clears_pre_login_session(self, app):
        from plugins.member.security import login_member

        class _Member:
            id = 12345

        with app.test_request_context('/'):
            from flask import session
            session['attacker_preset'] = 'pwned'
            login_member(_Member())
            assert session.get('member_id') == 12345
            assert 'attacker_preset' not in session


# ============================================================
# VULN-010：LIKE 转义
# ============================================================

@security
class TestVuln010LikeEscape:

    def test_escape_like(self):
        from app.utils.db_utils import escape_like
        assert escape_like(None) == ''
        assert escape_like('a%b') == 'a\\%b'
        assert escape_like('a_b') == 'a\\_b'
        assert escape_like('a\\b') == 'a\\\\b'

    def test_wildcards_do_not_expand_result_set(self, app):
        from app.models.article import Article
        from app.models.workflow import STATUS_PUBLISHED
        from app.utils.db_utils import escape_like, LIKE_ESCAPE
        with app.app_context():
            a1 = Article(column_id=1, title='100% coverage',
                         status=STATUS_PUBLISHED)
            a2 = Article(column_id=1, title='plain text',
                         status=STATUS_PUBLISHED)
            try:
                db.session.add_all([a1, a2])
                db.session.flush()
                rows = Article.query.filter(Article.title.like(
                    f'%{escape_like("%")}%', escape=LIKE_ESCAPE)).all()
                assert [r.title for r in rows] == ['100% coverage']
                rows = Article.query.filter(Article.title.like(
                    f'%{escape_like("plain")}%', escape=LIKE_ESCAPE)).all()
                assert [r.title for r in rows] == ['plain text']
            finally:
                db.session.rollback()


# ============================================================
# VULN-011：Meilisearch 地址校验
# ============================================================

@security
class TestVuln011MeiliUrl:

    def test_assert_http_url_allows_internal(self):
        from app.utils.url_safety import assert_http_url
        for good in ('http://127.0.0.1:7700', 'http://meili:7700',
                     'https://search.example.com'):
            assert assert_http_url(good) == good

    def test_assert_http_url_rejects_malformed(self):
        from app.utils.url_safety import assert_http_url
        for bad in ('file:///etc/passwd', 'gopher://evil.com:70/',
                    'http://user:pw@host:7700', 'http://', ''):
            with pytest.raises(ValueError):
                assert_http_url(bad)

    def test_setting_save_rejects_invalid_url(self, admin_client):
        keys = ('search_engine', 'search_meili_url', 'search_meili_key',
                'search_index_on_save', 'search_highlight',
                'search_results_per_page')
        with admin_client.application.app_context():
            old = {k: Setting.get(k) for k in keys}
        try:
            resp = admin_client.post('/admin/settings/search', data={
                'search_engine': old['search_engine'] or 'tantivy',
                'search_meili_url': 'gopher://evil.com:70/',
            })
            assert resp.status_code == 302
            with admin_client.application.app_context():
                assert Setting.get('search_meili_url') != 'gopher://evil.com:70/'

            resp = admin_client.post('/admin/settings/search', data={
                'search_engine': old['search_engine'] or 'tantivy',
                'search_meili_url': 'http://127.0.0.1:7700',
            })
            assert resp.status_code == 302
            with admin_client.application.app_context():
                assert Setting.get('search_meili_url') == 'http://127.0.0.1:7700'
        finally:
            with admin_client.application.app_context():
                for key, value in old.items():
                    Setting.set(key, value or '')
                db.session.commit()


# ============================================================
# VULN-012：生产环境 DEBUG 阻断
# ============================================================

@security
class TestVuln012ProductionDebug:

    def test_production_with_debug_raises(self, monkeypatch):
        import app as app_module
        from app.config import config as config_map

        monkeypatch.setattr(config_map['production'], 'DEBUG', True)
        with pytest.raises(SystemExit):
            app_module.create_app('production')

    def test_testing_config_allows_debug(self, app):
        # 现有测试应用即 testing 配置，DEBUG=True 不应被阻断
        assert app.config.get('DEBUG') is True


# ============================================================
# VULN-013：错误信息脱敏
# ============================================================

@security
class TestVuln013ErrorMasking:

    def test_operational_error_hides_connection_details(self, monkeypatch):
        import sqlalchemy
        from sqlalchemy.exc import OperationalError
        from app.utils import dbconfig

        def _boom(*args, **kwargs):
            raise OperationalError(
                'SELECT 1', {},
                Exception('host=10.9.8.7 port=5432 driver=psycopg2'))

        logged = []

        def _capture_warning(*args, **kwargs):
            logged.append((args, kwargs))

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        monkeypatch.setattr(dbconfig.logger, 'warning', _capture_warning)
        ok, msg = dbconfig.test_connection('postgresql://u:p@10.9.8.7:5432/db')
        assert not ok
        for leak in ('10.9.8.7', '5432', 'psycopg2'):
            assert leak not in msg, f'错误信息泄露连接细节: {leak}'
        # 详情仍写入日志（含堆栈）供排障
        assert logged, '失败详情未写日志'
        assert '10.9.8.7' in str(logged[0][0])
        assert logged[0][1].get('exc_info') is True


# ============================================================
# VULN-020：验证码随机源
# ============================================================

@security
class TestVuln020Captcha:

    def test_captcha_uses_secrets_not_random(self, monkeypatch):
        import app.utils.captcha as captcha

        used = []
        real_choice = captcha.secrets.choice

        def _spy(seq):
            used.append(1)
            return real_choice(seq)

        monkeypatch.setattr(captcha.secrets, 'choice', _spy)

        def _forbidden(*args, **kwargs):
            raise AssertionError('验证码仍在使用 random.choices')

        monkeypatch.setattr(captcha.random, 'choices', _forbidden)
        text, png = captcha.generate_captcha(4)
        assert len(text) == 4
        assert len(used) == 4
        assert png.startswith(b'\x89PNG\r\n\x1a\n')


# ============================================================
# VULN-021：fragment 审计日志
# ============================================================

@security
class TestVuln021FragmentAudit:

    def test_delete_and_toggle_write_audit_log(self, admin_client):
        from app.models.fragment import Fragment
        from app.models.audit import (
            AuditLog, MODULE_FRAGMENT, OP_DELETE, OP_UPDATE,
        )
        with admin_client.application.app_context():
            frag = Fragment(name='v319审计碎片', slug='v319-audit-frag',
                            field_type='text', is_enabled=True)
            db.session.add(frag)
            db.session.commit()
            fid = frag.id
        try:
            assert admin_client.post(
                f'/admin/fragments/{fid}/toggle').status_code == 302
            assert admin_client.post(
                f'/admin/fragments/{fid}/delete').status_code == 302
            with admin_client.application.app_context():
                logs = AuditLog.query.filter_by(
                    module=MODULE_FRAGMENT, target_id=str(fid)).all()
                ops = {log.op_type for log in logs}
                assert OP_UPDATE in ops, '启停未写审计日志'
                assert OP_DELETE in ops, '删除未写审计日志'
        finally:
            with admin_client.application.app_context():
                AuditLog.query.filter_by(
                    module=MODULE_FRAGMENT, target_id=str(fid)).delete()
                Fragment.query.filter_by(id=fid).delete()
                db.session.commit()
