"""布局 JSON 校验与规整。

安全红线：
  - 组件类型必须在注册表中（插件禁用时保存草稿仍允许，但渲染时跳过）
  - 递归深度 / 节点数 / 文档体积三重上限
  - props 仅允许白名单键（按组件 prop_schema），值类型做基本约束
  - 不接受可执行表达式；富文本由服务端页面同样的 CKEditor 信任模型处理
"""
import json

from ..constants import Builder as _B
from ..constants import Locales


class LayoutError(ValueError):
    """布局文档非法。"""


def _new_id():
    """生成短节点 id（n_ + 6 位十六进制）。碰撞由调用场景极低概率兜底。"""
    import uuid
    return 'n_' + uuid.uuid4().hex[:8]


def validate_layout(layout, check_widgets=True):
    """校验布局文档。成功返回规整后的 dict，失败抛 LayoutError。

    :param check_widgets: 是否校验组件类型已注册（保存来自插件的草稿时
        仍要求已安装；仅渲染已发布布局时对禁用插件组件放行跳过）
    """
    if not isinstance(layout, dict):
        raise LayoutError('布局必须是 JSON 对象')
    root = layout.get('root')
    if not isinstance(root, list):
        raise LayoutError('布局缺少 root 数组')

    payload = json.dumps(layout, ensure_ascii=False).encode('utf-8')
    if len(payload) > _B.MAX_PAYLOAD_BYTES:
        raise LayoutError(
            f'布局文档超过 {_B.MAX_PAYLOAD_BYTES // 1024}KB 上限'
        )

    valid_types = None
    if check_widgets:
        from .registry import _registry
        valid_types = set(_registry.keys())

    count = 0

    def walk(node, depth, allowed):
        nonlocal count
        count += 1
        if count > _B.MAX_NODES:
            raise LayoutError(f'单页节点数超过 {_B.MAX_NODES} 上限')
        if depth > _B.MAX_DEPTH:
            raise LayoutError(f'嵌套深度超过 {_B.MAX_DEPTH} 层上限')
        if not isinstance(node, dict):
            raise LayoutError('节点必须是对象')
        ntype = node.get('type')
        if not isinstance(ntype, str) or not ntype:
            raise LayoutError('节点缺少 type')
        if valid_types is not None and ntype not in valid_types:
            raise LayoutError(f'未知组件类型：{ntype}')
        if not isinstance(node.get('id'), str) or not node['id']:
            raise LayoutError(f'组件 {ntype} 缺少 id')
        props = node.get('props')
        if props is not None and not isinstance(props, dict):
            raise LayoutError(f'组件 {ntype} 的 props 必须是对象')
        vis = node.get('visibility')
        if vis is not None:
            if not isinstance(vis, dict):
                raise LayoutError(f'组件 {ntype} 的 visibility 必须是对象')
            locs = vis.get('locales')
            if locs is not None:
                if not isinstance(locs, list) or any(
                        not isinstance(x, str) for x in locs):
                    raise LayoutError(f'组件 {ntype} 的 visibility.locales 非法')
        children = node.get('children')
        if children is None:
            node['children'] = []
        elif not isinstance(children, list):
            raise LayoutError(f'组件 {ntype} 的 children 必须是数组')

        # 父子类型约束（注册表情景）
        if valid_types is not None and ntype in valid_types:
            from .registry import _registry
            widget = _registry[ntype]['widget']
            if not widget.allowed_children and node['children']:
                raise LayoutError(f'组件 {ntype} 不允许放置子组件')
            if widget.allowed_children and '*' not in widget.allowed_children:
                for child in node['children']:
                    if isinstance(child, dict) and child.get('type') \
                            not in widget.allowed_children:
                        raise LayoutError(
                            f'组件 {ntype} 内不允许放置 {child.get("type")}'
                        )
            _check_props(ntype, props or {}, widget)

        for child in node['children']:
            walk(child, depth + 1, None)

    for node in root:
        walk(node, 1, None)

    layout['version'] = _B.SCHEMA_VERSION
    return layout


