"""v3.1.8 安全加固测试（GitCode issue #12，P0 + P1 + F-001）。

覆盖：
  - VULN-001：主题 SSTI —— 构建器沙箱渲染阻断内省链 + 模板静态审计
  - VULN-002：插件 RCE —— 源码静态审计 + 直传开关默认关闭
  - VULN-003：敏感凭证 Fernet 加密入库 + 明文惰性迁移
  - VULN-004：企业微信 Webhook SSRF 子串绕过拒绝
  - VULN-005：短信 Webhook SSRF（最终 URL 校验 + 保存校验）
  - VULN-006：JWT 密钥与 SECRET_KEY 隔离，未配置自动生成
  - F-001：CSP 第三方源白名单（基线一致 / 追加 / 非法拒绝 / SVG 不受影响）
"""
import io
import zipfile

import pytest

from app.extensions import db
from app.models.setting import Setting


security = pytest.mark.security

# v3.1.7 基线 CSP（空白名单时必须逐字节一致）
_CSP_BASELINE = (
    "default-src 'self'; script-src 'self' 'unsafe-inline';"
    " style-src 'self' 'unsafe-inline';"
    " img-src 'self' data: https:; font-src 'self' data:; frame-ancestors 'self'"
)


# ============================================================
# VULN-001：主题 SSTI
# ============================================================

@security
class TestVuln001ThemeSSTI:

    def test_sandbox_blocks_introspection_chain(self, app):
        """沙箱环境下 SSTI 内省链渲染抛 SecurityError。"""
        from jinja2.sandbox import SecurityError
        from app.builder.renderer import _get_sandbox_env
        with app.app_context():
            env = _get_sandbox_env()
            with pytest.raises(SecurityError):
                env.from_string(
                    "{{ ''.__class__.__mro__[1].__subclasses__() }}").render()

    def test_sandbox_blocks_dunder_attribute(self, app):
        """沙箱环境下双下划线属性链访问（SECRET_KEY 泄露路径）被拒。

        jinja2 3.1 沙箱对单层不安全属性返回 Undefined（渲染为空），
        链上继续访问/调用时抛 SecurityError——两种形态均断言无法取到值。
        """
        from jinja2.sandbox import SecurityError
        from app.builder.renderer import _get_sandbox_env
        with app.app_context():
            env = _get_sandbox_env()
            with pytest.raises(SecurityError):
                env.from_string("{{ ().__class__.__mro__ }}").render()
            with pytest.raises(SecurityError):
                env.from_string("{{ ().__class__.__base__.__subclasses__() }}").render()
            # 单层访问取不到值（渲染为空，无任何内省信息泄露）
            assert env.from_string("{{ ().__class__ }}").render() == ''

    def test_audit_template_rejects_dangerous_identifiers(self):
        """模板审计：config[ / __class__ / getattr / os. / import 均被拦截。"""
        from app.utils.template_safety import audit_template
        for bad in ("{{ config['SECRET_KEY'] }}", "{{ x.__class__ }}",
                    '{{ getattr(x, "y") }}', '{{ os.popen("id") }}',
                    '{% import os %}', '{{ eval("1") }}', '{{ subprocess.call }}'):
            ok, reason = audit_template(bad)
            assert not ok, f'危险模板未被拦截: {bad}'

    def test_audit_template_bypass_variants(self):
        """模板审计二次加固：attr 拼接 / config / request 逃逸 / 环境内部对象。"""
        from app.utils.template_safety import audit_template
        for bad in ("{{ (''|attr('__cl'~'ass__')) }}",  # attr 过滤器 + 字符串拼接
                    '{{ config }}', '{{ config.SECRET_KEY }}',
                    '{{ config["SECRET_KEY"] }}',
                    '{{ request.application.config }}',  # request 白名单外属性
                    '{{ request.environ }}',
                    '{{ request["application"] }}',  # 下标回退 getattr
                    '{{ cycler.__init__ }}', '{{ namespace(x=1) }}',
                    '{{ joiner }}', '{{ lipsum }}'):
            ok, reason = audit_template(bad)
            assert not ok, f'绕过变体未被拦截: {bad}'

    def test_audit_template_allows_request_whitelist(self):
        """模板审计：request 白名单属性与纯文本不误伤。"""
        from app.utils.template_safety import audit_template
        for good in ('{{ request.path }}?lang={{ loc.code }}',
                     '{{ request.args.get("page", 1) }}',
                     '{{ request.endpoint }}', '{{ request.host_url }}',
                     '{{ request.view_args }}',
                     '<p>site config 文档</p>'):  # 纯文本 config 不误伤
            ok, reason = audit_template(good)
            assert ok, f'合法模板被误伤: {good} -> {reason}'

    def test_audit_theme_templates_rejects_package(self, tmp_path):
        """主题包含危险模板时整包审计失败并给出路径。"""
        from app.utils.template_safety import audit_theme_templates
        (tmp_path / 'index.html').write_text('<html>ok</html>', encoding='utf-8')
        (tmp_path / 'evil.html').write_text("{{ config['SECRET_KEY'] }}", encoding='utf-8')
        ok, violations = audit_theme_templates(str(tmp_path))
        assert not ok
        assert any('evil.html' in v[0] for v in violations)

    def test_runtime_sandbox_no_config_leak(self, app):
        """运行时：全站沙箱 globals 不含 config/request/session/g，
        config.SECRET_KEY 渲染为 undefined 而非密钥。"""
        with app.app_context():
            env = app.jinja_env
            assert env.sandboxed, '全站模板环境未沙箱化'
            for key in ('config', 'request', 'session', 'g'):
                assert key not in env.globals, f'globals 残留 {key}'
            assert 'url_for' in env.globals  # 合法 global 保留
            from jinja2 import UndefinedError
            with pytest.raises(UndefinedError):
                env.from_string('{{ config.SECRET_KEY }}').render()
            with pytest.raises(UndefinedError):
                env.from_string('{{ config["SECRET_KEY"] }}').render()
            # attr 拼接：求值后的 __class__ 被沙箱 is_safe_attribute 拦截，渲染为空
            assert env.from_string(
                "{{ (''|attr('__cl'~'ass__')) }}").render() == ''

    def test_runtime_request_proxy(self):
        """运行时：request 安全代理放行白名单、拦截逃逸属性与下标。"""
        from app import _TemplateRequestProxy

        class _FakeReq:
            path = '/x'
            application = 'APP_OBJ'

        proxy = _TemplateRequestProxy(_FakeReq())
        assert proxy.path == '/x'
        with pytest.raises(AttributeError):
            proxy.application  # noqa: B018（断言语义即属性访问）
        with pytest.raises(TypeError):
            proxy['path']


