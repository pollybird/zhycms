"""基础组件：heading/text/richtext/image/button/icon-box/alert/video。"""
from ...constants import Builder as _B
from ..registry import Widget, register_widget

_ALIGN = [
    ['left', '左对齐'], ['center', '居中'], ['right', '右对齐'],
]


class Heading(Widget):
    type = 'heading'
    category = _B.CAT_BASIC
    label = '标题'
    icon = 'fa-heading'
    description = 'H1-H6 标题'
    default_props = {'text': '标题文字', 'level': 2, 'align': 'left', 'color': ''}
    prop_schema = [
        {'key': 'text', 'label': '标题文字', 'type': 'text', 'localized': True},
        {'key': 'level', 'label': '标题级别', 'type': 'select', 'options':
         [[str(i), f'H{i}'] for i in range(1, 7)]},
        {'key': 'align', 'label': '对齐', 'type': 'select', 'options': _ALIGN},
        {'key': 'color', 'label': '文字颜色', 'type': 'color'},
    ]


class Text(Widget):
    type = 'text'
    category = _B.CAT_BASIC
    label = '段落文本'
    icon = 'fa-paragraph'
    description = '普通段落（自动转义换行）'
    default_props = {'content': '在这里输入段落文字。', 'align': 'left'}
    prop_schema = [
        {'key': 'content', 'label': '段落内容', 'type': 'textarea', 'localized': True},
        {'key': 'align', 'label': '对齐', 'type': 'select', 'options': _ALIGN},
    ]


class RichText(Widget):
    type = 'richtext'
    category = _B.CAT_BASIC
    label = '富文本'
    icon = 'fa-align-left'
    description = 'CKEditor 富文本内容'
    default_props = {'html': '<p>在这里编辑富文本内容。</p>'}
    prop_schema = [
        {'key': 'html', 'label': '富文本内容', 'type': 'richtext', 'localized': True},
    ]


class Image(Widget):
    type = 'image'
    category = _B.CAT_BASIC
    label = '图片'
    icon = 'fa-image'
    description = '单张图片，可选超链接与形状'
    default_props = {
        'src': '', 'alt': '', 'href': '', 'shape': 'rounded',
        'width': '100%', 'align': 'center', 'target_blank': False,
    }
    prop_schema = [
        {'key': 'src', 'label': '图片地址', 'type': 'image'},
        {'key': 'alt', 'label': '替代文字（ALT）', 'type': 'text', 'localized': True},
        {'key': 'href', 'label': '点击跳转链接', 'type': 'url'},
        {'key': 'target_blank', 'label': '新窗口打开', 'type': 'toggle'},
        {'key': 'shape', 'label': '形状', 'type': 'select', 'options': [
            ['rounded', '圆角'], ['img-thumbnail', '边框卡片'],
            ['rounded-circle', '圆形'], ['', '无'],
        ]},
        {'key': 'width', 'label': '宽度', 'type': 'select', 'options': [
            ['25%', '25%'], ['50%', '50%'], ['75%', '75%'], ['100%', '100%'],
        ]},
        {'key': 'align', 'label': '对齐', 'type': 'select', 'options': _ALIGN},
    ]


class Button(Widget):
    type = 'button'
    category = _B.CAT_BASIC
    label = '按钮'
    icon = 'fa-mouse-pointer'
    description = '行动按钮'
    default_props = {
        'text': '了解更多', 'href': '#', 'style': 'primary',
        'size': 'md', 'align': 'left', 'icon': '', 'target_blank': False,
    }
    prop_schema = [
        {'key': 'text', 'label': '按钮文字', 'type': 'text', 'localized': True},
        {'key': 'href', 'label': '链接地址', 'type': 'url'},
        {'key': 'target_blank', 'label': '新窗口打开', 'type': 'toggle'},
        {'key': 'style', 'label': '风格', 'type': 'select', 'options': [
            ['primary', '主色实心'], ['secondary', '灰色实心'],
            ['outline-primary', '主色描边'], ['success', '绿色实心'],
            ['danger', '红色实心'], ['dark', '深色实心'],
        ]},
        {'key': 'size', 'label': '尺寸', 'type': 'select', 'options': [
            ['sm', '小'], ['md', '中'], ['lg', '大'],
        ]},
        {'key': 'icon', 'label': '图标类名（FontAwesome）', 'type': 'icon',
         'help': '如 fas fa-phone'},
        {'key': 'align', 'label': '对齐', 'type': 'select', 'options': _ALIGN},
    ]


class IconBox(Widget):
    type = 'icon-box'
    category = _B.CAT_BASIC
    label = '图标文字卡'
    icon = 'fa-icons'
    description = '图标 + 标题 + 描述，适合优势/服务点'
    allowed_children = ()
    default_props = {
        'icon': 'fas fa-star', 'title': '核心优势', 'text': '用一段话描述优势。',
        'color': '#3498db', 'align': 'center',
    }
    prop_schema = [
        {'key': 'icon', 'label': '图标类名', 'type': 'icon'},
        {'key': 'color', 'label': '图标颜色', 'type': 'color'},
        {'key': 'title', 'label': '标题', 'type': 'text', 'localized': True},
        {'key': 'text', 'label': '描述', 'type': 'textarea', 'localized': True},
        {'key': 'align', 'label': '对齐', 'type': 'select', 'options': _ALIGN},
    ]


class Alert(Widget):
    type = 'alert'
    category = _B.CAT_BASIC
    label = '提示条'
    icon = 'fa-bullhorn'
    description = '公告/通知类提示条'
    default_props = {
        'content': '在这里填写通知内容。', 'alert_type': 'info',
        'dismissible': False,
    }
    prop_schema = [
        {'key': 'content', 'label': '提示内容', 'type': 'textarea', 'localized': True},
        {'key': 'alert_type', 'label': '类型', 'type': 'select', 'options': [
            ['info', '信息（蓝）'], ['success', '成功（绿）'],
            ['warning', '警告（黄）'], ['danger', '危险（红）'],
        ]},
        {'key': 'dismissible', 'label': '可关闭', 'type': 'toggle'},
    ]


class VideoEmbed(Widget):
    type = 'video-embed'
    category = _B.CAT_BASIC
    label = '视频嵌入'
    icon = 'fa-video'
    description = '粘贴 YouTube / 优酷等分享链接，响应式 16:9'
    default_props = {'url': '', 'ratio': '16by9'}
    prop_schema = [
        {'key': 'url', 'label': '视频链接或 <iframe> 嵌入地址', 'type': 'url',
         'help': '支持 youtu.be / youtube.com/watch（自动转换）'},
        {'key': 'ratio', 'label': '宽高比', 'type': 'select', 'options': [
            ['16by9', '16:9'], ['4by3', '4:3'], ['21by9', '21:9'],
        ]},
    ]

    def context(self, node, page_ctx):
        import re
        url = self.prop(node, 'url', '')
        embed = ''
        m = re.search(r'(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/))([\w-]{6,})', url)
        if m:
            embed = f'https://www.youtube.com/embed/{m.group(1)}'
        elif 'youtube.com/embed/' in url:
            embed = url
        return {'embed_url': embed}


for _w in (Heading, Text, RichText, Image, Button, IconBox, Alert, VideoEmbed):
    register_widget(_w)
