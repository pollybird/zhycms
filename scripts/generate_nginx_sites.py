#!/usr/bin/env python3
"""把站点表渲染成 nginx vhost 配置文件。

示例：
    python scripts/generate_nginx_sites.py --base-domain example.com
    python scripts/generate_nginx_sites.py --stdout --site-id 2
    python scripts/generate_nginx_sites.py --output-dir /etc/nginx/conf.d

脚本只读取数据库中的站点与设置，不写库、不 reload nginx。
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='根据站点表生成 nginx 站点配置')
    parser.add_argument('--app', default=None,
                        help='项目根目录（默认脚本上级目录）')
    parser.add_argument('--base-domain', default=None,
                        help='子域站点使用的基础域名，缺省读取站点设置 site_url')
    backend = parser.add_mutually_exclusive_group()
    backend.add_argument('--upstream', default=None,
                         help='单个后端地址，默认 127.0.0.1:5000')
    backend.add_argument('--upstreams', default=None,
                         help='多实例后端地址，逗号分隔，如 127.0.0.1:5000,127.0.0.1:5001')
    parser.add_argument('--output-dir', default='build/nginx',
                        help='输出目录，默认 build/nginx')
    parser.add_argument('--stdout', action='store_true',
                        help='直接打印配置，不写文件')
    parser.add_argument('--site-id', type=int, default=None,
                        help='仅生成指定站点')
    parser.add_argument('--ssl', action='store_true',
                        help='生成 80 跳转 443 与证书配置')
    parser.add_argument('--skip-validate', action='store_true',
                        help='跳过 nginx -t 校验')
    return parser.parse_args(argv)


def validate_config(conf_dir):
    """尝试用本机 nginx 校验生成的配置；没有 nginx 时跳过。"""
    nginx = shutil.which('nginx')
    if not nginx:
        print('未找到 nginx 命令，跳过配置校验', file=sys.stderr)
        return True

    include_dir = os.path.abspath(conf_dir)
    content = (
        'events {}\n'
        'http {\n'
        f'    include {include_dir}/*.conf;\n'
        '}\n'
    )
    fd, conf_path = tempfile.mkstemp(prefix='zhycms-nginx-', suffix='.conf')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(content)
        proc = subprocess.run(
            [nginx, '-t', '-c', conf_path],
            capture_output=True, text=True, timeout=20)
        if proc.returncode == 0:
            print('nginx 配置校验通过')
            return True
        print('nginx 配置校验失败：', file=sys.stderr)
        sys.stderr.write(proc.stderr or proc.stdout)
        return False
    except (OSError, subprocess.SubprocessError) as e:
        print(f'nginx 配置校验异常，已跳过：{e}', file=sys.stderr)
        return False
    finally:
        try:
            os.unlink(conf_path)
        except OSError:
            pass


def main(argv=None):
    args = parse_args(argv)
    app_root = os.path.abspath(args.app or PROJECT_ROOT)
    if app_root not in sys.path:
        sys.path.insert(0, app_root)

    from app import create_app
    from app.services.site_deploy import generate_for_app, render_upstream_block

    upstreams = [u for u in (args.upstreams or '').split(',') if u.strip()]
    app = create_app()
    text, entries, skipped = generate_for_app(
        app, base_domain=args.base_domain, upstream=args.upstream,
        ssl=args.ssl, site_id=args.site_id, upstreams=upstreams)

    for item in skipped:
        print(f'跳过站点 {item["site_id"]}（{item["name"]}）：{item["reason"]}',
              file=sys.stderr)

    if not entries:
        print('无站点可生成')
        return 0

    if args.stdout:
        sys.stdout.write(text)
        return 0

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    # 多实例 upstream 独立成文件，避免多个站点配置重复定义 upstream
    block = render_upstream_block(upstreams)
    if block:
        upstream_path = os.path.join(output_dir, '00-zhycms-upstream.conf')
        with open(upstream_path, 'w', encoding='utf-8') as fh:
            fh.write(block + '\n')
        print(f'已生成 {upstream_path}')
    for entry in entries:
        path = os.path.join(output_dir, entry['filename'])
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(entry['content'] + '\n')
        print(f'已生成 {path}')

    print(f'将生成 {len(entries)} 个站点配置（跳过 {len(skipped)} 个无 domain/subdomain 的站点）')
    if not args.skip_validate:
        validate_config(output_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
