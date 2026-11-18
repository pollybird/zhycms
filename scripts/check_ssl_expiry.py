#!/usr/bin/env python3
"""检查站点 SSL 证书剩余天数。

示例：
    python scripts/check_ssl_expiry.py
    python scripts/check_ssl_expiry.py --days 15 --json
    python scripts/check_ssl_expiry.py --strict --no-notify

退出码：0 无临期/过期证书；1 存在告警（仅 --strict）；2 执行失败。
"""
import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='站点 SSL 证书到期检查')
    parser.add_argument('--app', default=None, help='项目根目录')
    parser.add_argument('--days', type=int, default=None,
                        help='剩余天数告警阈值，默认读取站点设置（10）')
    parser.add_argument('--json', action='store_true', help='以 JSON 输出')
    parser.add_argument('--strict', action='store_true',
                        help='存在临期或过期证书时返回退出码 1')
    parser.add_argument('--no-notify', action='store_true',
                        help='只检查并写审计，不发送邮件/企业微信提醒')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    app_root = os.path.abspath(args.app or PROJECT_ROOT)
    if app_root not in sys.path:
        sys.path.insert(0, app_root)

    from app import create_app
    from app.services.site_ssl import run_daily_check

    try:
        app = create_app()
        with app.app_context():
            summary = run_daily_check(warn_days=args.days,
                                      notify=not args.no_notify)
    except Exception as e:
        print(f'证书检查失败：{e}', file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, default=str, indent=2))
    else:
        print(f'已检查 {summary["checked"]} 个站点，阈值 {summary["warn_days"]} 天')
        for item in summary['expiring']:
            print(f'[临期] {item["host"]} 剩余 {item["days_left"]} 天'
                  f'（{item["expires_at"]}）')
        for item in summary['expired']:
            print(f'[过期] {item["host"]} 已过期 {-item["days_left"]} 天'
                  f'（{item["expires_at"]}）')
        for item in summary['invalid']:
            print(f'[异常] {item["host"]}：{item["error"]}')
        print(f'临期 {len(summary["expiring"])} 个，过期 {len(summary["expired"])} 个，'
              f'未配置 {len(summary["missing"])} 个')

    if args.strict and (summary['expiring'] or summary['expired']):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
