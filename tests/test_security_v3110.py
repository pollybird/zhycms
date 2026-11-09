"""v3.1.10 纵深防御与合规加固测试（GitCode issue #14 残留 Low/Info + SAST P3）。

覆盖：
  - VULN-023：模板审计下标内字符串拼接检测
  - VULN-025：加密 fail-open 高可见度告警（error 日志一次 + 后台红色横幅）
  - VULN-014：CORS 拒绝 * 通配符（新保存校验 + 存量 UI 告警）
  - VULN-015：后台管理员密码策略（12 位四类字符，存量不受影响）
  - VULN-017：CI Actions 全部 pin 完整 SHA
  - VULN-018：非 testing 环境使用 TestingConfig 固定密钥拒绝启动
"""
import os
import re
from pathlib import Path

import pytest

from app.extensions import db
from app.models.setting import Setting


security = pytest.mark.security

ROOT = Path(__file__).resolve().parent.parent


# ============================================================
# VULN-023：模板审计下标拼接
# ============================================================

@security
class TestVuln023GetitemConcat:

    def test_concat_payloads_rejected(self):
        from app.utils.template_safety import audit_template
        for bad in ("{{ ''['_'+'_class'+'__'] }}",
                    "{{ x['__gl'~'obals__'] }}",
                    "{% set a = x['__cl'~'ass__'] %}"):
            ok, reason = audit_template(bad)
            assert not ok, f'下标拼接未被拦截: {bad!r}'
            assert '下标内字符串拼接' in reason

    def test_normal_getitem_allowed(self):
        from app.utils.template_safety import audit_template
        for good in ("{{ data['title'] }}",
                     "{{ request.args['page'] }}",
                     "{{ items[0] }}",
                     "{{ article['title'] | e }}"):
            ok, reason = audit_template(good)
            assert ok, f'正常下标被误伤: {good!r} -> {reason}'

    def test_official_themes_zero_hits(self):
        from app.utils.template_safety import audit_theme_templates
        themes_root = os.path.join(
            ROOT, 'app', 'frontend', 'templates', 'themes')
        ok, violations = audit_theme_templates(themes_root)
        hits = [v for v in violations if '下标内字符串拼接' in v[1]]
        assert not hits, f'官方主题命中下标拼接规则: {hits}'


# ============================================================
# VULN-025：加密 fail-open 高可见度告警
# ============================================================

@security
class TestVuln025EncUnavailable:

    def test_error_logged_once_when_key_missing(self, monkeypatch):
        from app.utils import crypto
        # 模拟密钥不可用：_resolve_key 返回空 → _get_fernet 返回 None
        monkeypatch.setattr(crypto, '_resolve_key', lambda: '')
        monkeypatch.setattr(crypto, '_warned_unavailable', False)
        # 直接捕获 logger.error（与 handler/传播链状态无关，见 VULN-013 同款写法）
        errors = []
        monkeypatch.setattr(crypto.logger, 'error',
                            lambda *a, **k: errors.append((a, k)))
        assert crypto.encrypt_value('secret') == 'secret'  # fail-open
        crypto.decrypt_value('gAAAAAxxxx')  # 第二次调用不再重复告警
        hits = [e for e in errors if 'ZHYCMS_ENC_KEY' in str(e[0])]
        assert len(hits) == 1, 'error 告警应每进程仅记录一次'

    def test_banner_shown_when_flag_set(self, admin_client):
        app = admin_client.application
        old = app.config.get('ZHYCMS_ENC_UNAVAILABLE')
        app.config['ZHYCMS_ENC_UNAVAILABLE'] = True
        try:
            resp = admin_client.get('/admin/settings/api')
            assert resp.status_code == 200
            assert '敏感配置加密未启用' in resp.get_data(as_text=True)
        finally:
            app.config['ZHYCMS_ENC_UNAVAILABLE'] = bool(old)

    def test_no_banner_when_encryption_available(self, admin_client):
        # 测试环境 ZHYCMS_ENC_KEY 固定可用，不应出现横幅
        app = admin_client.application
        assert not app.config.get('ZHYCMS_ENC_UNAVAILABLE')
        resp = admin_client.get('/admin/settings/api')
        assert resp.status_code == 200
        assert '敏感配置加密未启用' not in resp.get_data(as_text=True)


# ============================================================
# VULN-014：CORS 拒绝 * 通配符
# ============================================================

_API_KEYS = ('api_enable', 'api_token', 'api_cache_ttl', 'api_cors_origins',
             'api_auth_mode', 'jwt_secret_key', 'jwt_access_expires_minutes',
             'jwt_refresh_expires_days', 'api_rate_limit_enable',
             'api_rate_limit_login', 'api_rate_limit_read')


