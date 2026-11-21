#!/usr/bin/env python3
"""生成对外内容 API 的 OpenAPI 3.0 契约文件（v3.2.11）。

契约由 ``app/api/openapi.py`` 注册表与 Flask 路由表合并生成，不引入
第三方序列化依赖：内置最小 YAML 输出器（字符串一律双引号转义），
保证在无 PyYAML 的环境也能产出可解析的 YAML。

用法：
    python scripts/generate_openapi.py                    # 写 docs/openapi.yaml
    python scripts/generate_openapi.py --output /tmp/a.yaml
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _inline(value):
    """标量/空容器单行输出。"""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return '{}'
    if isinstance(value, list):
        return '[]'
    return json.dumps(str(value), ensure_ascii=False)


def _dump_yaml(data, indent=0):
    """把 dict/list 递归输出为 YAML（字符串始终双引号，避免类型歧义）。"""
    pad = ' ' * indent
    lines = []
    if isinstance(data, dict):
        if not data:
            return pad + '{}\n'
        for key, value in data.items():
            name = json.dumps(str(key), ensure_ascii=False)
            if isinstance(value, (dict, list)) and value:
                lines.append(f'{pad}{name}:')
                lines.append(_dump_yaml(value, indent + 2).rstrip('\n'))
            else:
                lines.append(f'{pad}{name}: {_inline(value)}')
    elif isinstance(data, list):
        if not data:
            return pad + '[]\n'
        for item in data:
            if isinstance(item, (dict, list)) and item:
                body = _dump_yaml(item, indent + 2).rstrip('\n').split('\n')
                lines.append(f'{pad}- ' + body[0][indent + 2:])
                lines.extend(body[1:])
            else:
                lines.append(f'{pad}- {_inline(item)}')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description='生成 OpenAPI 契约')
    parser.add_argument('--output', default=str(ROOT / 'docs' / 'openapi.yaml'),
                        help='输出文件路径（默认 docs/openapi.yaml）')
    args = parser.parse_args()

    from app import create_app
    from app.api.openapi import build_spec

    app = create_app('testing')
    spec = build_spec(app)
    text = '# 由 scripts/generate_openapi.py 自动生成，请勿手工修改\n' + _dump_yaml(spec)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding='utf-8')
    paths = spec.get('paths') or {}
    operations = sum(len(v) for v in paths.values())
    print(f'已生成 {out}（{len(paths)} 条路径 / {operations} 个操作）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