# ============================================================
# VULN-002：插件 RCE
# ============================================================

@security
class TestVuln002PluginRCE:

    def test_audit_python_source_rejects_dangerous_calls(self):
        """插件源码审计：os.system / subprocess / eval / __import__ 均被拦截。"""
        from app.utils.plugin_safety import audit_python_source
        for bad in ('os.system("id")', 'subprocess.Popen("id")',
                    'subprocess.run(["id"])', 'eval("1")', 'exec("1")',
                    '__import__("os")'):
            ok, reason = audit_python_source(bad)
            assert not ok, f'危险源码未被拦截: {bad}'

    def test_audit_python_source_allows_normal_code(self):
        from app.utils.plugin_safety import audit_python_source
        ok, _ = audit_python_source('def setup(app):\n    return True\n')
        assert ok

    def test_audit_python_source_bypass_variants(self):
        """插件审计二次加固（AST）：from-import / importlib / sys.modules /
        动态 getattr / operator / builtins 变体全部拦截。"""
        from app.utils.plugin_safety import audit_python_source
        for bad in ('from os import system\nsystem("id")',
                    'from os import popen',
                    'import importlib\nimportlib.import_module("os").system("id")',
                    'import sys\nsys.modules["os"].system("id")',
                    'import builtins\nbuiltins.eval("1")',
                    'import operator\noperator.attrgetter("__class__")(1)',
                    'x = ().__class__.__mro__',
                    'getattr(x, "__globals__")',
                    'getattr(x, "__gl" + "obals__")',  # 动态属性名
                    'compile("1", "<s>", "eval")',
                    'x = globals()'):
            ok, reason = audit_python_source(bad)
            assert not ok, f'绕过变体未被拦截: {bad}'

    def test_audit_python_source_allows_legit_patterns(self):
        """插件审计：os.path / 私有属性 / 常量 getattr / dunder 常量不误伤。"""
        from app.utils.plugin_safety import audit_python_source
        for good in ('import os\np = os.path.join("a", "b")\nos.makedirs(p, exist_ok=True)',
                     'def __init__(self):\n    self.__cache = {}',
                     'x = getattr(obj, "name", None)',
                     '__all__ = ["a"]\n__version__ = "1.0"'):
            ok, reason = audit_python_source(good)
            assert ok, f'合法代码被误伤: {good} -> {reason}'

    def test_plugin_upload_rejected_when_disabled(self, admin_client):
        """默认（plugin_upload_enabled 关闭）直传插件包被拒。"""
        with admin_client.application.app_context():
            Setting.set('plugin_upload_enabled', '')
            db.session.commit()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('manifest.json', '{}')
            z.writestr('__init__.py', '')
        buf.seek(0)
        resp = admin_client.post(
            '/admin/plugins/upload',
            data={'archive': (buf, 'evil.zip')},
            content_type='multipart/form-data')
        assert resp.status_code == 302  # 拒绝并跳回插件页
        with admin_client.application.app_context():
            assert Setting.get('plugin_upload_enabled') != 'on'

    def test_plugin_upload_toggle(self, admin_client):
        """直传开关可开启/关闭并持久化。"""
        try:
            resp = admin_client.post('/admin/plugins/upload-toggle',
                                     data={'plugin_upload_enabled': 'on'})
            assert resp.status_code == 302
            with admin_client.application.app_context():
                assert Setting.get('plugin_upload_enabled') == 'on'
            resp = admin_client.post('/admin/plugins/upload-toggle', data={})
            assert resp.status_code == 302
            with admin_client.application.app_context():
                assert Setting.get('plugin_upload_enabled') == ''
        finally:
            with admin_client.application.app_context():
                Setting.set('plugin_upload_enabled', '')
                db.session.commit()


