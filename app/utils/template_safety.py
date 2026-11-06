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

# 需审计的模板扩展名
_TEMPLATE_EXTS = ('.html', '.htm', '.j2', '.jinja', '.jinja2')


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
    return True, ''


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
