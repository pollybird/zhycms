# Webhook 事件订阅（v3.2.12）

ZhyCMS 可以把站点内的业务事件推送到你指定的 HTTPS 接收地址：文章发布/归档、表单提交、站点备份完成、站点启停、证书临期等。投递带 HMAC-SHA256 签名与幂等标识，失败自动重试。

- 入口：**后台 → 全局设置 → Webhook 集成**（需要 `site:manage` 权限）。
- 默认零外发：不配置订阅时不会产生任何外发请求。
- 按站点隔离：订阅与投递记录都归属当前站点，互不可见。

## 一、快速开始

1. 后台「Webhook 集成 → 新增订阅」，填写接收地址并勾选事件类型。
2. 保存后页面会**仅一次**完整显示签名密钥，请立即保存到接收方配置中；之后列表只显示掩码，丢失只能轮换。
3. 点击「发送测试」生成一条 `webhook.test` 事件，约 10 秒内由投递器发送；在「投递记录」查看结果。
4. 失败记录可手动「重试」（重置次数并重新排队）。

## 二、事件类型与载荷

请求为 `POST`，`Content-Type: application/json`，超时 5 秒，**不跟随重定向**（3xx 按失败处理）。请求体结构：

```json
{
  "event": "article.published",
  "site_id": 0,
  "replay_id": "6f0c2f2d0f2a4c8f9f0f6c6e2c7f9a1b",
  "created_at": "2026-11-21T14:00:00.000000",
  "data": { "article_id": 12 }
}
```

| 事件 | 触发时机 | `data` 要点 |
| --- | --- | --- |
| `article.published` | 工作流发布/审核通过提交后 | `article_id`、`column_id`、`title`、`url`、`published_at` |
| `article.archived` | 归档提交后 | `article_id`、`column_id`、`title`、`archived_at` |
| `form.submitted` | 表单提交落库后 | `form_id`、`form_slug`、`submission_id`、`fields`（仅字段名）、`submitted_at` |
| `backup.completed` | 站点备份导出成功后 | `filename`、`size`、`created_at`、`tables` |
| `site.status_changed` | 站点编辑或批量启停状态变化后 | `site_id`、`from`、`to` |
| `ssl.expiring` | 每日巡检发现临期/过期证书（同站同日随提醒去重） | `domain`、`days_left`、`status`、`expires_at` |
| `webhook.test` | 后台「发送测试」 | `message`、`timestamp` |

事件体不包含密码、密钥、完整手机号/邮箱及表单提交值等敏感内容。事件在业务事务**提交后**发射，发射或投递失败只记录日志，不影响主业务。

## 三、请求头与签名校验

| Header | 说明 |
| --- | --- |
| `X-ZhyCMS-Event` | 事件类型 |
| `X-ZhyCMS-Delivery` | 幂等标识（同 `replay_id`），重试保持不变 |
| `X-ZhyCMS-Signature` | `t=<unix时间戳>,v1=<hex签名>` |
| `User-Agent` | `ZhyCMS-Webhook/1.0` |

签名算法：`v1 = hex(hmac_sha256(secret, "{t}." + 原始请求体字节))`。

Python 接收端校验示例（Flask）：

```python
import hashlib
import hmac
import time

from flask import request

SECRET = '创建订阅时显示的密钥'
processed = set()  # 生产环境请用 Redis/数据库持久化


def verify_zhycms():
    header = request.headers.get('X-ZhyCMS-Signature', '')
    parts = dict(p.split('=', 1) for p in header.split(',') if '=' in p)
    timestamp = int(parts.get('t', '0'))
    # 建议时间戳偏差 ≤ 5 分钟，防重放
    if abs(time.time() - timestamp) > 300:
        return False
    expected = hmac.new(
        SECRET.encode('utf-8'),
        str(timestamp).encode('utf-8') + b'.' + request.get_data(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, parts.get('v1', ''))


def on_webhook():
    if not verify_zhycms():
        return 'invalid signature', 401
    delivery = request.headers.get('X-ZhyCMS-Delivery', '')
    if delivery in processed:  # 投递为 at-least-once，必须幂等
        return 'duplicate', 200
    processed.add(delivery)
    payload = request.get_json(force=True)
    # 按 payload['event'] 分发处理 payload['data']
    return 'ok', 200
```

要点：**使用原始请求体**复算签名（不要先解析再序列化 JSON）；校验时间戳；按 `X-ZhyCMS-Delivery` 去重后再执行业务。

## 四、重试与限速

- 2xx 视为成功，写 `delivered_at`；其余（含 3xx、4xx、5xx、超时、连接错误）按失败处理。
- 第 1 次失败 1 秒后重试，第 2 次失败 10 秒后重试，第 3 次失败进入终态 `failed` 并写审计日志；`last_error` 仅保留前 2KB 便于排查。
- 重试与手动重试都保持同一 `replay_id`。
- 每个订阅每秒最多投递 5 次，超出时顺延 1 秒且不消耗重试次数；多实例部署时使用 Redis 共享计数，否则为进程内滑窗。
- 多 worker 下通过条件 `UPDATE` 抢占事件，同一事件只会被一个进程领取。

## 五、安全边界（SSRF 与密钥）

- 保存订阅与每次发送前都会校验接收地址：默认**仅 HTTPS、仅公网地址**，拒绝内网/回环/保留 IP（含 DNS 解析结果与非常规 IP 字面量）。
- 设置键（数据库 `settings`，无后台 UI）：
  - `webhook_allow_http=on`：允许 HTTP 地址；
  - `webhook_allow_private=on`：允许内网地址（仍限 http/https 与合法主机名）。
  两者默认 `off`，仅建议在受控内网/测试环境开启。
- 密钥使用实例级 Fernet 密钥加密入库（`secret_enc`），列表仅显示掩码；轮换后旧密钥立即失效。
- 所有订阅变更、测试、重试均写审计日志；DNS 重绑定的 TOCTOU 风险仍需出口防火墙兜底，见 `SECURITY.md`。

## 六、运维

- 内置调度器每 10 秒执行一轮投递；多 worker + Redis 时仅领导者进程执行（v3.2.10）。
- 外置调度（`ZHYCMS_SCHEDULER_ENABLED=0`）时用 cron：

  ```cron
  * * * * * cd /path/to/zhycms && .venv/bin/python -m app.services.webhook --once
  ```

- 数据表：`webhook_subscriptions`（`site_id+url` 唯一）、`webhook_events`（一行 = 一次事件对一个订阅的投递，`replay_id` 唯一，`status+next_retry_at` 索引）。
- 停用外送：停用或删除全部订阅即可；卸载功能可回退代码后执行 `flask db downgrade` 删除两张表。
