"""插件对页面构建器「默认布局」的贡献（v3.0.0）。

插件除注册可拖拽组件（registry, owner=slug）外，还可以在包内提供
``builder/<scope>.json`` **布局片段**：用户新建构建页或在编辑器点
「默认布局」时，系统把基础布局（当前主题 fixture，缺省回退核心）与
当前**已启用**插件的片段做一次性快照合并。

片段文件（plugins/<slug>/builder/home.json）：

    {
      "version": 1,
      "position": "append",            // prepend | append（默认 append）
      "after": "n_home_cta",           // 可选：锚点（基础布局根节点 id），
                                       // 找不到时回退 position
      "root": [ <组件节点...> ]        // 与普通布局相同的节点数组
    }

设计约束：
  - 作用域仅 home/page/list/article，文件名即作用域，其余一律拒绝；
  - 片段在插件加载期登记（不论启用与否），启用时通过同一套
    validate_layout 校验（组件类型必须已注册），非法则拒绝启用；
  - 只在 init_default_layout 快照时合并，绝不改写用户已有草稿/已发布页；
  - 片段节点 id 建议带插件前缀（n_<slug>_*）；与基础布局撞 id 时
    自动加 owner 前缀重写，保证不覆盖、不串节点；
  - 单个片段合并失败只跳过该片段并记录日志，不阻断默认布局初始化。
"""
import copy
import json
import os

from ..constants import Builder as _B
from .schema import validate_layout, LayoutError

# scope -> 片段文件名（与主题 fixture 同名约定，但语义是「贡献片段」）
SCOPE_FILES = {
    _B.SCOPE_HOME: 'home.json',
    _B.SCOPE_PAGE: 'page.json',
    _B.SCOPE_LIST: 'list.json',
    _B.SCOPE_ARTICLE: 'article.json',
}
_POSITIONS = ('prepend', 'append')

# owner(slug) -> {scope: [fragment, ...]}
_owner_layouts = {}
# 加载期发现/解析失败的错误（启用时据此拦截）
_owner_errors = {}


# ============================================================
# 发现与注册
# ============================================================

def discover_package_layouts(package_dir):
    """扫描插件包内 builder/*.json，返回 {scope: [fragment]}。

    解析失败（坏 JSON / 非法文件名 / 结构错误）抛 ValueError，
    由注册流程登记为 owner 错误并在启用时拦截。
    """
    builder_dir = os.path.join(package_dir, 'builder')
    if not os.path.isdir(builder_dir):
        return {}
    result = {}
    for name in sorted(os.listdir(builder_dir)):
        fp = os.path.join(builder_dir, name)
        if not os.path.isfile(fp) or not name.endswith('.json'):
            continue
        scope = next((s for s, fname in SCOPE_FILES.items()
                      if fname == name), None)
        if scope is None:
            raise ValueError(
                f'builder/{name} 不被识别：插件布局片段仅允许 '
                'home.json / page.json / list.json / article.json')
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (ValueError, OSError) as e:
            raise ValueError(f'builder/{name} 不是合法 JSON：{e}')
        fragment = _normalize_fragment(data, name)
        result.setdefault(scope, []).append(fragment)
    return result


def _normalize_fragment(data, name):
    if not isinstance(data, dict):
        raise ValueError(f'builder/{name} 片段必须是 JSON 对象')
    root = data.get('root')
    if not isinstance(root, list) or not root:
        raise ValueError(f'builder/{name} 缺少非空 root 数组')
    position = data.get('position') or 'append'
    if position not in _POSITIONS:
        raise ValueError(
            f'builder/{name} 的 position 仅支持 prepend/append')
    after = data.get('after')
    if after is not None and (not isinstance(after, str) or not after.strip()):
        raise ValueError(f'builder/{name} 的 after 必须是非空字符串')
    return {
        'position': position,
        'after': (after or '').strip() or None,
        'root': root,
        'source': name,
    }


def register_owner_layouts(owner, layouts):
    """登记某插件的全部片段（同 owner 后注册覆盖，便于同进程重载）。

    入参片段既可以是 discover_package_layouts 的产物（已归一化），
    也可以是 get_builder_layouts 直接返回的原始 dict，这里统一过一遍
    归一化，结构非法时登记为 owner 错误（启用时拦截），不抛出。
    """
    clean = {}
    for scope, fragments in (layouts or {}).items():
        if scope not in SCOPE_FILES:
            continue
        norm = []
        for raw in (fragments or []):
            try:
                if isinstance(raw, dict) and raw.get('source') \
                        and isinstance(raw.get('root'), list):
                    norm.append(raw)  # 已归一化（发现期产物）
                else:
                    norm.append(_normalize_fragment(raw, SCOPE_FILES[scope]))
            except ValueError as e:
                register_owner_error(owner, str(e))
                return
        clean[scope] = norm
    _owner_layouts[owner] = clean
    _owner_errors.pop(owner, None)


def register_owner_error(owner, message):
    """登记发现/解析失败（启用校验时返回该错误）。"""
    _owner_errors[owner] = str(message)


def unregister_owner(owner):
    """卸载插件时清理其片段登记。"""
    _owner_layouts.pop(owner, None)
    _owner_errors.pop(owner, None)