# ============================================================
# VULN-003：敏感凭证加密
# ============================================================

@security
class TestVuln003CredentialEncryption:

    def test_sensitive_key_stored_encrypted(self, app):
        """敏感键 set 后入库为 gAAAAA 密文，get 返回明文。"""
        with app.app_context():
            try:
                Setting.set('api_token', 'v318-plain-secret')
                db.session.commit()
                item = Setting.query.filter_by(key='api_token').first()
                assert item.value.startswith('gAAAAA'), '敏感值未加密入库'
                assert 'v318-plain-secret' not in item.value
                assert Setting.get('api_token') == 'v318-plain-secret'
            finally:
                Setting.set('api_token', 'test-api-token')
                db.session.commit()

    def test_suffix_matched_sensitive_keys(self, app):
        """后缀匹配的敏感键（oss_*_secret / *_password）同样加密。"""
        with app.app_context():
            Setting.set('oss_aliyun_access_key_secret', 'oss-plain')
            Setting.set('notify_email_smtp_password', 'smtp-plain')
            db.session.commit()
            for key, plain in (('oss_aliyun_access_key_secret', 'oss-plain'),
                               ('notify_email_smtp_password', 'smtp-plain')):
                item = Setting.query.filter_by(key=key).first()
                assert item.value.startswith('gAAAAA'), f'{key} 未加密入库'
                assert Setting.get(key) == plain
                # 清理
                Setting.set(key, '')
            db.session.commit()

    def test_legacy_plaintext_lazy_migration(self, app):
        """历史明文敏感值首次读取时自动加密回写（惰性迁移）。"""
        with app.app_context():
            item = Setting.query.filter_by(key='search_meili_key').first()
            if item is None:
                item = Setting(key='search_meili_key', value='legacy-plain')
                db.session.add(item)
            else:
                item.value = 'legacy-plain'
            db.session.commit()
            # 首次读取返回明文
            assert Setting.get('search_meili_key') == 'legacy-plain'
            db.session.expire_all()
            item = Setting.query.filter_by(key='search_meili_key').first()
            assert item.value.startswith('gAAAAA'), '明文未惰性迁移为密文'
            assert Setting.get('search_meili_key') == 'legacy-plain'
            # 清理
            Setting.set('search_meili_key', '')
            db.session.commit()

    def test_normal_key_not_encrypted(self, app):
        """非敏感键保持明文存储。"""
        with app.app_context():
            Setting.set('site_name', 'v318-test-site')
            db.session.commit()
            item = Setting.query.filter_by(key='site_name').first()
            assert item.value == 'v318-test-site'
            assert Setting.get_dict()['site_name'] == 'v318-test-site'


