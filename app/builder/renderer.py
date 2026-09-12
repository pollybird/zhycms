"""布局渲染器：组件树 → 服务端 HTML。

渲染规则：
  - 模板解析链：themes/<当前主题>/builder/widgets/<type>.html
                → builder/widgets/<type>.html（含插件模板目录）
  - 组件取数：Widget.context(node, page_ctx)
  - 可见性：visibility.locales 语言白名单、member_only 会员限定
  - 插件门控：提供组件的插件被禁用后渲染空占位（预览态标红提示），不白页
  - 预览态：注入 data-zbw-id / data-zbw-children 属性供编辑器画布桥识别

render.html 继承当前主题 base.html，navbar/footer/SEO 与手工模板完全一致。
"""
from flask import current_app, render_template
from markupsafe import Markup, escape

from ..constants import Builder as _B
from ..utils.themes import get_active_theme
from .registry import get_widget, widget_owner
from .schema import normalize_layout


def _current_locale():
    try:
        from ..i18n import select_locale
        return select_locale()
    except Exception:
        return 'zh'


def _is_member():
    try:
        from ..plugin_system import frontend_guard
        guard = frontend_guard()
        return bool(guard and guard['is_authenticated']())
    except Exception:
        return False


def _node_visible(node, page_ctx):
    vis = node.get('visibility') or {}
    # 语言白名单：空=全部语言
    locs = vis.get('locales') or []
    if locs and page_ctx.get('locale') not in locs:
        return False
    # 会员限定
    if vis.get('member_only') and not page_ctx.get('is_member'):
        return False
    return True


def _template_base_ctx():
    """获取 Flask 模板上下文（context processor 注入的 site_settings/
    site_fragments/nav_columns/current_theme/theme_base 等）。

    组件 partial 通过 jinja_env.get_template().render() 直渲（异常隔离需要），
    该路径不会自动跑 context_processor，这里手动补全，保证组件模板与整页
    render_template() 环境一致。
    """
    try:
        base = {}
        current_app.update_template_context(base)
        return base
    except Exception:
        return {}


def _theme_template_exists(template_path):
    try:
        loader = current_app.jinja_env.loader
        loader.get_source(current_app.jinja_env, template_path)
        return True
    except Exception:
        return False


def _resolve_template(widget_type):
    """主题覆写优先，否则核心/插件通用目录。"""
    theme = get_active_theme()
    override = f'themes/{theme}/builder/widgets/{widget_type}.html'
    if _theme_template_exists(override):
        return override
    return f'builder/widgets/{widget_type}.html'


