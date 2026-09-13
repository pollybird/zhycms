"""全局页面样式（layout.styles）。

用户在构建器中自定义整页风格：页面/内容区背景、正文/标题/链接颜色、
底部背景与文字色、容器（.zbw-container）圆角/边框/阴影。

安全模型：
  - 样式只能取白名单键；颜色只接受 #RRGGBB；枚举值只能选预设
  - CSS 由本模块按固定模板拼接，永不接受用户自由文本，杜绝注入
  - 所有项均可空：未设置时输出空串，主题原样呈现（老页面零变化）
"""
import re

_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

# 枚举预设（值即最终输出到 CSS 的安全片段）
_RADIUS_OPTIONS = ['0px', '2px', '4px', '8px', '12px', '16px']
_BORDER_WIDTH_OPTIONS = ['0px', '1px', '2px', '3px']
_SHADOW_OPTIONS = {
    'sm': '0 1px 3px rgba(0,0,0,.10)',
    'md': '0 2px 12px rgba(0,0,0,.12)',
    'lg': '0 8px 24px rgba(0,0,0,.16)',
}

# 编辑器据此自动生成「全局样式」表单（与组件 prop_schema 同构）
STYLE_SCHEMA = [
    {'key': 'page_bg', 'label': '页面背景色', 'type': 'color',
     'help': '整个页面（含两侧留白区域）的底色'},
    {'key': 'content_bg', 'label': '内容区背景色', 'type': 'color',
     'help': '构建器内容区域的底色'},
    {'key': 'text_color', 'label': '正文颜色', 'type': 'color'},
    {'key': 'heading_color', 'label': '标题颜色', 'type': 'color',
     'help': '内容区所有标题；组件单独设置的标题色优先'},
    {'key': 'link_color', 'label': '链接颜色', 'type': 'color'},
    {'key': 'footer_bg', 'label': '底部背景色', 'type': 'color',
     'help': '覆盖当前主题的页脚背景（含渐变主题）'},
    {'key': 'footer_color', 'label': '底部文字色', 'type': 'color'},
    {'key': 'radius', 'label': '容器圆角', 'type': 'select',
     'options': [[v, v] for v in _RADIUS_OPTIONS]},
    {'key': 'border_width', 'label': '容器边框宽度', 'type': 'select',
     'options': [[v, ('无边框' if v == '0px' else v)]
                 for v in _BORDER_WIDTH_OPTIONS]},
    {'key': 'border_color', 'label': '容器边框颜色', 'type': 'color'},
    {'key': 'shadow', 'label': '容器阴影', 'type': 'select',
     'options': [['none', '无阴影'], ['sm', '轻微'], ['md', '中等'],
                 ['lg', '明显']]},
]

_COLOR_KEYS = {f['key'] for f in STYLE_SCHEMA if f['type'] == 'color'}
_SELECT_OPTIONS = {
    'radius': set(_RADIUS_OPTIONS),
    'border_width': set(_BORDER_WIDTH_OPTIONS),
    'shadow': set(_SHADOW_OPTIONS) | {'none'},
}
STYLE_KEYS = {f['key'] for f in STYLE_SCHEMA}

_HEADING_SELECTORS = ', '.join(
    f'.zbw-page-root h{i}' for i in range(1, 7))


class StyleError(ValueError):
    """全局样式配置非法。"""


def validate_styles(styles):
    """校验 layout.styles；返回规整后的 dict（空值统一为 ''）。"""
    if styles is None:
        return {}
    if not isinstance(styles, dict):
        raise StyleError('全局样式必须是对象')
    cleaned = {}
    for key, val in styles.items():
        if key not in STYLE_KEYS:
            raise StyleError(f'不支持的全局样式项：{key}')
        if not isinstance(val, str):
            raise StyleError(f'全局样式 {key} 必须是字符串')
        val = val.strip()
        if not val:
            continue
        if key in _COLOR_KEYS:
            if not _COLOR_RE.match(val):
                raise StyleError(f'{key} 必须是 #RRGGBB 格式颜色')
        elif key in _SELECT_OPTIONS:
            if val not in _SELECT_OPTIONS[key]:
                raise StyleError(f'{key} 取值非法')
        cleaned[key] = val
    return cleaned


def build_global_css(styles):
    """按白名单样式生成 CSS 字符串；无任何有效配置时返回 ''。

    生成结果仅含白名单键与固定模板，调用方可直接标记为 Markup。
    """
    try:
        s = validate_styles(styles)
    except StyleError:
        return ''
    if not s:
        return ''

    rules = []
    if s.get('page_bg'):
        rules.append(f'body {{ background-color: {s["page_bg"]}; }}')

    root_decl = []
    if s.get('content_bg'):
        root_decl.append(f'background-color: {s["content_bg"]}')
    if s.get('text_color'):
        root_decl.append(f'color: {s["text_color"]}')
    if root_decl:
        rules.append('.zbw-page-root { ' + '; '.join(root_decl) + '; }')

    if s.get('heading_color'):
        rules.append(
            f'{_HEADING_SELECTORS}, .zbw-page-root .zbw-heading'
            f' {{ color: {s["heading_color"]}; }}')
    if s.get('link_color'):
        rules.append(f'.zbw-page-root a {{ color: {s["link_color"]}; }}')

    if s.get('footer_bg'):
        # 部分主题（如 blue）页脚使用渐变背景，background-color 会被
        # background-image 遮住，需同时去掉渐变图片
        color = s['footer_bg']
        rules.append(
            'footer.footer { background-image: none !important;'
            f' background-color: {color} !important;'
            ' }')
    if s.get('footer_color'):
        rules.append(
            'footer.footer, footer.footer h1, footer.footer h2,'
            ' footer.footer h3, footer.footer h4, footer.footer h5,'
            ' footer.footer h6, footer.footer p, footer.footer li,'
            ' footer.footer small, footer.footer a'
            f' {{ color: {s["footer_color"]}; }}')

    # 容器装饰：圆角 / 边框 / 阴影
    cont_decl = []
    if s.get('radius'):
        cont_decl.append(f'border-radius: {s["radius"]}')
    width = s.get('border_width') or '0px'
    if width != '0px':
        border_color = s.get('border_color') or '#dee2e6'
        cont_decl.append(f'border: {width} solid {border_color}')
    if s.get('shadow') and s['shadow'] != 'none':
        cont_decl.append(f'box-shadow: {_SHADOW_OPTIONS[s["shadow"]]}')
    if cont_decl:
        rules.append(
            '.zbw-page-root .zbw-container'
            ' { ' + '; '.join(cont_decl) + '; }')

    return '\n'.join(rules)
