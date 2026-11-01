"""v3.1.5 Markdown 渲染与双写契约单元测试。"""
from types import SimpleNamespace

from app.constants import Editor
from app.utils.markdown_render import render, is_available, apply_editor_form


class TestRender:
    """markdown → HTML 渲染。"""

    def test_basic_heading(self):
        html = render('# 标题')
        assert '<h1>' in html and '标题' in html

    def test_empty_and_none(self):
        assert render('') == ''
        assert render(None) == ''

    def test_nl2br(self):
        # nl2br 扩展：单个换行转为 <br>（与前端 marked breaks:true 对齐）
        html = render('第一行\n第二行')
        assert '<br' in html

    def test_inline_html_passthrough(self):
        # 与 CKEditor sourceEditing 同信任模型：内联 HTML 透传
        html = render('段落 <span style="color:red">红字</span>')
        assert '<span style="color:red">' in html

    def test_table_extra(self):
        md = '| a | b |\n| --- | --- |\n| 1 | 2 |'
        assert '<table>' in render(md)

    def test_is_available(self):
        assert is_available() is True


class TestApplyEditorForm:
    """保存链路双写契约（apply_editor_form 是唯一写入口）。"""

    def _obj(self):
        return SimpleNamespace(content=None, content_md=None,
                               content_format=Editor.FORMAT_HTML)

    def test_markdown_mode(self):
        obj = self._obj()
        form = {'content': '<p>兜底</p>', 'content_md': '# 大标题', 'content_format': 'markdown'}
        apply_editor_form(obj, form, 'content', 'content')
        assert '<h1>' in obj.content          # content 始终是渲染后的 HTML
        assert obj.content_md == '# 大标题'    # 原文留存供编辑回填
        assert obj.content_format == 'markdown'

    def test_markdown_mode_md_missing_fallback_to_content(self):
        obj = self._obj()
        # content_md 缺失时以 content 字段作为 Markdown 源码
        form = {'content': '**加粗**', 'content_format': 'markdown'}
        apply_editor_form(obj, form, 'content', 'content')
        assert '<strong>' in obj.content
        assert obj.content_md == '**加粗**'
        assert obj.content_format == 'markdown'

    def test_html_mode_keeps_md_untouched(self):
        obj = self._obj()
        obj.content_md = '# 留存的原文'
        form = {'content': '<p>富文本</p>', 'content_md': '# 不应生效',
                'content_format': 'html'}
        apply_editor_form(obj, form, 'content', 'content')
        assert obj.content == '<p>富文本</p>'   # 原样写入
        assert obj.content_md == '# 留存的原文'  # 保留不动（切回 Markdown 不丢原文）
        assert obj.content_format == 'html'

    def test_missing_format_falls_back_html(self):
        obj = self._obj()
        apply_editor_form(obj, {'content': '<p>x</p>'}, 'content', 'content')
        assert obj.content == '<p>x</p>'
        assert obj.content_format == 'html'

    def test_invalid_format_falls_back_html(self):
        obj = self._obj()
        form = {'content': '<p>x</p>', 'content_format': 'weird',
                'content_md': '# 不应生效'}
        apply_editor_form(obj, form, 'content', 'content')
        assert obj.content == '<p>x</p>'
        assert obj.content_format == 'html'

    def test_translation_field_naming(self):
        # 多语言字段：{form_field}_md / {form_field}_format 按表单字段名推导
        obj = SimpleNamespace(content=None, content_md=None, content_format='html')
        form = {'content_en': '', 'content_en_md': '# EN', 'content_en_format': 'markdown'}
        apply_editor_form(obj, form, 'content_en', 'content')
        assert '<h1>' in obj.content
        assert obj.content_md == '# EN'
        assert obj.content_format == 'markdown'