def owner_scopes(owner):
    return sorted(_owner_layouts.get(owner, {}).keys())


# ============================================================
# 启用校验
# ============================================================

def validation_error(owner):
    """返回该插件片段的校验错误字符串；全部合法返回 None。

    与主题 builder fixture 同一套 validate_layout：组件类型必须已注册
    （插件组件在启动期已登记，禁用不影响注册表）、props 白名单、
    父子约束、节点数/深度上限全部生效。
    """
    if owner in _owner_errors:
        return _owner_errors[owner]
    for scope, fragments in _owner_layouts.get(owner, {}).items():
        for frag in fragments:
            try:
                validate_layout({'root': frag['root']})
            except LayoutError as e:
                return f"builder/{frag['source']} 布局片段校验失败：{e}"
    return None


# ============================================================
# 快照合并
# ============================================================

def _enabled_owners():
    try:
        from ..plugin_system import enabled_slugs
        return set(enabled_slugs())
    except Exception:
        return set()


def _collect_ids(nodes):
    ids = set()
    stack = list(nodes or [])
    while stack:
        n = stack.pop()
        if isinstance(n, dict):
            nid = n.get('id')
            if isinstance(nid, str):
                ids.add(nid)
            stack.extend(n.get('children') or [])
    return ids


def _rewrite_ids(nodes, taken, owner):
    """撞 id 时给片段节点加 owner 前缀；返回（新节点列表, 是否有改写）。"""
    cloned = copy.deepcopy(nodes)
    changed = False

    def walk(node):
        nonlocal changed
        if not isinstance(node, dict):
            return
        nid = node.get('id')
        if isinstance(nid, str) and nid in taken:
            node['id'] = f'n_{owner}__{nid}'
            changed = True
        for child in node.get('children') or []:
            walk(child)

    for n in cloned:
        walk(n)
    return cloned, changed


def compose_layout(base_layout, scope, enabled=None):
    """把已启用插件的片段合并进基础布局，返回新的布局 dict（不改入参）。

    合并顺序：prepend 片段（按 slug 倒序插入，保证 slug 升序展示）
    → 带锚点片段（按 slug 升序，锚点缺失回退 append 位）
    → append 片段（slug 升序）。
    任何片段异常都被隔离跳过，基础布局一定可用。
    """
    try:
        base = copy.deepcopy(base_layout) if isinstance(
            base_layout, dict) else {'version': _B.SCHEMA_VERSION, 'root': []}
        root = list(base.get('root') or [])
        if scope not in SCOPE_FILES:
            return base

        if enabled is None:
            enabled = _enabled_owners()
        enabled = set(enabled)
        # slug 升序：多插件同时贡献时插入顺序确定可预期
        owners = sorted(o for o in enabled
                        if _owner_layouts.get(o, {}).get(scope))
        if not owners:
            return base

        fragments = []  # (owner, fragment)
        for owner in owners:
            for frag in _owner_layouts[owner][scope]:
                fragments.append((owner, frag))

        prepends = [(o, f) for o, f in fragments
                    if f.get('position') == 'prepend']
        appends = [(o, f) for o, f in fragments
                   if f.get('position') != 'prepend' and not f.get('after')]
        anchored = [(o, f) for o, f in fragments if f.get('after')]

        taken = _collect_ids(root)

        def materialize(owner, frag):
            """深拷贝 + 撞 id 重写 + 单片段校验；失败返回 None。"""
            nodes, _changed = _rewrite_ids(frag['root'], taken, owner)
            try:
                validate_layout({'root': nodes})
            except LayoutError as e:
                _log_warning(owner, frag, f'片段已跳过：{e}')
                return None
            taken.update(_collect_ids(nodes))
            return nodes

        # 1) 锚点插入（锚点只在基础布局/已插入根节点中查找；找不到回退尾插）
        for owner, frag in anchored:
            nodes = materialize(owner, frag)
            if nodes is None:
                continue
            idx = next((i for i, n in enumerate(root)
                        if isinstance(n, dict)
                        and n.get('id') == frag.get('after')),
                       None)
            if idx is None:
                root.extend(nodes)
            else:
                root[idx + 1:idx + 1] = nodes

        # 2) 尾部追加（slug 升序）
        for owner, frag in appends:
            nodes = materialize(owner, frag)
            if nodes is not None:
                root.extend(nodes)

        # 3) 头部插入：逐条头插会逆序，故按 slug 倒序处理
        for owner, frag in reversed(prepends):
            nodes = materialize(owner, frag)
            if nodes is not None:
                root[0:0] = nodes

        base['root'] = root
        return base
    except Exception as e:  # 合并层绝不阻断初始化：退回基础布局
        try:
            from flask import current_app
            current_app.logger.warning('插件布局片段合并失败，已回退基础布局：%s', e)
        except Exception:
            pass
        return copy.deepcopy(base_layout)


def _log_warning(owner, frag, message):
    try:
        from flask import current_app
        current_app.logger.warning(
            '插件 %s 的 builder/%s %s', owner, frag.get('source'), message)
    except Exception:
        pass
