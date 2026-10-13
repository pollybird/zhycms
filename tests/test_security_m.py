"""中危安全修复测试（v3.1.2，GitCode issue #2 M1-M5）。

覆盖：
  - M1：表单 int() 输入保护（safe_int）
  - M2：上传子目录白名单 + _safe_sub_dir 二次校验
  - M3：CKEditorFuncNum 反射型 XSS 防护
  - M4：SVG 上传管控（开关 + 内容嗅探 + 大小上限 + 响应头）
  - M5：验证码一次性消费
"""
import io

import pytest

from app.extensions import db
from app.models.setting import Setting
from app.utils.helpers import safe_int
from app.utils.uploads import _safe_sub_dir, ALLOWED_SUB_DIRS


security = pytest.mark.security


# ============================================================
# M1：safe_int
# ============================================================

@security
class TestMSafeInt:

    def test_safe_int_basic(self):
        assert safe_int('42') == 42
        assert safe_int(42) == 42
        assert safe_int('  42  ') == 42
        assert safe_int(None) == 0
        assert safe_int('') == 0
        assert safe_int('abc') == 0
        assert safe_int('1.5') == 0  # int() 拒绝
        assert safe_int('abc', default=5) == 5
        assert safe_int(None, default=7) == 7

    def test_article_sort_order_non_numeric_does_not_500(self, admin_client):
        """文章保存提交 sort_order=abc 应被 safe_int 兜底为 0，不抛 500。"""
        from tests.factories import make_column

        with admin_client.application.app_context():
            col = make_column(slug='m1-col-list', col_type='list')
            db.session.commit()
            cid = col.id

        # 故意传非数字 sort_order，校验返回非 500
        resp = admin_client.post(
            f'/admin/columns/{cid}/articles/create',
            data={
                'title': 'M1 测试文章',
                'sort_order': 'abc-definitely-not-a-number',
                'status': 'draft',
            }, follow_redirects=False)
        # 应该是 302（创建成功）或 200（重渲染），但不能是 500
        assert resp.status_code != 500, 'safe_int 未生效，int() 仍抛 ValueError'

    def test_column_page_size_non_numeric_falls_back_to_default(self, admin_client):
        """栏目 page_size=xyz 应回退到默认 10，不抛 500。"""
        resp = admin_client.post(
            '/admin/columns/create',
            data={
                'name': 'M1 列目',
                'slug': 'm1-col-page-size-test',
                'type': 'list',
                'page_size': 'xyz-not-a-number',
            }, follow_redirects=False)
        assert resp.status_code != 500

    def test_fragment_sort_order_non_numeric(self, admin_client):
        """碎片分组 sort_order=abc 不应 500。"""
        resp = admin_client.post(
            '/admin/fragments/groups/create',
            data={'name': 'M1 分组', 'sort_order': 'NaN'},
            follow_redirects=False)
        assert resp.status_code != 500


# ============================================================
# M2：子目录白名单
# ============================================================

@security
class TestMSubDirWhitelist:

    def test_safe_sub_dir_valid(self):
        assert _safe_sub_dir('common') == 'common'
        assert _safe_sub_dir('article') == 'article'
        assert _safe_sub_dir('fragment/image') == 'fragment/image'
        assert _safe_sub_dir('fragment/file') == 'fragment/file'
        assert _safe_sub_dir('') == 'common'
        assert _safe_sub_dir(None) == 'common'

    def test_safe_sub_dir_traversal_rejected(self):
        # 路径穿越
        assert _safe_sub_dir('../etc/passwd') == 'common'
        assert _safe_sub_dir('..') == 'common'
        assert _safe_sub_dir('../../secret') == 'common'
        assert _safe_sub_dir('common/../../../etc') == 'common'
        # 绝对路径
        assert _safe_sub_dir('/etc/passwd') == 'common'
        assert _safe_sub_dir('\\etc\\passwd') == 'common'
        # 不在白名单
        assert _safe_sub_dir('unknown_dir') == 'common'
        assert _safe_sub_dir('theme/../secret') == 'common'
        # 段格式不合法（含点）
        assert _safe_sub_dir('common/sneaky.txt') == 'common'
        # 段格式不合法（超长）
        assert _safe_sub_dir('common/' + 'a' * 33) == 'common'

    def test_allowed_sub_dirs_contains_required(self):
        """白名单至少覆盖现有调用点：common/image/file/avatar/editor/article/theme/site/column/fragment。"""
        for required in ('common', 'image', 'file', 'avatar', 'editor',
                         'article', 'theme', 'site', 'column', 'fragment'):
            assert required in ALLOWED_SUB_DIRS, f'白名单缺少 {required}'

    def test_upload_route_traversal_type_falls_to_common(self, admin_client):
        """type=../x 通过上传入口时应被 _safe_sub_dir 归一化到 common，
        文件仍能上传成功（不会写到 UPLOAD_FOLDER 之外）。"""
        # 准备一个最小合法 png（1x1）以通过 MIME/后缀校验
        PNG_HEX = ('89504e470d0a1a0a0000000d49484452000000010000000108020000'
                   '00907753de0000000c494441540899636000000000020001e221bc33'
                   '0000000049454e44ae426082')
        data = bytes.fromhex(PNG_HEX)

        resp = admin_client.post(
            '/admin/upload',
            data={'type': '../../etc/passwd',
                  'file': (io.BytesIO(data), 'm2.png')},
            content_type='multipart/form-data')
        assert resp.status_code == 200
        import json as _json
        body = resp.get_data(as_text=True)
        try:
            payload = _json.loads(body)
        except _json.JSONDecodeError:
            pytest.fail(f'响应不是 JSON：{body[:200]}')
        path = payload.get('path', '')
        assert path.startswith('uploads/common/'), \
            f'type=../etc/passwd 应回退到 common，实际 path={path}'