@security
class TestVuln014CorsWildcard:

    @staticmethod
    def _snapshot(app):
        with app.app_context():
            return {k: Setting.get(k) for k in _API_KEYS}

    @staticmethod
    def _restore(app, old):
        with app.app_context():
            for k, v in old.items():
                Setting.set(k, v or '')
            db.session.commit()

    def test_save_rejects_wildcard(self, admin_client):
        old = self._snapshot(admin_client.application)
        try:
            resp = admin_client.post('/admin/settings/api',
                                     data={'api_cors_origins': '*'})
            assert resp.status_code == 302
            with admin_client.application.app_context():
                assert Setting.get('api_cors_origins') != '*'
        finally:
            self._restore(admin_client.application, old)

    def test_save_rejects_malformed_origin(self, admin_client):
        old = self._snapshot(admin_client.application)
        try:
            resp = admin_client.post(
                '/admin/settings/api',
                data={'api_cors_origins': 'javascript:alert(1)'})
            assert resp.status_code == 302
            with admin_client.application.app_context():
                assert Setting.get('api_cors_origins') != 'javascript:alert(1)'
        finally:
            self._restore(admin_client.application, old)

    def test_save_accepts_explicit_origins(self, admin_client):
        old = self._snapshot(admin_client.application)
        try:
            resp = admin_client.post(
                '/admin/settings/api',
                data={'api_cors_origins': 'https://a.example.com,http://b.com:8080'})
            assert resp.status_code == 302
            with admin_client.application.app_context():
                assert Setting.get('api_cors_origins') == \
                    'https://a.example.com,http://b.com:8080'
        finally:
            self._restore(admin_client.application, old)

    def test_existing_wildcard_shows_warning_not_cleared(self, admin_client):
        old = self._snapshot(admin_client.application)
        try:
            with admin_client.application.app_context():
                Setting.set('api_cors_origins', '*')
                db.session.commit()
            resp = admin_client.get('/admin/settings/api')
            assert resp.status_code == 200
            text = resp.get_data(as_text=True)
            assert '通配符' in text and '跨域滥用风险' in text
            # 存量配置不清空（运行时行为不变）
            with admin_client.application.app_context():
                assert Setting.get('api_cors_origins') == '*'
        finally:
            self._restore(admin_client.application, old)


# ============================================================
# VULN-015：后台管理员密码策略
# ============================================================

@security
class TestVuln015PasswordPolicy:

    def test_policy_boundaries(self):
        from app.utils.password_policy import validate_password
        assert not validate_password('Abcdef12345')[0]    # 11 位
        assert not validate_password('Abcdef123456')[0]   # 12 位但无特殊字符
        assert not validate_password('abcdef12345!')[0]   # 缺大写
        assert not validate_password('123456')[0]         # 会员端旧策略长度也不够
        assert validate_password('Abcdef12345!')[0]       # 12 位四类字符
        assert validate_password('Xy9!abcDEF1234')[0]

    def test_reset_password_rejects_weak(self, admin_client):
        from app.models.user import User
        with admin_client.application.app_context():
            admin = User.query.filter_by(username='admin').first()
            uid = admin.id
            old_hash = admin.password_hash
        resp = admin_client.post(f'/admin/users/{uid}/reset-password',
                                 data={'password': '123456'})
        assert resp.status_code == 302
        with admin_client.application.app_context():
            admin = User.query.filter_by(username='admin').first()
            assert admin.password_hash == old_hash, '弱密码不应被接受'

    def test_legacy_password_still_can_login(self, client):
        # 存量弱密码（admin123）不受影响：不强制改密、可正常登录
        with client.session_transaction() as sess:
            sess['captcha'] = 'abcd'
        resp = client.post('/admin/login', data={
            'username': 'admin', 'password': 'admin123', 'captcha': 'abcd',
        })
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert sess.get('_user_id'), '存量密码登录失败'


# ============================================================
# VULN-017：CI Actions pin 完整 SHA
# ============================================================

@security
class TestVuln017CIPinSHA:

    def test_no_floating_version_tags(self):
        wf_dir = ROOT / '.github' / 'workflows'
        uses_re = re.compile(r'uses:\s*([\w./-]+)@([^\s#]+)')
        offenders = []
        for yml in sorted(wf_dir.glob('*.yml')):
            for lineno, line in enumerate(
                    yml.read_text(encoding='utf-8').splitlines(), 1):
                m = uses_re.search(line)
                if not m:
                    continue
                action, ref = m.groups()
                if not re.fullmatch(r'[0-9a-f]{40}', ref):
                    offenders.append(f'{yml.name}:{lineno} {action}@{ref}')
        assert not offenders, 'CI 存在浮动版本标签: ' + '; '.join(offenders)


# ============================================================
# VULN-018：TestingConfig 密钥防护
# ============================================================

@security
class TestVuln018TestingKeyGuard:

    def test_testing_key_rejected_outside_testing(self):
        # 测试进程内 ZHYCMS_SECRET_KEY 即 TestingConfig 固定值，
        # 非 testing 配置应立即 SystemExit
        import app as app_module
        from app.config import Config, TestingConfig
        assert Config.SECRET_KEY == TestingConfig.SECRET_KEY  # 前置条件
        with pytest.raises(SystemExit):
            app_module.create_app('default')

    def test_testing_config_itself_allowed(self, app):
        # testing 配置（当前测试应用）不受限制
        assert app.config.get('ENV') == 'testing'
