"""轻量 HTTP 压测脚本（v3.2.10）。

用于多 worker / 多实例部署的发布验收，只依赖 requests，不需要额外工具。

示例：
    python scripts/bench_http.py --url http://127.0.0.1:5000/ --duration 10 --concurrency 20
    python scripts/bench_http.py --url http://127.0.0.1:5000/api/v1/site \
        --header "Authorization: Bearer <token>"
"""
import argparse
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='ZhyCMS HTTP 压测')
    parser.add_argument('--url', required=True, help='目标 URL')
    parser.add_argument('--duration', type=float, default=10,
                        help='持续时间（秒），默认 10')
    parser.add_argument('--concurrency', type=int, default=10,
                        help='并发线程数，默认 10')
    parser.add_argument('--timeout', type=float, default=10,
                        help='单请求超时（秒），默认 10')
    parser.add_argument('--header', action='append', default=[],
                        help='附加请求头，格式 "Key: Value"，可重复')
    args = parser.parse_args(argv)
    if args.duration <= 0:
        parser.error('--duration 必须大于 0')
    if args.concurrency < 1:
        parser.error('--concurrency 必须大于等于 1')
    return args


def _headers(raw_headers):
    headers = {}
    for raw in raw_headers:
        if ':' in raw:
            key, value = raw.split(':', 1)
            headers[key.strip()] = value.strip()
    return headers


def _percentile(values, ratio):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * ratio)))
    return ordered[index]


def run_bench(url, duration, concurrency, timeout, headers):
    latencies = []
    errors = []
    lock = threading.Lock()
    deadline = time.monotonic() + duration

    def _worker():
        session = requests.Session()
        session.headers.update(headers or {})
        while time.monotonic() < deadline:
            started = time.monotonic()
            try:
                resp = session.get(url, timeout=timeout)
                elapsed = time.monotonic() - started
                with lock:
                    latencies.append(elapsed)
                    if resp.status_code >= 400:
                        errors.append(f'HTTP {resp.status_code}')
            except Exception as e:
                with lock:
                    errors.append(type(e).__name__)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for _ in range(concurrency):
            pool.submit(_worker)

    total = len(latencies) + len(errors)
    elapsed = max(duration, 0.001)
    return {
        'total': total,
        'success': len(latencies),
        'errors': len(errors),
        'error_rate': (len(errors) / total * 100) if total else 0.0,
        'qps': len(latencies) / elapsed,
        'p50': _percentile(latencies, 0.50) * 1000,
        'p95': _percentile(latencies, 0.95) * 1000,
        'p99': _percentile(latencies, 0.99) * 1000,
        'mean': (statistics.mean(latencies) * 1000) if latencies else 0.0,
        'error_samples': errors[:5],
    }


def main(argv=None):
    args = parse_args(argv)
    result = run_bench(args.url, args.duration, args.concurrency,
                       args.timeout, _headers(args.header))
    print(f"总请求: {result['total']}  成功: {result['success']}  "
          f"错误: {result['errors']}（{result['error_rate']:.2f}%）")
    print(f"QPS: {result['qps']:.1f}  平均: {result['mean']:.1f}ms  "
          f"p50: {result['p50']:.1f}ms  p95: {result['p95']:.1f}ms  "
          f"p99: {result['p99']:.1f}ms")
    if result['error_samples']:
        print('错误样例:', ', '.join(result['error_samples']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