# ============================================================
# M3：CKEditorFuncNum 反射型 XSS 防护
# ============================================================

@security
class TestMCKEditorFuncNum:

    def test_func_num_invalid_pattern_returns_400(self, admin_client):
        """func_num 含非数字字符应直接 400，不反射到 <script>。"""
        resp = admin_client.post(
            '/admin/upload?CKEditorFuncNum=alert(1)',
            data={'file': (io.BytesIO(b'\x89PNG\r\n\x1a\n'), 'm3.png')},
            content_type='multipart/form-data')
        assert resp.status_code == 400

    def test_func_num_script_payload_rejected(self, admin_client):
        """func_num=</script><script>alert(1)</script> 应 400，不反射。"""
        resp = admin_client.post(
            '/admin/upload?CKEditorFuncNum=</script><script>alert(1)</script>',
            data={'file': (io.BytesIO(b'\x89PNG\r\n\x1a\n'), 'm3b.png')},
            content_type='multipart/form-data')
        assert resp.status_code == 400

    def test_func_num_too_long_rejected(self, admin_client):
        """func_num 7 位数字超出 1-6 位上限 → 400。"""
        resp = admin_client.post(
            '/admin/upload?CKEditorFuncNum=1234567',
            data={'file': (io.BytesIO(b'\x89PNG\r\n\x1a\n'), 'm3c.png')},
            content_type='multipart/form-data')
        assert resp.status_code == 400

    def test_func_num_valid_numeric_accepted(self, admin_client):
        """func_num=42（合法）应被接受，并经 html.escape 渲染。"""
        PNG_HEX = ('89504e470d0a1a0a0000000d49484452000000010000000108020000'
                   '00907753de0000000c494441540899636000000000020001e221bc33'
                   '0000000049454e44ae426082')
        data = bytes.fromhex(PNG_HEX)
        resp = admin_client.post(
            '/admin/upload?CKEditorFuncNum=42',
            data={'file': (io.BytesIO(data), 'm3ok.png')},
            content_type='multipart/form-data')
        assert resp.status_code == 200
        # CKEditor callback 形式：window.parent.CKEDITOR.tools.callFunction(42, ...);
        body = resp.get_data(as_text=True)
        assert 'window.parent.CKEDITOR.tools.callFunction(42' in body


# ============================================================
# M4：SVG 上传管控
# ============================================================

