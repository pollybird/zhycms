"""布局组件：section / container / grid-row / grid-col / spacer / divider。"""
from ...constants import Builder as _B
from ..registry import Widget, register_widget


class Section(Widget):
    type = 'section'
    category = _B.CAT_LAYOUT
    label = '通栏区块'
    icon = 'fa-columns'
    description = '全宽通栏，可设背景色与内边距，内部容器自动居中'
    allowed_children = ('*',)
    default_props = {
        'bg_color': '#ffffff', 'text_color': '', 'padding': 'py-5',
        'container': True,
    }
    prop_schema = [
        {'key': 'bg_color', 'label': '背景色', 'type': 'color'},
        {'key': 'text_color', 'label': '文字颜色', 'type': 'color'},
        {'key': 'padding', 'label': '上下内边距', 'type': 'select', 'options': [
            ['py-0', '无'], ['py-3', '小'], ['py-5', '中'], ['py-8', '大'],
        ]},
        {'key': 'container', 'label': '内容居中（固定宽度）', 'type': 'toggle'},
    ]


class Container(Widget):
    type = 'container'
    category = _B.CAT_LAYOUT
    label = '容器'
    icon = 'fa-square'
    description = '居中内容容器，可切换固定宽度/全宽'
    allowed_children = ('*',)
    default_props = {'fluid': False}
    prop_schema = [
        {'key': 'fluid', 'label': '全宽容器（container-fluid）', 'type': 'toggle'},
    ]


class GridRow(Widget):
    type = 'grid-row'
    category = _B.CAT_LAYOUT
    label = '栅格行'
    icon = 'fa-grip'
    description = 'Bootstrap 栅格行，内部放栅格列'
    allowed_children = ('grid-col',)
    default_children = 2
    default_props = {'gutter': 'normal'}
    prop_schema = [
        {'key': 'gutter', 'label': '列间距', 'type': 'select', 'options': [
            ['no-gutters', '无间距'], ['normal', '标准'], ['large', '加大'],
        ]},
    ]


class GridCol(Widget):
    type = 'grid-col'
    category = _B.CAT_LAYOUT
    label = '栅格列'
    icon = 'fa-square'
    description = '栅格列，可放任意组件'
    allowed_children = ('*',)
    default_props = {'span_md': 6, 'span_sm': 12, 'align_self': 'auto'}
    prop_schema = [
        {'key': 'span_sm', 'label': '小屏（≥576px）占宽', 'type': 'select', 'options':
         [[str(i), f'{i}/12'] for i in range(1, 13)]},
        {'key': 'span_md', 'label': '中屏（≥768px）占宽', 'type': 'select', 'options':
         [[str(i), f'{i}/12'] for i in range(1, 13)]},
        {'key': 'align_self', 'label': '垂直对齐', 'type': 'select', 'options': [
            ['auto', '默认'], ['start', '顶部'], ['center', '居中'], ['end', '底部'],
        ]},
    ]


class Spacer(Widget):
    type = 'spacer'
    category = _B.CAT_LAYOUT
    label = '间距'
    icon = 'fa-arrows-alt-v'
    description = '垂直留白'
    default_props = {'height': '40px'}
    prop_schema = [
        {'key': 'height', 'label': '高度', 'type': 'select', 'options': [
            ['16px', '小（16px）'], ['40px', '中（40px）'],
            ['80px', '大（80px）'], ['120px', '特大（120px）'],
        ]},
    ]


class Divider(Widget):
    type = 'divider'
    category = _B.CAT_LAYOUT
    label = '分割线'
    icon = 'fa-minus'
    description = '水平分割线'
    default_props = {'width': '100%', 'color': '#dee2e6', 'margin': 'my-4'}
    prop_schema = [
        {'key': 'width', 'label': '宽度', 'type': 'select', 'options': [
            ['100%', '100%'], ['66%', '2/3'], ['50%', '一半'], ['25%', '1/4'],
        ]},
        {'key': 'color', 'label': '颜色', 'type': 'color'},
        {'key': 'margin', 'label': '上下间距', 'type': 'select', 'options': [
            ['my-2', '小'], ['my-4', '中'], ['my-5', '大'],
        ]},
    ]


for _w in (Section, Container, GridRow, GridCol, Spacer, Divider):
    register_widget(_w)