# ============================================================
# VULN-004 / VULN-005：SSRF 防护
# ============================================================

@security
class TestVuln004005SSRF:

    def test_wework_webhook_substring_bypass_rejected(self, app):
        """企业微信 Webhook：子串绕过（evil.com 含目标域名字符串）被拒。"""
        from app.utils.notify_utils import send_wechat_webhook
        with app.app_context():
            for bad in ('https://qyapi.weixin.qq.com.evil.com/send?key=x',
                        'https://evil.com/?qyapi.weixin.qq.com',
                        'http://qyapi.weixin.qq.com/send?key=x',  # 非 https
                        'https://evil.com@qyapi.weixin.qq.com/', ):
                Setting.set('notify_wework_webhook', bad)
                db.session.commit()
                assert send_wechat_webhook('test') is False, f'子串绕过未拦截: {bad}'
            Setting.set('notify_wework_webhook', '')
            db.session.commit()

    def test_url_safety_rejects_internal_ips(self):
        """内网/回环/链路本地 IP 字面量一律拒绝。"""
        from app.utils.url_safety import assert_safe_external_url
        for bad in ('http://127.0.0.1/hook', 'http://192.168.1.1/hook',
                    'http://10.0.0.1/hook', 'http://172.16.0.1/hook',
                    'http://169.254.169.254/latest/meta-data',
                    'http://[::1]/hook', 'ftp://example.com/x'):
            with pytest.raises(ValueError):
                assert_safe_external_url(bad)

    def test_url_safety_rejects_exotic_ip_literals(self):
        """非常规 IP 字面量绕过：十进制/十六进制/八进制/短格式/IPv4-mapped。"""
        from app.utils.url_safety import assert_safe_external_url
        for bad in ('http://2130706433/',       # 十进制 127.0.0.1
                    'http://0x7f000001/',       # 十六进制 127.0.0.1
                    'http://0177.0.0.1/',       # 八进制 127.0.0.1
                    'http://127.1/',            # 段数省略 127.0.0.1
                    'http://[::ffff:127.0.0.1]/',  # IPv4-mapped IPv6
                    'http://0.0.0.0/',          # 未指定地址
                    'http://2852039166/',       # 十进制 169.254.169.254
                    ):
            with pytest.raises(ValueError):
                assert_safe_external_url(bad)

    def test_url_safety_dns_rebinding_rejected(self, monkeypatch):
        """DNS 重绑定：域名解析到内网地址即拒绝（fail closed）。"""
        import socket
        from app.utils.url_safety import assert_safe_external_url

        def _fake_getaddrinfo(host, *a, **kw):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 0))]

        monkeypatch.setattr(socket, 'getaddrinfo', _fake_getaddrinfo)
        with pytest.raises(ValueError, match='内网'):
            assert_safe_external_url('https://rebinding.example.com/hook')
        # 域名解析失败同样拒绝
        def _fail_getaddrinfo(host, *a, **kw):
            raise socket.gaierror('mock DNS failure')

        monkeypatch.setattr(socket, 'getaddrinfo', _fail_getaddrinfo)
        with pytest.raises(ValueError, match='解析失败'):
            assert_safe_external_url('https://unresolvable.invalid/hook')

    def test_url_safety_allows_public_https(self, monkeypatch):
        import socket
        from app.utils.url_safety import assert_safe_external_url

        def _fake_getaddrinfo(host, *a, **kw):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 0))]

        monkeypatch.setattr(socket, 'getaddrinfo', _fake_getaddrinfo)
        assert assert_safe_external_url('https://example.com/hook')
        assert assert_safe_external_url('https://8.8.8.8/hook')
        # 域名白名单精确命中：跳过 DNS 解析（可信域名）
        assert assert_safe_external_url('https://qyapi.weixin.qq.com/x',
                                        allowed_hosts={'qyapi.weixin.qq.com'})

    def test_sms_webhook_save_validation(self, app, monkeypatch):
        """会员短信设置保存：内网 URL 校验失败不落库。"""
        from plugins.member import settings as member_settings
        # mock DNS 解析：sms.example.com → 公网地址（测试环境无外网 DNS）
        import socket
        _orig_getaddrinfo = socket.getaddrinfo

        def _fake_getaddrinfo(host, *a, **kw):
            if host == 'sms.example.com':
                return _orig_getaddrinfo('223.5.5.5', *a, **kw)
            return _orig_getaddrinfo(host, *a, **kw)

        monkeypatch.setattr(socket, 'getaddrinfo', _fake_getaddrinfo)
        with app.app_context():
            with pytest.raises(ValueError):
                member_settings.save_group(
                    'sms', {'member_sms_webhook_url': 'http://127.0.0.1/sms?p={phone}&c={code}'})
            # 合法 URL 正常保存
            member_settings.save_group(
                'sms', {'member_sms_webhook_url': 'https://sms.example.com/send?p={phone}&c={code}'})
            db.session.commit()
            assert Setting.get('member_sms_webhook_url') == \
                'https://sms.example.com/send?p={phone}&c={code}'
            Setting.set('member_sms_webhook_url', '')
            db.session.commit()

    def test_sms_webhook_send_validates_final_url(self, app):
        """短信发送前对占位符替换后的最终 URL 再校验一次。"""
        from plugins.member import sms as member_sms
        with app.app_context():
            Setting.set('member_sms_webhook_url', 'http://169.254.169.254/{phone}/{code}')
            db.session.commit()
            with pytest.raises(RuntimeError, match='不安全'):
                member_sms._send_webhook('13800000000', '123456')
            Setting.set('member_sms_webhook_url', '')
            db.session.commit()