def render_node(node, page_ctx, depth=0):
    """渲染单个节点为 HTML 字符串（Markup）。"""
    if not isinstance(node, dict):
        return Markup('')
    if not _node_visible(node, page_ctx):
        return Markup('')

    ntype = node.get('type', '')
    widget = get_widget(ntype)
    preview = bool(page_ctx.get('preview'))

    # 插件禁用：生产空占位；预览标红提示（不阻断其余页面）
    if widget is None:
        owner = widget_owner(ntype)
        if preview and owner and owner != 'core':
            return Markup(
                '<div class="zbw-disabled-placeholder">组件 '
                f'{escape(ntype)} 所属插件 {escape(owner)} 未启用</div>'
            )
        return Markup('')

    def render_children(children=None):
        kids = node.get('children') if children is None else children
        parts = [render_node(c, page_ctx, depth + 1) for c in (kids or [])]
        return Markup(''.join(parts))

    locale = page_ctx.get('locale') or _current_locale()

    def localized(key, default=''):
        return widget.localized(node, key, locale, default)

    def node_attrs(*extra_classes):
        """预览态挂在组件根元素上的属性（生产态输出空串）。"""
        if not preview:
            return Markup('')
        cls = ' '.join(extra_classes)
        return Markup(
            f' data-zbw-id="{escape(node.get("id", ""))}"'
            f' data-zbw-type="{escape(ntype)}"'
            + (f' class="{escape(cls)}"' if cls else '')
        )

    def children_attrs():
        """预览态挂在子组件容器上的属性，画布桥据此做拖放排序。"""
        if not preview:
            return Markup('')
        accept = ','.join(widget.allowed_children) if widget.allowed_children else ''
        return Markup(
            f' data-zbw-children="{escape(node.get("id", ""))}"'
            f' data-zbw-accept="{escape(accept)}"'
        )

    # context_processor 注入的全站变量（site_fragments/theme_base/
    # site_settings 等）。partial 直渲不经过 render_template，需要手动补全；
    # 组件自身上下文优先级更高，因此放在最前面。
    ctx = dict(page_ctx.get('_tpl_base') or {})
    ctx.update({
        'node': node,
        'props': node.get('props') or {},
        'page_ctx': page_ctx,
        'preview': preview,
        'locale': locale,
        'render_node': lambda n: render_node(n, page_ctx, depth + 1),
        'render_children': render_children,
        'localized': localized,
        'node_attrs': node_attrs,
        'children_attrs': children_attrs,
        'zbw_p': lambda key, default='': widget.prop(node, key, default),
    })
    # 页面级上下文（column/article/pagination 等）在组件模板内可直接引用
    for _k, _v in page_ctx.items():
        if not _k.startswith('_') and _k not in ctx:
            ctx[_k] = _v

    # 组件取数（异常隔离：单个组件失败不拖垮整页）
    try:
        extra = widget.context(node, page_ctx) or {}
        if isinstance(extra, dict):
            ctx.update(extra)
    except Exception as e:
        current_app.logger.warning('构建器组件 %s 取数失败：%s', ntype, e)
        if preview:
            return Markup(
                f'<div class="zbw-disabled-placeholder">组件 {escape(ntype)} '
                f'取数失败：{escape(str(e))}</div>'
            )
        return Markup('')

    template = _resolve_template(ntype)
    try:
        return Markup(render_template_string_safe(template, ctx))
    except Exception as e:
        current_app.logger.exception('构建器组件 %s 渲染失败', ntype)
        if preview:
            return Markup(
                f'<div class="zbw-disabled-placeholder">组件 {escape(ntype)} '
                f'渲染失败：{escape(str(e))}</div>'
            )
        return Markup('')


def render_template_string_safe(template_name, ctx):
    return current_app.jinja_env.get_template(template_name).render(**ctx)


def render_layout_html(layout, page_ctx=None):
    """渲染整棵组件树。"""
    page_ctx = dict(page_ctx or {})
    page_ctx.setdefault('locale', _current_locale())
    page_ctx.setdefault('is_member', _is_member())
    page_ctx.setdefault('_qcache', {})
    page_ctx.setdefault('_tpl_base', _template_base_ctx())
    layout = normalize_layout(layout)
    parts = [render_node(n, page_ctx) for n in layout.get('root', [])]
    return Markup(''.join(parts))


def render_builder_page(layout, page_ctx=None, template='builder/render.html'):
    """渲染完整前台页面（继承当前主题 base.html）。

    page_ctx 至少包含：scope / nav / seo；按作用域可选 column / article /
    articles / pagination / fields 等。
    """
    page_ctx = dict(page_ctx or {})
    page_ctx.setdefault('locale', _current_locale())
    page_ctx.setdefault('is_member', _is_member())
    page_ctx.setdefault('_qcache', {})
    page_ctx.setdefault('_tpl_base', _template_base_ctx())
    layout = normalize_layout(layout)
    builder_html = Markup(
        ''.join(render_node(n, page_ctx) for n in layout.get('root', []))
    )
    return render_template(
        template,
        builder_html=builder_html,
        builder_scope=page_ctx.get('scope', ''),
        preview=bool(page_ctx.get('preview')),
        **{k: v for k, v in page_ctx.items()
           if k not in ('_qcache', 'preview', 'locale', 'is_member')}
    )
