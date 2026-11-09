"""主题模板静态安全审计（v3.1.8，GitCode issue #12 VULN-001）。

主题包上传时对全部 ``.html`` 模板做危险标识符扫描，与构建器运行时
``jinja2.sandbox.SandboxedEnvironment`` 构成纵深防御：
  - 上传期：本模块拦截含 SSTI 内省/危险调用标识的模板，拒绝落盘；
  - 运行期：构建器渲染链强制沙箱，阻断 ``__class__``/``__mro__`` 等访问。

规则来源：v3.1.8 安全计划步骤 0 已对仓库内全部官方主题扫描，候选规则零命中，
官方主题不受本审计影响。
"""
import os
import re

# 字面量危险标识符（SSTI 内省链 / 危险内置调用）
_LITERAL_PATTERNS = (
    '__class__', '__mro__', '__subclasses__', '__globals__', '__builtins__',
    '__import__', 'config[', 'getattr', 'subprocess', 'eval(', 'exec(',
)
# os. 模块访问（词边界，避免误伤 photos. / logos. 等正常文本）
_OS_ACCESS_RE = re.compile(r'\bos\.')
# Python 风格 import（排除 CSS @import 与词内嵌入）
_PY_IMPORT_RE = re.compile(r'(?<![\w@])import\s')

# --- v3.1.8 二次加固：表达式片段级规则（防拼接/变体绕过） ---
# 以下规则只对 {{ ... }} / {% ... %} 表达式片段生效，纯文本不误伤。

# 提取模板表达式片段
_EXPR_RE = re.compile(r'({{.*?}}|{%.*?%}|{#.*?#})', re.S)

# |attr 过滤器：名称参数运行时可拼接（'__cl'~'ass__'），经典沙箱绕过武器
_ATTR_FILTER_RE = re.compile(r'\|\s*attr\s*\(')
# config 任意引用（globals 已剔除，模板中出现的 config 只能是攻击载荷）
_CONFIG_RE = re.compile(r'\bconfig\b')
# Jinja 环境内部对象（cycler/joiner/namespace/lipsum 可触达环境内部状态）
_ENV_INTERNALS_RE = re.compile(r'\b(cycler|joiner|namespace|lipsum)\b')
# request 对象属性访问：仅放行模板实际使用的白名单属性，
# request.application / request.environ 等可直达应用实例与 config
_REQUEST_ATTR_RE = re.compile(r'\brequest\s*\.\s*([A-Za-z_]\w*)')
# request 下标访问：Jinja foo['bar'] 会回退 getattr，等价于属性访问
_REQUEST_GETITEM_RE = re.compile(r'\brequest\s*\[')
# 下标内字符串拼接（v3.1.10 VULN-023，Issue #14）：
# {{ ''['_'+'_class'+'__'] }} / {{ x['__gl'~'obals__'] }} 用拼接混淆属性名
# 绕过字面量审计（运行期沙箱已拦截，此为审计层纵深防御，不追求完备）。
_GETITEM_CONCAT_RE = re.compile(r"\[\s*(?:[^\]\[]*?['\"][^\]\[]*?)(?:~|\+)\s*['\"]")
_REQUEST_ALLOWED_ATTRS = frozenset({
    'path', 'full_path', 'args', 'view_args', 'endpoint', 'method',
    'url', 'base_url', 'url_root', 'root_url', 'script_root', 'host',
    'host_url', 'referrer', 'blueprint', 'query_string', 'path_info',
})

# 需审计的模板扩展名
_TEMPLATE_EXTS = ('.html', '.htm', '.j2', '.jinja', '.jinja2')


def _audit_expressions(content):
    """表达式片段级审计（v3.1.8 二次加固）。返回 (ok, reason)。"""
    for m in _EXPR_RE.finditer(content):
        expr = m.group(0)
        if _ATTR_FILTER_RE.search(expr):
            return False, "包含 '|attr' 过滤器（可拼接属性名绕过沙箱）"
        if _CONFIG_RE.search(expr):
            return False, "包含 'config' 引用（模板上下文不暴露应用配置）"
        if _ENV_INTERNALS_RE.search(expr):
            return False, "包含模板环境内部对象（cycler/joiner/namespace/lipsum）"
        if _REQUEST_GETITEM_RE.search(expr):
            return False, "包含 request 下标访问（可回退为属性访问绕过白名单）"
        if _GETITEM_CONCAT_RE.search(expr):
            return False, "包含下标内字符串拼接（疑似属性名混淆绕过审计）"
        for attr in _REQUEST_ATTR_RE.findall(expr):
            if attr not in _REQUEST_ALLOWED_ATTRS:
                return False, "包含白名单外的 request 属性访问 'request.{0}'".format(attr)
    return True, ''


def audit_template(content):
    """审计单个模板内容。返回 (ok, reason)，ok=False 时 reason 为命中说明。"""
    if not content:
        return True, ''
    for lit in _LITERAL_PATTERNS:
        if lit in content:
            return False, "包含危险标识符 '{0}'".format(lit)
    if _OS_ACCESS_RE.search(content):
        return False, "包含危险标识符 'os.'"
    if _PY_IMPORT_RE.search(content):
        return False, "包含危险标识符 'import'"
    return _audit_expressions(content)


def audit_theme_templates(root):
    """递归审计目录下全部模板文件。

    返回 (ok, violations)；violations 为 [(相对路径, 原因), ...]。
    读取失败的文件按违规处理（宁可拒传，不放过不可读模板）。
    """
    violations = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.lower().endswith(_TEMPLATE_EXTS):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except OSError as e:
                violations.append((rel, '模板读取失败：{0}'.format(e)))
                continue
            ok, reason = audit_template(content)
            if not ok:
                violations.append((rel, reason))
    return (not violations), violations
