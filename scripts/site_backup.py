#!/usr/bin/env python3
"""导出站点级 ZIP 备份（大站点运维兜底）。

示例：
    python scripts/site_backup.py --site-id 0
    python scripts/site_backup.py --list
"""
import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='站点级备份导出')
    parser.add_argument('--app', default=None, help='项目根目录')
    parser.add_argument('--site-id', type=int, default=None, help='站点 ID')
    parser.add_argument('--list', action='store_true', help='列出已有备份')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    app_root = os.path.abspath(args.app or PROJECT_ROOT)
    if app_root not in sys.path:
        sys.path.insert(0, app_root)

    from app import create_app
    from app.services.site_backup import (
        BackupError, export_site, list_site_backups,
    )

    if not args.list and args.site_id is None:
        print('请指定 --site-id 或 --list', file=sys.stderr)
        return 2

    app = create_app()
    with app.app_context():
        if args.list:
            if args.site_id is None:
                print('--list 需要同时指定 --site-id', file=sys.stderr)
                return 2
            for item in list_site_backups(args.site_id):
                print(f'{item["filename"]}\t{item["size"]}\t'
                      f'{item["created_at"]:%Y-%m-%d %H:%M:%S}')
            return 0
        try:
            result = export_site(args.site_id)
        except BackupError as e:
            print(f'导出失败：{e}', file=sys.stderr)
            return 1
    print(result['path'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
