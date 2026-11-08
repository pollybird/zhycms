"""插件包静态安全审计（v3.1.8，GitCode issue #12 VULN-002 / VULN-009）。

插件经 ``importlib.import_module`` 加载即获得完整进程权限，无法在加载期拦截
代码执行，因此上传期必须做静态内容审计。

v3.1.8 二次加固：由字符串黑名单升级为 **AST 语法树分析**，杜绝
``from os import system`` / ``importlib.import_module("os").system`` /
``getattr(os, 'sys'+'tem')`` 等字符串变体绕过：

v3.1.9（GitCode issue #14 VULN-022）：增加 **别名映射 + 赋值传播**，封堵
间接引用绕过（两遍 AST 分析）：

- ``import os as x; x.system("id")``
- ``from os import system as s; s("id")``
- ``x = os.system; x("id")`` / ``y = x; y("id")``
- ``getattr(os, "system")("id")``

原有规则不变：

- import 白名单语义：``subprocess``/``importlib``/``ctypes``/``pty`` 等
  高危模块整体禁止；``from os import system/popen/spawn*/exec*`` 等按名禁止；
- 调用分析：``os.system``/``subprocess.*``/``eval``/``exec``/``__import__``/
  ``compile`` 等按解析后的限定名匹配；
- dunder 属性访问整体禁止（``x.__globals__`` 等内省链）；
- ``getattr(obj, name)`` 的 name 必须是非 dunder 字符串字面量
  （动态属性名无法静态验证，宁可拒传）。

作用域说明：别名/赋值分析不区分作用域（宁可误报，不做完整符号表）。

说明：审计仅作用于后台上传的第三方插件包；仓库内预装官方插件
（如 oss_storage 使用 importlib 按需加载 SDK）不经过本审计。
"""
import ast
import os

# 整体禁止导入的模块（顶级包名匹配）。
# sys：sys.modules['os'] 可绕过 import 白名单；builtins：内置函数任意触达；
# operator：attrgetter/itemgetter 可用字符串参数构造属性访问链。
_BANNED_MODULES = frozenset({
    'subprocess', 'importlib', 'ctypes', 'pty', 'multiprocessing',
    'socketserver', 'xmlrpc', 'sys', 'builtins', 'operator',
})

# from os import <name> 按名禁止（os 本身用于 os.path 等，不整体禁止）
_BANNED_OS_NAMES = frozenset({
    'system', 'popen', 'popen2', 'popen3', 'popen4',
    'spawnl', 'spawnle', 'spawnlp', 'spawnlpe', 'spawnv', 'spawnve',
    'spawnvp', 'spawnvpe', 'execl', 'execle', 'execlp', 'execlpe',
    'execv', 'execve', 'execvp', 'execvpe', 'fork', 'forkpty',
    'kill', 'killpg', 'posix_spawn', 'posix_spawnp',
})

# 禁止调用的限定名（os.xxx 形式）
_BANNED_OS_CALLS = frozenset({'os.' + n for n in _BANNED_OS_NAMES})

# 禁止调用的裸名（内置动态执行）
_BANNED_BARE_CALLS = frozenset({
    'eval', 'exec', '__import__', 'compile', 'breakpoint',
    'globals', 'vars', 'exit', 'quit',
})

# getattr 作用于 os 模块时额外禁止的属性名（结合 _BANNED_OS_NAMES）
_BANNED_GETATTR_OS_ATTRS = frozenset(_BANNED_OS_NAMES | {'remove', 'unlink', 'rmdir'})

# 赋值传播的最大迭代轮数（3 轮足以覆盖常见链式别名）
_MAX_PROPAGATION_ROUNDS = 3

# 禁止访问的 dunder 属性（精确名单，不误伤 self.__private 私有属性）
_BANNED_DUNDER_ATTRS = frozenset({
    '__globals__', '__builtins__', '__class__', '__mro__', '__subclasses__',
    '__bases__', '__base__', '__code__', '__closure__', '__func__',
    '__func_globals__', '__gi_frame__', '__gi_code__', '__cr_frame__',
    '__cr_code__', '__dict__', '__import__', '__loader__', '__spec__',
    '__call__', '__get__', '__getattribute__', '__init_subclass__',
    '__set_name__', '__reduce__', '__reduce_ex__', '__getattr__',
})


def _qualified_name(node):
    """把 ast.Call 的 func 解析为 'a.b.c' 限定名（仅 Name/Attribute 链）。"""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        parts.reverse()
        return '.'.join(parts)
    return None


