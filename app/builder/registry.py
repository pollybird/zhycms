"""组件注册表：核心组件与插件组件统一登记、按启用状态门控。

组件（Widget）是构建器的最小渲染单元：
  - 元数据：type/category/label/icon/scopes/allowed_children
  - default_props：新建设备的默认属性
  - prop_schema：属性面板表单描述（编辑器据此自动生成表单）
  - context(node, page_ctx)：渲染前取数（文章列表、碎片等动态数据）
  - 模板：themes/<主题>/builder/widgets/<type>.html 覆写，
          否则回退 builder/widgets/<type>.html（含插件模板目录）

插件通过 PluginBase.get_builder_widgets() 在启动期注册，owner=插件 slug；
运行时插件被禁用，其组件在编辑器标灰、前台拒绝渲染（空占位）。
"""
from ..constants import Builder as _B

# type -> {'widget': Widget 实例, 'owner': 'core' 或插件 slug}
_registry = {}

# 属性表单字段允许的类型（编辑器与 schema 校验共用）
PROP_FIELD_TYPES = {
    'text', 'textarea', 'richtext', 'number', 'select', 'toggle',
    'color', 'image', 'icon', 'url', 'column', 'repeater', 'fragment',
}

# repeater 子字段允许的简单类型
REPEATER_FIELD_TYPES = {
    'text', 'textarea', 'number', 'select', 'toggle', 'color',
    'image', 'icon', 'url',
}


class Widget:
    """组件基类：子类用类属性声明元数据，按需覆写 context()。"""

    type = ''
    category = _B.CAT_BASIC
    label = ''
    icon = 'fa-puzzle-piece'
    description = ''

    # 可放置的页面作用域；默认四种均可
    scopes = _B.SCOPES
    # 允许的子组件类型：空 tuple=叶子；'*' 或 ('*',)=任意；
    # 也可写具体 type 元组，如 ('grid-col',)
    allowed_children = ()
    # 子项默认数量（grid-row 新建时自动补几个 col 等）
    default_children = 0

    default_props = {}
    # 属性表单：[{key,label,type,options?,default?,localized?,help?,fields?(repeater)}]
    prop_schema = []

    def context(self, node, page_ctx):
        """渲染前取数，返回追加进组件模板上下文的 dict。"""
        return {}

    # ---- 供模板使用的便捷方法 ----

    @staticmethod
    def prop(node, key, default=None):
        return (node.get('props') or {}).get(key, default)

    @staticmethod
    def localized(node, key, locale, default=''):
        """取本地化文案：props.key 为字符串时所有语言通用；
        为 {locale: text} 时按当前 locale 取并回退默认语言/任意值。"""
        val = (node.get('props') or {}).get(key, default)
        if isinstance(val, dict):
            if locale in val and val[locale]:
                return val[locale]
            # 回退：默认语言 → 第一个非空
            from ..constants import Locales
            if val.get(Locales.DEFAULT):
                return val[Locales.DEFAULT]
            for v in val.values():
                if v:
                    return v
            return default
        return val if val is not None else default


def register_widget(widget_cls, owner='core'):
    """注册组件类（实例化后登记）。同名组件后注册者覆盖，
    允许插件以同 type 提供替代实现。"""
    inst = widget_cls if isinstance(widget_cls, Widget) else widget_cls()
    if not getattr(inst, 'type', ''):
        raise ValueError('构建器组件缺少 type 标识')
    _registry[inst.type] = {'widget': inst, 'owner': owner}
    return inst


def unregister_owner(owner):
    """卸载插件时移除其贡献的全部组件。"""
    for t in [k for k, v in _registry.items() if v['owner'] == owner]:
        _registry.pop(t, None)


def _owner_enabled(owner):
    if owner == 'core':
        return True
    try:
        from ..plugin_system import plugin_enabled
        return plugin_enabled(owner)
    except Exception:
        return False


def get_widget(widget_type, include_disabled=False):
    """返回组件实例；插件禁用默认返回 None。"""
    rec = _registry.get(widget_type)
    if rec is None:
        return None
    if not include_disabled and not _owner_enabled(rec['owner']):
        return None
    return rec['widget']


def widget_owner(widget_type):
    rec = _registry.get(widget_type)
    return rec['owner'] if rec else None


def available_widget_types():
    """当前请求下可渲染的组件类型集合（插件门控后）。"""
    return {t for t, rec in _registry.items() if _owner_enabled(rec['owner'])}


def core_widget_count():
    return sum(1 for rec in _registry.values() if rec['owner'] == 'core')


def widget_catalog(scope=None):
    """编辑器组件目录数据（含禁用插件组件标灰）。

    返回 {category: [{'type','label','icon','description','owner',
                      'enabled','default_props','prop_schema',
                      'allowed_children','default_children'}, ...]}
    """
    groups = {code: [] for code, _label in _B.CATEGORIES}
    for t, rec in sorted(_registry.items(), key=lambda kv: kv[0]):
        w = rec['widget']
        if scope and scope not in w.scopes:
            continue
        groups.setdefault(w.category, []).append({
            'type': w.type,
            'label': w.label,
            'icon': w.icon,
            'description': w.description,
            'owner': rec['owner'],
            'enabled': _owner_enabled(rec['owner']),
            'default_props': w.default_props,
            'prop_schema': w.prop_schema,
            'allowed_children': list(w.allowed_children),
            'default_children': w.default_children,
        })
    return groups