def _check_props(ntype, props, widget):
    allowed = {f['key'] for f in widget.prop_schema}
    for key in props:
        if key not in allowed:
            raise LayoutError(f'组件 {ntype} 不支持属性 {key}')
    for field in widget.prop_schema:
        key = field['key']
        if key not in props:
            continue
        val = props[key]
        ftype = field.get('type', 'text')
        if ftype == 'number':
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise LayoutError(f'组件 {ntype}.{key} 必须是数字')
        elif ftype == 'toggle':
            if not isinstance(val, bool):
                raise LayoutError(f'组件 {ntype}.{key} 必须是布尔值')
        elif ftype == 'select':
            options = {str(o[0]) if isinstance(o, (list, tuple)) else str(o)
                       for o in field.get('options', [])}
            if options and str(val) not in options:
                raise LayoutError(f'组件 {ntype}.{key} 取值非法')
        elif ftype == 'repeater':
            if not isinstance(val, list):
                raise LayoutError(f'组件 {ntype}.{key} 必须是数组')
            sub_keys = {f['key'] for f in field.get('fields', [])}
            for item in val:
                if not isinstance(item, dict):
                    raise LayoutError(f'组件 {ntype}.{key} 子项必须是对象')
                for sk in item:
                    if sk not in sub_keys:
                        raise LayoutError(
                            f'组件 {ntype}.{key} 含非法子字段 {sk}')
        elif ftype in ('image', 'url', 'fragment'):
            if not isinstance(val, str):
                raise LayoutError(f'组件 {ntype}.{key} 必须是字符串')
        elif ftype in ('text', 'textarea', 'richtext', 'color', 'icon'):
            if not isinstance(val, (str, dict)):
                raise LayoutError(f'组件 {ntype}.{key} 必须是字符串或多语言对象')
            if isinstance(val, dict):
                for lk, lv in val.items():
                    if lk not in Locales.ALL or not isinstance(lv, str):
                        raise LayoutError(
                            f'组件 {ntype}.{key} 多语言格式非法')


def normalize_layout(layout):
    """宽松规整（用于容错读取历史/外部数据）：剔除非 dict 节点。"""
    if not isinstance(layout, dict):
        return {'version': _B.SCHEMA_VERSION, 'root': []}
    root = layout.get('root')
    if not isinstance(root, list):
        return {'version': _B.SCHEMA_VERSION, 'root': []}

    def clean(node):
        if not isinstance(node, dict) or not node.get('type'):
            return None
        node.setdefault('id', _new_id())
        node.setdefault('props', {})
        node.setdefault('visibility', {})
        children = node.get('children')
        if isinstance(children, list):
            node['children'] = [c for c in (clean(x) for x in children) if c]
        else:
            node['children'] = []
        return node

    cleaned = [n for n in (clean(x) for x in root) if n]
    return {'version': _B.SCHEMA_VERSION, 'root': cleaned}


def loads_layout(raw):
    """解析 JSON 字符串为布局 dict（非法 JSON 抛 LayoutError）。"""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {'version': _B.SCHEMA_VERSION, 'root': []}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as e:
        raise LayoutError(f'布局 JSON 解析失败：{e}')
    return data


def dumps_layout(layout):
    return json.dumps(layout, ensure_ascii=False)


def new_node(widget_type, overrides=None):
    """按组件默认值构造一个新节点。"""
    from .registry import get_widget
    widget = get_widget(widget_type, include_disabled=True)
    if widget is None:
        raise LayoutError(f'未知组件类型：{widget_type}')
    node = {
        'id': _new_id(),
        'type': widget_type,
        'props': dict(widget.default_props or {}),
        'visibility': {},
        'children': [],
    }
    # 默认子组件（如 grid-row 自动补 grid-col）
    if widget.default_children:
        allowed = [t for t in widget.allowed_children if t != '*']
        for i in range(widget.default_children):
            child_type = allowed[0] if allowed else None
            if child_type:
                node['children'].append(new_node(child_type))
    if overrides:
        node['props'].update(overrides.pop('props', {}) or {})
        node.update(overrides)
    return node


def iter_nodes(nodes):
    """深度优先遍历节点。"""
    for node in nodes:
        yield node
        yield from iter_nodes(node.get('children') or [])


def find_node(nodes, node_id):
    for node in nodes:
        if node.get('id') == node_id:
            return node
        found = find_node(node.get('children') or [], node_id)
        if found:
            return found
    return None


def find_parent(nodes, node_id, parent=None):
    for node in nodes:
        if node.get('id') == node_id:
            return parent, node
        found = find_parent(node.get('children') or [], node_id, node)
        if found[1] is not None:
            return found
    return None, None