# ============================================================
# VULN-006：JWT 密钥隔离
# ============================================================

@security
class TestVuln006JWTSecret:

    def test_jwt_secret_not_reuse_flask_secret_key(self, app):
        """JWT 密钥绝不回退复用 SECRET_KEY。"""
        assert app.config.get('JWT_SECRET_KEY'), 'JWT_SECRET_KEY 未初始化'
        assert app.config['JWT_SECRET_KEY'] != app.config['SECRET_KEY']

    def test_jwt_secret_auto_generated_and_persisted(self, app):
        """jwt_secret_key 未配置且 DB 可用时，启动自动生成并持久化到 Setting。"""
        from app import create_app
        with app.app_context():
            Setting.set('jwt_secret_key', '')
            db.session.commit()
        # 重新建应用触发 JWT 初始化段（测试库表已存在，走自动生成+持久化分支）
        app2 = create_app('testing')
        with app2.app_context():
            value = Setting.get('jwt_secret_key')
            assert value, 'jwt_secret_key 未自动生成持久化'
            assert len(value) >= 32
            assert app2.config['JWT_SECRET_KEY'] == value
            assert app2.config['JWT_SECRET_KEY'] != app2.config['SECRET_KEY']
            # 入库为密文（敏感键）
            item = Setting.query.filter_by(key='jwt_secret_key').first()
            assert item.value.startswith('gAAAAA')


# ============================================================
# F-001：CSP 第三方源白名单
# ============================================================