@security
class TestMSvgUploadControl:

    def test_default_off(self, app):
        with app.app_context():
            assert Setting.get('upload_allow_svg') == 'off'

    def test_svg_rejected_when_off(self, admin_client):
        """upload_allow_svg=off（默认）时，即便 allowed_exts 含 svg 也拒绝。"""
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        resp = admin_client.post(
            '/admin/upload',
            data={'file': (io.BytesIO(svg), 'evil.svg'),
                  'type': 'common'},
            content_type='multipart/form-data')
        # 上传失败：返回 400 且提示需到设置开启
        assert resp.status_code == 400
        err = resp.get_json().get('error', '')
        assert 'SVG' in err, f'未提示 SVG 关闭: {err}'

    def test_svg_benign_accepted_when_on(self, admin_client):
        """开启后，无脚本片段的 SVG 允许上传。"""
        with admin_client.application.app_context():
            Setting.set('upload_allow_svg', 'on')
            db.session.commit()
        try:
            svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
            resp = admin_client.post(
                '/admin/upload',
                data={'file': (io.BytesIO(svg), 'ok.svg'),
                      'type': 'common'},
                content_type='multipart/form-data')
            assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        finally:
            with admin_client.application.app_context():
                Setting.set('upload_allow_svg', 'off')
                db.session.commit()

    def test_svg_with_script_rejected_when_on(self, admin_client):
        """开启后，含 <script> 片段的 SVG 仍被拒。"""
        with admin_client.application.app_context():
            Setting.set('upload_allow_svg', 'on')
            db.session.commit()
        try:
            svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
            resp = admin_client.post(
                '/admin/upload',
                data={'file': (io.BytesIO(svg), 'evil.svg'),
                      'type': 'common'},
                content_type='multipart/form-data')
            assert resp.status_code == 400
            err = resp.get_json().get('error', '')
            assert '危险脚本' in err, f'未提示危险脚本: {err}'
        finally:
            with admin_client.application.app_context():
                Setting.set('upload_allow_svg', 'off')
                db.session.commit()

    def test_svg_with_onload_rejected_when_on(self, admin_client):
        """开启后，onload= 事件处理器被拒。"""
        with admin_client.application.app_context():
            Setting.set('upload_allow_svg', 'on')
            db.session.commit()
        try:
            svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'
            resp = admin_client.post(
                '/admin/upload',
                data={'file': (io.BytesIO(svg), 'onload.svg'),
                      'type': 'common'},
                content_type='multipart/form-data')
            assert resp.status_code == 400
        finally:
            with admin_client.application.app_context():
                Setting.set('upload_allow_svg', 'off')
                db.session.commit()

    def test_svg_oversize_rejected_when_on(self, admin_client):
        """开启后，>512KB 的 SVG 被拒。"""
        with admin_client.application.app_context():
            Setting.set('upload_allow_svg', 'on')
            db.session.commit()
        try:
            # 构造 > 512KB 的合法 SVG（填充注释）
            big_body = '<svg xmlns="http://www.w3.org/2000/svg"><!-- ' + ('A' * (600 * 1024)) + ' --></svg>'
            svg = big_body.encode('utf-8')
            resp = admin_client.post(
                '/admin/upload',
                data={'file': (io.BytesIO(svg), 'big.svg'),
                      'type': 'common'},
                content_type='multipart/form-data')
            assert resp.status_code == 400
            err = resp.get_json().get('error', '')
            assert '过大' in err, f'未提示过大: {err}'
        finally:
            with admin_client.application.app_context():
                Setting.set('upload_allow_svg', 'off')
                db.session.commit()

    def test_svg_response_has_sandbox_csp(self, client):
        """访问 .svg 静态响应时，CSP 应附加 sandbox（兜底防护存量 SVG）。"""
        import os
        static_dir = client.application.static_folder
        svg_path = os.path.join(static_dir, 'test_m4_sandbox.svg')
        try:
            with open(svg_path, 'w', encoding='utf-8') as f:
                f.write('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
            resp = client.get('/static/test_m4_sandbox.svg')
            assert resp.status_code == 200
            csp = resp.headers.get('Content-Security-Policy', '')
            assert 'sandbox' in csp, f'未附加 sandbox CSP: {csp}'
            ct = resp.headers.get('Content-Type', '')
            assert ct.startswith('image/svg+xml'), f'Content-Type 不正确: {ct}'
            assert resp.headers.get('X-Content-Type-Options') == 'nosniff'
        finally:
            if os.path.exists(svg_path):
                os.remove(svg_path)


# ============================================================
# M5：验证码一次性消费
# ============================================================

@security
class TestMCaptchaOneShot:

    def test_captcha_popped_on_wrong_captcha(self, client):
        """验证码错误时 session['captcha'] 应已被 pop，不残留可复用。"""
        with client.session_transaction() as sess:
            sess['captcha'] = 'ABCD'
        # 提交错误验证码
        resp = client.post('/admin/login', data={
            'username': 'admin', 'password': 'admin123',
            'captcha': 'wrong',
        })
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert 'captcha' not in sess, \
                '验证码错误后 session.captcha 仍残留，可被复用枚举密码'

    def test_captcha_popped_on_wrong_password(self, client):
        """验证码正确但密码错误时，captcha 也应已被消费。"""
        with client.session_transaction() as sess:
            sess['captcha'] = 'ABCD'
        # 提交正确验证码 + 错误密码
        resp = client.post('/admin/login', data={
            'username': 'admin', 'password': 'wrong-password',
            'captcha': 'abcd',
        })
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert 'captcha' not in sess, \
                '验证码正确但密码错误时 session.captcha 仍残留，可被复用枚举密码'

    def test_captcha_cannot_reuse_for_brute_force(self, client):
        """同码复用场景：第一次成功通过验证码（密码错误），第二次同码必须被拒。"""
        with client.session_transaction() as sess:
            sess['captcha'] = 'ABCD'
        # 第一次：正确验证码 + 错误密码
        r1 = client.post('/admin/login', data={
            'username': 'admin', 'password': 'wrong-1',
            'captcha': 'abcd',
        })
        assert r1.status_code == 200
        # 第二次：再次用同码 → 必须提示验证码错误
        r2 = client.post('/admin/login', data={
            'username': 'admin', 'password': 'wrong-2',
            'captcha': 'abcd',
        })
        assert r2.status_code == 200
        body = r2.get_data(as_text=True)
        assert '验证码错误' in body, '同码复用未被拒，M5 修复未生效'

    def test_captcha_consumed_on_successful_login(self, client):
        """成功登录后 session.captcha 应已被 pop。"""
        with client.session_transaction() as sess:
            sess['captcha'] = 'ABCD'
        resp = client.post('/admin/login', data={
            'username': 'admin', 'password': 'admin123',
            'captcha': 'abcd',
        }, follow_redirects=False)
        # 成功登录会 302 跳转到 dashboard
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert 'captcha' not in sess
