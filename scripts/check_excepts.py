"""CI 门禁：检查 app/ 与 plugins/ 中未留痕的通用异常捕获。

v3.1.6 新增。规则：``except Exception`` / ``except BaseException`` / 裸
``except:`` 的处理器体内（自 except 行起 8 行内）必须出现留痕关键字
（logger / logging / raise / flash / abort / jsonify），否则视为静默吞噬。

白名单（scripts/excepts_whitelist.txt）逐行 ``文件:行号:理由``，用于已审定的
显式处理（返回错误信息、rollback 守卫、预期分支等）。

用法：
    python scripts/check_excepts.py          # 检查，有违规退出 1
    python scripts/check_excepts.py --list   # 仅列出违规，不退出非零
"""
import ast
import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ('app', 'plugins')
WHITELIST_FILE = ROOT / 'scripts' / 'excepts_whitelist.txt'

# 处理器体内的留痕/显式处理关键字
SIGNALS = ('logger', 'logging', 'raise', 'flash', 'abort', 'jsonify')

# 自 except 行起检查的窗口行数（含 except 行本身）
LOOKAHEAD_LINES = 8


def _load_whitelist():
    """加载白名单：{(相对路径, 行号): 理由}。"""
    entries = {}
    if not WHITELIST_FILE.is_file():
        return entries
    for raw in WHITELIST_FILE.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(':', 2)
        if len(parts) < 2:
            print(f'警告：白名单格式不合法，已忽略：{line}', file=sys.stderr)
            continue
        try:
            lineno = int(parts[1])
        except ValueError:
            print(f'警告：白名单行号不合法，已忽略：{line}', file=sys.stderr)
            continue
        reason = parts[2].strip() if len(parts) > 2 else ''
        entries[(parts[0].strip(), lineno)] = reason
    return entries


def _collect_py_files():
    """收集 app/ 与 plugins/ 下所有 .py 文件（排除 __pycache__）。"""
    files = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob('*.py'):
            if '__pycache__' in str(p):
                continue
            files.append(p)
    return files


def _is_generic(handler):
    """是否为通用异常捕获：裸 except、Exception、BaseException。"""
    if handler.type is None:
        return True
    return (isinstance(handler.type, ast.Name)
            and handler.type.id in ('Exception', 'BaseException'))


def check():
    """执行检查，返回违规列表。"""
    whitelist = _load_whitelist()
    violations = []
    for fpath in _collect_py_files():
        rel = str(fpath.relative_to(ROOT)).replace('\\', '/')
        try:
            content = fpath.read_text(encoding='utf-8')
        except Exception as e:
            print(f'警告：无法读取 {rel}，已跳过：{e}', file=sys.stderr)
            continue
        try:
            tree = ast.parse(content, filename=rel)
        except SyntaxError as e:
            print(f'警告：{rel} 语法解析失败，已跳过：{e}', file=sys.stderr)
            continue
        lines = content.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or not _is_generic(node):
                continue
            start = node.lineno - 1
            window = '\n'.join(lines[start:start + LOOKAHEAD_LINES])
            if any(sig in window for sig in SIGNALS):
                continue
            if (rel, node.lineno) in whitelist:
                continue
            code = lines[start].strip() if 0 <= start < len(lines) else ''
            violations.append({
                'file': rel,
                'line': node.lineno,
                'code': code,
            })
    return violations


if __name__ == '__main__':
    list_only = '--list' in sys.argv
    viols = check()
    if not viols:
        print('[check_excepts] OK - 所有通用异常捕获均已留痕或列入白名单')
        sys.exit(0)

    print(f'[check_excepts] 发现 {len(viols)} 处未留痕的通用异常捕获：\n')
    for v in viols:
        print(f"  {v['file']}:{v['line']}")
        print(f"    代码: {v['code']}")
        print('    建议: 收窄为具体异常，或补 logger.warning 留痕，'
              '或加入 scripts/excepts_whitelist.txt')
        print()

    if not list_only:
        sys.exit(1)