@security
class TestF001CSPWhitelist:

    def _clear_csp_settings(self):
        for key in ('security_csp_script_src', 'security_csp_style_src',
                    'security_csp_img_src', 'security_csp_font_src',
                    'security_csp_connect_src', 'security_csp_media_src',
                    'security_csp_frame_src'):
            Setting.set(key, '')
        db.session.commit()

    def test_empty_whitelist_matches_v317_baseline(self, app):
        """空白名单时 CSP 与 v3.1.7 基线逐字节一致（回归基线）。"""
        from app import _build_csp
        with app.app_context():
            self._clear_csp_settings()
            assert _build_csp() == _CSP_BASELINE

    def test_response_header_matches_baseline(self, client):
        """空白名单时实际响应头与基线一致。"""
        with client.application.app_context():
            self._clear_csp_settings()
        resp = client.get('/')
        assert resp.headers.get('Content-Security-Policy') == _CSP_BASELINE

    def test_whitelist_appended_to_directive(self, client):
        """配置 script-src 白名单后响应头包含该源，其余指令不变。"""
        with client.application.app_context():
            self._clear_csp_settings()
            Setting.set('security_csp_script_src', 'https://cdn.example.com')
            db.session.commit()
        try:
            resp = client.get('/')
            csp = resp.headers.get('Content-Security-Policy', '')
            assert "script-src 'self' 'unsafe-inline' https://cdn.example.com" in csp
            assert "style-src 'self' 'unsafe-inline';" in csp
            assert "frame-ancestors 'self'" in csp
            assert 'connect-src' not in csp  # 未配置的指令不出现
        finally:
            with client.application.app_context():
                self._clear_csp_settings()

    def test_wildcard_subdomain_source(self, client):
        """子域通配 *.example.com 合法追加。"""
        with client.application.app_context():
            self._clear_csp_settings()
            Setting.set('security_csp_img_src', '*.example.com')
            db.session.commit()
        try:
            resp = client.get('/')
            csp = resp.headers.get('Content-Security-Policy', '')
            assert 'img-src \'self\' data: https: *.example.com' in csp
        finally:
            with client.application.app_context():
                self._clear_csp_settings()

    def test_validate_csp_sources(self):
        """保存校验：裸 * / 非 http(s) / userinfo / 空格引号均被拒。"""
        from app.admin.system.setting import _validate_csp_sources
        assert _validate_csp_sources('https://cdn.example.com')[0]
        assert _validate_csp_sources('*.example.com')[0]
        assert _validate_csp_sources('https://*.example.com')[0]
        for bad in ('*', 'javascript:alert(1)', 'data:text/html,x',
                    'ftp://evil.com', 'https://user@evil.com',
                    'https://evil.com/x?y=1', "https://evil.com';",
                    'https://ev il.com'):
            ok, err = _validate_csp_sources(bad)
            assert not ok, f'非法源未拒绝: {bad}'
            assert err, '拒绝时未给出错误消息'

    def test_invalid_entry_rejected_on_save(self, admin_client):
        """后台保存非法条目：提示行号且不落库。"""
        with admin_client.application.app_context():
            self._clear_csp_settings()
        resp = admin_client.post('/admin/settings/security', data={
            'admin_prefix': 'admin',
            'security_csp_script_src': '*',
        }, follow_redirects=False)
        assert resp.status_code == 302
        with admin_client.application.app_context():
            assert Setting.get('security_csp_script_src') == '', '非法条目被落库'

    def test_valid_entries_saved_on_post(self, admin_client):
        """后台保存合法条目并规范化（去空行）。"""
        with admin_client.application.app_context():
            self._clear_csp_settings()
        try:
            resp = admin_client.post('/admin/settings/security', data={
                'admin_prefix': 'admin',
                'security_csp_script_src': 'https://cdn.example.com\n\n*.foo.bar\n',
            })
            assert resp.status_code == 302
            with admin_client.application.app_context():
                assert Setting.get('security_csp_script_src') == \
                    'https://cdn.example.com\n*.foo.bar'
        finally:
            with admin_client.application.app_context():
                self._clear_csp_settings()

    def test_svg_sandbox_csp_not_affected(self, client):
        """SVG 响应仍为 sandbox CSP，不读取任何白名单源。"""
        import os
        with client.application.app_context():
            self._clear_csp_settings()
            Setting.set('security_csp_script_src', 'https://cdn.example.com')
            db.session.commit()
        static_dir = client.application.static_folder
        svg_path = os.path.join(static_dir, 'test_f001_sandbox.svg')
        try:
            with open(svg_path, 'w', encoding='utf-8') as f:
                f.write('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
            resp = client.get('/static/test_f001_sandbox.svg')
            assert resp.status_code == 200
            csp = resp.headers.get('Content-Security-Policy', '')
            assert 'sandbox' in csp
            assert 'cdn.example.com' not in csp, 'SVG 沙箱 CSP 不应包含白名单源'
        finally:
            if os.path.exists(svg_path):
                os.remove(svg_path)
            with client.application.app_context():
                self._clear_csp_settings()
