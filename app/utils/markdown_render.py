"""Markdown 渲染（v3.1.5）。

唯一用途：后台保存 Markdown 内容时在此转换为 HTML 写入 content 列
（content 始终是 HTML，全站消费方零改动；原文另存 *_md 列供编辑回填）。

每次调用新建 Markdown 实例，避免多线程共享实例的状态污染。
markdown 依赖缺失时降级为 html.escape 纯文本转义 + 告警日志，
保证后台不 500（兜底分支，正常部署不会触发）。
"""
import html as _html
import logging

try:
    import markdown as _md
    _HAS_MD = True
except ImportError:  # pragma: no cover - 依赖缺失兜底
    _md = None
    _HAS_MD = False

_EXTENSIONS = ['extra', 'sane_lists', 'nl2br']


def is_available():
    """markdown 依赖是否可用（供「编辑设置」页只读展示排障）。"""
    return _HAS_MD


def render(text):
    """Markdown 源码 → HTML 字符串；空值返回 ''。

    内联 HTML 透传（与 CKEditor sourceEditing 同信任模型，不额外清洗）。
    """
    if not text:
        return ''
    if not _HAS_MD:  # pragma: no cover - 依赖缺失兜底
        logging.getLogger(__name__).warning(
            'markdown 包未安装，Markdown 内容降级为纯文本转义')
        return '<p>%s</p>' % _html.escape(text).replace('\n', '<br>')
    return _md.markdown(text, extensions=_EXTENSIONS, output_format='html5')


def apply_editor_form(obj, form_data, form_field, attr):
    """把表单富文本字段按格式双写到对象（v3.1.5，唯一写入口）。

    :param obj: 目标模型实例（Article/Column/Fragment 或其翻译）
    :param form_data: request.form（或等效映射）
    :param form_field: 表单字段名，如 content / content_en / page_content / value
    :param attr: 对象上的基础属性名，如 content / page_content / value
                 （md 列与 format 列按 ``{attr}_md`` / ``{attr}_format`` 推导）

    约定：
    - format == markdown → ``attr`` = render(md 原文)，``{attr}_md`` = 原文
    - 其他（含缺失/非法值）→ html 语义：``attr`` 原样写入，
      ``{attr}_md`` 保留不动（切回富文本后 Markdown 原文不丢失），
      ``{attr}_format`` 置 'html'
    """
    from ..constants import Editor

    fmt = form_data.get(f'{form_field}_format')
    if fmt == Editor.FORMAT_MARKDOWN:
        md = form_data.get(f'{form_field}_md') or form_data.get(form_field) or ''
        setattr(obj, attr, render(md))
        setattr(obj, f'{attr}_md', md)
        setattr(obj, f'{attr}_format', Editor.FORMAT_MARKDOWN)
    else:
        setattr(obj, attr, form_data.get(form_field) or '')
        setattr(obj, f'{attr}_format', Editor.FORMAT_HTML)
