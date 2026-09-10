#!/usr/bin/env python3
"""CI 门禁：检查 app/ 与 plugins/ 中是否新增了已收编常量的字面量。

v2.6.0 新增。已收编到 app/constants.py 的常量值（如 'published'、'whoosh'）
不应再以裸字面量形式出现在 Python 代码中——应通过常量类引用。

白名单（scripts/constants_whitelist.txt）列出不检查的文件/路径（如 UPGGRADE.md
中的文档引用、scripts/ 自身、迁移脚本中的历史数据等）。

用法：
    python scripts/check_constants.py          # 检查，有违规退出 1
    python scripts/check_constants.py --list   # 仅列出违规，不退出非零
"""
import re
import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'app'
PLUGINS = ROOT / 'plugins'

# 已收编到 constants.py 的字面量值及其对应的常量路径
GATE_PATTERNS = {
    # 工作流状态字面量
    r"""['"]published['"]""": 'constants.Workflow.STATUS_PUBLISHED',
    r"""['"]draft['"]""": 'constants.Workflow.STATUS_DRAFT',
    r"""['"]review['"]""": 'constants.Workflow.STATUS_REVIEW',
    r"""['"]archived['"]""": 'constants.Workflow.STATUS_ARCHIVED',
    # 搜索引擎名
    r"""['"]whoosh['"]""": 'constants.Search.ENGINE_WHOOSH',
    r"""['"]meilisearch['"]""": 'constants.Search.ENGINE_MEILI',
    # 上传白名单（多元素字面量列表/元组）
    r"""\('zip',\s*'tar\.gz',\s*'tgz'\)""": 'constants.Upload.THEME_EXTS',
    r"""\['jpg',\s*'jpeg',\s*'png',\s*'gif',\s*'webp'\]""": 'constants.Upload.IMAGE_EXTS',
    r"""\['doc',\s*'docx',\s*'xls',\s*'xlsx',\s*'pdf'\]""": 'constants.Upload.RESUME_EXTS',
    # 角色预设名
    r"""['"]super_admin['"]""": 'constants.Roles.SUPER_ADMIN',
    r"""['"]content_auditor['"]""": 'constants.Roles.CONTENT_AUDITOR',
    r"""['"]content_editor['"]""": 'constants.Roles.CONTENT_EDITOR',
    r"""['"]readonly_viewer['"]""": 'constants.Roles.READONLY_VIEWER',
}

# 豁免：这些文件/目录不检查（文档、迁移脚本、本脚本、constants.py 本身、
# workflow.py/rbac.py 的重导出行、setting.py 的种子数据）
WHITELIST_PATHS = {
    'app/constants.py',           # 定义处
    'app/models/workflow.py',     # 重导出
    'app/models/rbac.py',         # 重导出
    'app/models/setting.py',      # 种子数据中的 key/value
    'app/admin/setting.py',       # 设置页白名单校验
    'scripts/check_constants.py',
}

# 按目录豁免（这些目录下的文件整体跳过）
WHITELIST_DIRS = {
    'migrations',      # 迁移脚本含历史数据
    '.trae',
    '.git',
    'instance',
    '__pycache__',
}


def _is_whitelisted(rel_path):
    """检查文件是否在白名单中。"""
    for d in WHITELIST_DIRS:
        if rel_path.startswith(d + '/'):
            return True
    return rel_path in WHITELIST_PATHS


def _collect_py_files():
    """收集 app/ 和 plugins/ 下所有 .py 文件（排除 __pycache__）。"""
    files = []
    for base in (APP, PLUGINS):
        for p in base.rglob('*.py'):
            if '__pycache__' in str(p):
                continue
            rel = str(p.relative_to(ROOT))
            if _is_whitelisted(rel):
                continue
            files.append(p)
    return files


def check():
    """执行检查，返回违规列表。"""
    violations = []
    for fpath in _collect_py_files():
        rel = str(fpath.relative_to(ROOT))
        try:
            content = fpath.read_text(encoding='utf-8')
        except Exception:
            continue
        for pat, const_ref in GATE_PATTERNS.items():
            for m in re.finditer(pat, content):
                line_no = content[:m.start()].count('\n') + 1
                line = content.split('\n')[line_no - 1].strip()
                # 跳过注释行
                if line.startswith('#'):
                    continue
                violations.append({
                    'file': rel,
                    'line': line_no,
                    'match': m.group(),
                    'should_use': const_ref,
                    'code': line,
                })
    return violations


if __name__ == '__main__':
    list_only = '--list' in sys.argv
    viols = check()
    if not viols:
        print('[check_constants] OK - 无违规字面量')
        sys.exit(0)

    print(f'[check_constants] 发现 {len(viols)} 处违规：\n')
    for v in viols:
        print(f"  {v['file']}:{v['line']}")
        print(f"    匹配: {v['match']}")
        print(f"    建议: 使用 {v['should_use']}")
        print(f"    代码: {v['code']}")
        print()

    if not list_only:
        sys.exit(1)
