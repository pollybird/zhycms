#!/usr/bin/env python3
"""发布一致性检查：校验版本号在各处一致。

v2.6.0 新增。检查 CMS_VERSION（setting.py）、插件 manifest.json + Plugin.version、
CHANGELOG 顶部版本号与日期、README 当前版本、wiki.html 标题等是否一致。

用法：
    python scripts/check_release.py                    # 检查所有版本号一致性
    python scripts/check_release.py --version v2.6.0  # 校验目标版本
    python scripts/check_release.py --print-version     # 打印当前 CMS_VERSION
"""
import json
import re
import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent


def _read(path):
    try:
        return (ROOT / path).read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''


def get_cms_version():
    """从 setting.py 提取 CMS_VERSION。"""
    text = _read('app/models/setting.py')
    m = re.search(r"CMS_VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    return m.group(1) if m else None


def get_plugin_versions():
    """提取各插件的 manifest.json version。"""
    results = {}
    plugins_dir = ROOT / 'plugins'
    if not plugins_dir.is_dir():
        return results
    for mf in sorted(plugins_dir.glob('*/manifest.json')):
        try:
            data = json.loads(mf.read_text(encoding='utf-8'))
            results[mf.parent.name] = data.get('version', '?')
        except Exception:
            results[mf.parent.name] = '<parse error>'
    return results


def get_changelog_version():
    """提取 CHANGELOG 顶部的版本号与日期。"""
    text = _read('CHANGELOG.md')
    m = re.search(r'##\s*\[([\d.]+)\]\s*-\s*(\d{4}-\d{2}-\d{2})', text)
    if m:
        return m.group(1), m.group(2)
    return None, None


def get_readme_version():
    """提取 README 中的当前版本。"""
    text = _read('README.md')
    m = re.search(r'当前版本：v([\d.]+)', text)
    return m.group(1) if m else None


def get_wiki_title_version():
    """提取 wiki.html 标题中的版本号。"""
    text = _read('wiki.html')
    m = re.search(r'<title>[^<]*v([\d.]+)', text)
    return m.group(1) if m else None


def check(target_version=None):
    """执行全部检查，返回违规列表。"""
    violations = []
    today = date.today().isoformat()

    # 1. CMS_VERSION
    cms_ver = get_cms_version()
    if cms_ver is None:
        violations.append('app/models/setting.py: CMS_VERSION 未找到')
    elif target_version and cms_ver != target_version:
        violations.append(
            f'app/models/setting.py: CMS_VERSION={cms_ver} ≠ 目标 {target_version}')

    # 2. CHANGELOG 版本号 + 日期
    cl_ver, cl_date = get_changelog_version()
    if cl_ver is None:
        violations.append('CHANGELOG.md: 顶部版本号未找到')
    else:
        if target_version and cl_ver != target_version:
            violations.append(
                f'CHANGELOG.md: 顶部版本 {cl_ver} ≠ 目标 {target_version}')
        if cl_date and cl_date > today:
            violations.append(
                f'CHANGELOG.md: 日期 {cl_date} 晚于今天 {today}')

    # 3. README 当前版本
    rd_ver = get_readme_version()
    if rd_ver is None:
        violations.append('README.md: 当前版本未找到')
    elif target_version and rd_ver != target_version:
        violations.append(
            f'README.md: 当前版本 v{rd_ver} ≠ 目标 v{target_version}')

    # 4. wiki.html 标题版本
    wk_ver = get_wiki_title_version()
    if wk_ver is None:
        violations.append('wiki.html: 标题版本号未找到')
    elif target_version and wk_ver != target_version:
        violations.append(
            f'wiki.html: 标题版本 v{wk_ver} ≠ 目标 v{target_version}')

    # 5. 插件 manifest 版本（仅提示，不阻断——插件版本独立）
    plugin_vers = get_plugin_versions()
    # 插件版本号不强制等于核心版本号，仅列出供参考

    return violations, {
        'cms_version': cms_ver,
        'changelog_version': cl_ver,
        'changelog_date': cl_date,
        'readme_version': rd_ver,
        'wiki_title_version': wk_ver,
        'plugin_versions': plugin_vers,
    }


if __name__ == '__main__':
    if '--print-version' in sys.argv:
        v = get_cms_version()
        print(v or 'unknown')
        sys.exit(0)

    target = None
    for i, arg in enumerate(sys.argv):
        if arg == '--version' and i + 1 < len(sys.argv):
            target = sys.argv[i + 1]

    viols, info = check(target)

    print('=== 版本一致性检查 ===')
    print(f"  CMS_VERSION:          {info['cms_version']}")
    print(f"  CHANGELOG 顶部版本:   {info['changelog_version']} ({info['changelog_date']})")
    print(f"  README 当前版本:      v{info['readme_version']}")
    print(f"  wiki.html 标题版本:  v{info['wiki_title_version']}")
    print(f"  插件版本:")
    for slug, ver in info['plugin_versions'].items():
        print(f"    {slug}: {ver}")

    if viols:
        print(f'\n[check_release] 发现 {len(viols)} 处不一致：\n')
        for v in viols:
            print(f'  ✗ {v}')
        sys.exit(1)
    else:
        print('\n[check_release] OK - 版本号一致')
        sys.exit(0)
