#!/usr/bin/env python3
"""CI 门禁：校验 OpenAPI 契约与 Flask 路由的一致性（v3.2.11）。

检查项：
  1. 所有 /api/v1/* 路由都必须挂载 @openapi_doc，或在 OPENAPI_SKIP 中
     显式排除（排除项必须写明原因）。
  2. spec 中每条路径/方法都必须对应真实存在的路由。
  3. 每个操作必须有非空 summary，且至少声明一个 response。
  4. docs/openapi.yaml 与当前代码生成结果一致（防止忘记重新生成）。

用法：
    python scripts/check_openapi.py           # 检查，失败退出 1
    python scripts/check_openapi.py --no-file # 跳过契约文件一致性检查
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _check_skip_reasons(errors):
    """OPENAPI_SKIP 的每一项必须在 openapi.py 中带注释说明原因。"""
    from app.api.openapi import OPENAPI_SKIP
    source = (ROOT / 'app' / 'api' / 'openapi.py').read_text(encoding='utf-8')
    for endpoint in sorted(OPENAPI_SKIP):
        # 排除表相邻行或同一行出现 '#' 注释即视为已说明原因
        marker = f"'{endpoint}'"
        idx = source.find(marker)
        if idx < 0:
            errors.append(f'OPENAPI_SKIP 中的 {endpoint} 未在 openapi.py 中找到')
            continue
        line_start = source.rfind('\n', 0, idx) + 1
        prev_start = source.rfind('\n', 0, line_start - 1) + 1
        context = source[prev_start:source.find('\n', idx)]
        if '#' not in context:
            errors.append(f'OPENAPI_SKIP 中的 {endpoint} 缺少原因注释')


def main():
    parser = argparse.ArgumentParser(description='校验 OpenAPI 契约覆盖率')
    parser.add_argument('--no-file', action='store_true',
                        help='跳过 docs/openapi.yaml 一致性检查')
    args = parser.parse_args()
    errors = []

    from app import create_app
    from app.api.openapi import (
        OPENAPI_SKIP, _normalize_path, build_spec, iter_api_rules,
    )

    app = create_app('testing')
    spec = build_spec(app)
    spec_paths = spec.get('paths') or {}

    covered = set()
    for rule, methods, endpoint, meta in iter_api_rules(app):
        if endpoint in OPENAPI_SKIP:
            continue
        if meta is None:
            errors.append(f'路由缺少 @openapi_doc：{rule} [{",".join(methods)}] '
                          f'(endpoint={endpoint})')
            continue
        path = _normalize_path(rule.rule)
        for method in methods:
            covered.add((path, method.lower()))
            op = (spec_paths.get(path) or {}).get(method.lower())
            if op is None:
                errors.append(f'spec 缺少操作：{method} {path}')
                continue
            if not (op.get('summary') or '').strip():
                errors.append(f'操作缺少 summary：{method} {path}')
            if not op.get('responses'):
                errors.append(f'操作缺少 responses：{method} {path}')

    # 反向：spec 中的路径必须真实存在
    for path, ops in spec_paths.items():
        for method in ops:
            if (path, method) not in covered:
                errors.append(f'spec 中的操作无对应路由：{method.upper()} {path}')

    _check_skip_reasons(errors)

    if not args.no_file:
        from scripts.generate_openapi import _dump_yaml
        expected = ('# 由 scripts/generate_openapi.py 自动生成，请勿手工修改\n'
                    + _dump_yaml(spec))
        target = ROOT / 'docs' / 'openapi.yaml'
        if not target.exists():
            errors.append('docs/openapi.yaml 不存在，请运行 '
                          'python scripts/generate_openapi.py')
        elif target.read_text(encoding='utf-8') != expected:
            errors.append('docs/openapi.yaml 与代码不一致，请重新运行 '
                          'python scripts/generate_openapi.py')

    if errors:
        print('OpenAPI 门禁未通过：')
        for item in errors:
            print('  -', item)
        return 1
    print(f'OpenAPI 门禁通过（{len(covered)} 个操作，'
          f'{len(OPENAPI_SKIP)} 项显式排除）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