def _resolve_qualified(qname, bindings):
    """把限定名首段按别名/赋值映射还原为真实模块名。"""
    if not qname:
        return qname
    head, sep, rest = qname.partition('.')
    base = bindings.get(head, head)
    return base + sep + rest if sep else base


def _collect_bindings(tree):
    """Pass 1：收集 import 别名与赋值传播映射（作用域不敏感）。

    不区分作用域、不做完整符号表：宁可误报，不可漏过。
    """
    bindings = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bindings[alias.asname] = alias.name
                else:
                    top = alias.name.split('.')[0]
                    bindings[top] = top
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            for alias in node.names:
                if alias.name == '*':
                    continue
                local = alias.asname or alias.name
                bindings[local] = (module + '.' + alias.name) if module else alias.name

    # 赋值传播：x = os / x = os.system / y = x，迭代至稳定
    assignments = [
        (node.targets[0].id, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ]
    for _ in range(_MAX_PROPAGATION_ROUNDS):
        changed = False
        for name, value in assignments:
            qname = _resolve_qualified(_qualified_name(value), bindings)
            if qname and bindings.get(name) != qname:
                bindings[name] = qname
                changed = True
        if not changed:
            break
    return bindings


def _audit_node(node, bindings):
    """检查单个 AST 节点（基于别名/赋值映射还原），返回违规原因或 None。"""
    if isinstance(node, ast.Import):
        for alias in node.names:
            top = alias.name.split('.')[0]
            if top in _BANNED_MODULES:
                return "禁止导入高危模块 '{0}'".format(alias.name)
    elif isinstance(node, ast.ImportFrom):
        top = (node.module or '').split('.')[0]
        if top in _BANNED_MODULES:
            return "禁止从高危模块导入 '{0}'".format(node.module)
        if top == 'os':
            for alias in node.names:
                if alias.name in _BANNED_OS_NAMES:
                    return "禁止从 os 导入 '{0}'".format(alias.name)
    elif isinstance(node, ast.Attribute):
        if node.attr in _BANNED_DUNDER_ATTRS:
            return "禁止访问双下划线属性 '{0}'（内省链）".format(node.attr)
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            name = _resolve_qualified(node.func.id, bindings)
            if name in _BANNED_BARE_CALLS:
                return "禁止调用 '{0}()'".format(name)
            if name == 'getattr':
                # getattr(obj, name)：name 必须是非 dunder 字符串字面量
                if len(node.args) >= 2:
                    arg = node.args[1]
                    if not (isinstance(arg, ast.Constant)
                            and isinstance(arg.value, str)):
                        return '禁止动态属性名的 getattr 调用（无法静态验证）'
                    if arg.value.startswith('__'):
                        return "禁止 getattr 访问双下划线属性 '{0}'".format(arg.value)
                    # 对 os 模块取危险方法：getattr(os, "system")("id")
                    target = _resolve_qualified(
                        _qualified_name(node.args[0]), bindings)
                    if target == 'os' and arg.value in _BANNED_GETATTR_OS_ATTRS:
                        return "禁止 getattr 获取 os 的危险方法 '{0}'".format(arg.value)
        qname = _resolve_qualified(_qualified_name(node.func), bindings)
        if qname:
            if qname in _BANNED_OS_CALLS:
                return "禁止调用 '{0}()'".format(qname)
            if qname.split('.')[0] in ('subprocess', 'importlib'):
                return "禁止调用 '{0}()'".format(qname)
    return None


def audit_python_source(content, filename='<source>'):
    """审计单个 Python 源码内容（AST 两遍分析）。返回 (ok, reason)。"""
    if not content:
        return True, ''
    try:
        tree = ast.parse(content, filename=filename)
    except (SyntaxError, ValueError) as e:
        # 语法错误源码无法静态验证，宁可拒传
        return False, '源码解析失败（可能含混淆或非 py3 语法）：{0}'.format(e)
    bindings = _collect_bindings(tree)
    for node in ast.walk(tree):
        reason = _audit_node(node, bindings)
        if reason:
            return False, reason
    return True, ''


def audit_plugin_package(root):
    """递归审计插件包目录下全部 .py 文件。

    返回 (ok, violations)；violations 为 [(相对路径, 原因), ...]。
    读取失败的文件按违规处理（宁可拒传，不放过不可读源码）。
    """
    violations = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.lower().endswith('.py'):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except OSError as e:
                violations.append((rel, '源码读取失败：{0}'.format(e)))
                continue
            ok, reason = audit_python_source(content, filename=rel)
            if not ok:
                violations.append((rel, reason))
    return (not violations), violations
