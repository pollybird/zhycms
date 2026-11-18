#!/usr/bin/env python3
"""审计内置插件是否适配站群作用域。

示例：
    python scripts/audit_plugins_site_scope.py
    python scripts/audit_plugins_site_scope.py --json
    python scripts/audit_plugins_site_scope.py --markdown
    python scripts/audit_plugins_site_scope.py --strict

退出码：0 = 全部适配或有豁免；2 = 存在未适配；--strict 时为 1。
"""
import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.utils.plugin_site_scope import (  # noqa: E402
    audit_plugins, to_markdown,
)

STATUS_LABELS = {
    'adapted': '已适配',
    'unadapted': '未适配',
    'no_tables': '无内容表',
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='审计插件模型的站点作用域适配情况')
    parser.add_argument('--plugins-dir',
                        default=os.path.join(PROJECT_ROOT, 'plugins'),
                        help='插件目录，默认 plugins/')
    parser.add_argument('--exempt-file',
                        default=os.path.join(
                            PROJECT_ROOT, 'scripts',
                            'plugin_site_scope_exempt.txt'),
                        help='豁免清单路径')
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    parser.add_argument('--markdown', action='store_true', help='输出 Markdown')
    parser.add_argument('--strict', action='store_true',
                        help='存在未适配插件时返回 1')
    return parser.parse_args(argv)


def run(argv=None):
    args = parse_args(argv)
    report = audit_plugins(args.plugins_dir, args.exempt_file)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.markdown:
        sys.stdout.write(to_markdown(report))
    else:
        print(f'插件站点作用域审计（{report["generated_at"]}）')
        print('-' * 72)
        print(f'{"插件":<18}{"版本":<10}{"结论":<10}规则')
        for item in report['plugins']:
            status = STATUS_LABELS.get(item['status'], item['status'])
            rules = '; '.join(
                f'{r["rule"]} {r["detail"]}' for r in item['rules']) or '-'
            print(f'{item["slug"]:<18}{item.get("version") or "-":<10}'
                  f'{status:<10}{rules}')
            for warning in item['warnings']:
                print(f'  [警告] {warning["rule"]} {warning["detail"]}')

    unadapted = [i for i in report['plugins'] if i['status'] == 'unadapted']
    if unadapted and not (args.json or args.markdown):
        print('-' * 72)
        print(f'发现 {len(unadapted)} 个未适配插件：'
              + '、'.join(i['slug'] for i in unadapted))

    if unadapted:
        return 1 if args.strict else 2
    return 0


if __name__ == '__main__':
    sys.exit(run())
