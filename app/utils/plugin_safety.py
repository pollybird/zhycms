"""插件包静态安全审计（v3.1.8，GitCode issue #12 VULN-002 / VULN-009）。

插件经 ``importlib.import_module`` 加载即获得完整进程权限，无法在加载期拦截
代码执行，因此上传期必须做静态内容审计：扫描包内全部 ``.py`` 文件，拒绝含
高危系统调用/动态执行标识的插件包。

规则来源：v3.1.8 安全计划步骤 0 已对仓库内全部官方插件扫描，候选规则零命中，
官方插件不受本审计影响。已在磁盘上的存量插件不重新审计。
"""
import os

# 高危调用标识符（命令执行 / 动态导入 / 动态求值）
_DANGEROUS_PATTERNS = (
    'subprocess.Popen', 'subprocess.call', 'subprocess.run',
    'subprocess.check_output', 'os.system', 'os.popen',
    '__import__', 'eval(', 'exec(',
)


def audit_python_source(content):
    """审计单个 Python 源码内容。返回 (ok, reason)。"""
    if not content:
        return True, ''
    for pat in _DANGEROUS_PATTERNS:
        if pat in content:
            return False, "包含高危调用 '{0}'".format(pat)
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
            ok, reason = audit_python_source(content)
            if not ok:
                violations.append((rel, reason))
    return (not violations), violations
