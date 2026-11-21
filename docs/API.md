# 内容 API（v3.2.11）

面向小程序、移动端与第三方系统的公开内容 API。所有端点位于 `/api/v1/`，
响应统一为：

```json
{"code": 0, "message": "ok", "data": null, "meta": null}
```

`code != 0` 表示失败，`message` 为可直接展示的中文原因。机器可读契约：
`GET /api/v1/openapi.json`（或仓库内 `docs/openapi.yaml`）。

## 一、开关与鉴权

| 设置项 | 默认值 | 说明 |
| --- | --- | --- |
| `api_enable` | `on` | `off` 时所有 `/api/v1/*` 返回 404 |
| `api_auth_mode` | `both` | `token`（仅静态令牌）/ `jwt` / `both`（优先 JWT） |
| `api_token` | 空 | 静态令牌，请求头 `X-API-Token` |
| `api_write_enable` | `off` | 内容写端点开关；`off` 时写请求 404 |
| `api_rate_limit_read` | `120` | 只读端点每 IP 每分钟次数 |
| `api_rate_limit_write` | `30` | 写端点每账号 + IP 每分钟次数 |
| `api_cache_ttl` | `60` | 只读接口缓存秒数，`0` 关闭 |
| `api_cors_origins` | 空 | 允许的跨域来源，逗号分隔或 `*` |

- **只读端点**：`X-API-Token` 与 `Authorization: Bearer <access_token>` 均可。
- **写端点**：仅接受 Bearer JWT；静态令牌一律 403。
- 设置均按站点存储，未配置时回退默认站点 0。

### JWT 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/auth/login` | 用户名密码登录，返回 `access_token` / `refresh_token` |
| POST | `/api/v1/auth/refresh` | 用 refresh token 换新 access token |
| POST | `/api/v1/auth/logout` | 登出（配置 Redis 时令牌立即失效） |

## 二、只读端点

| 方法 | 路径 | 权限 |
| --- | --- | --- |
| GET | `/api/v1/site` | 公开 API 鉴权 |
| GET | `/api/v1/columns` | 公开 API 鉴权（`?tree=1` 返回树） |
| GET | `/api/v1/columns/<slug>` | 公开 API 鉴权 |
| GET | `/api/v1/columns/<slug>/articles` | 公开 API 鉴权（`page` / `per_page` / `keyword`） |
| GET | `/api/v1/articles/<id>` | 公开 API 鉴权 |
| GET | `/api/v1/forms/<slug>/submissions` | JWT + `form:view` |
| GET | `/api/v1/sites` | JWT + 超级管理员 |
| GET | `/api/v1/sites/<id>/metrics` | JWT + 超级管理员（最近 30 条日快照） |
| GET | `/api/v1/openapi.json` | 免鉴权（受 `api_enable` 控制） |

插件可贡献额外端点，如 `GET /api/v1/banners/<slug>`、`GET /api/v1/columns/<slug>/products`、
`GET /api/v1/products/<id>`，插件未启用时不注册。

分页响应示例：

```json
{
  "code": 0,
  "data": [{"id": 1, "title": "..."}],
  "meta": {"page": 1, "per_page": 20, "total": 42, "total_pages": 3}
}
```

## 三、写端点（默认关闭）

开启 `api_write_enable=on` 后可用，全部要求 Bearer JWT，并按站点隔离：

| 方法 | 路径 | 权限 |
| --- | --- | --- |
| POST | `/api/v1/articles` | `content:create` + 栏目授权 |
| PUT / DELETE | `/api/v1/articles/<id>` | `content:edit` / `content:delete` + 栏目授权 |
| POST | `/api/v1/columns` | `column:manage` |
| PUT / DELETE | `/api/v1/columns/<id>` | `column:manage` |
| POST | `/api/v1/fragments` | `system:settings` |
| PUT / DELETE | `/api/v1/fragments/<id>` | `system:settings` |

- 状态置为 `published` 还需栏目发布标志 `can_publish`，否则 403。
- `PUT` 为全量替换：请求体中未提供的可写字段会被置空（需要清空某字段时显式传空串）；API 未暴露的栏目自定义字段配置、翻译与单页内容会被保留。
- 写入复用后台服务层：版本快照、审计日志、自定义字段（`fields` 对象，键为字段 key 或 id）。
- 栏目存在子栏目或文章时删除返回 409。
- 请求体不接受 `site_id`，站点由当前域名 / 站点上下文决定。

```bash
TOKEN=$(curl -s -X POST https://example.com/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"***"}' | jq -r .data.access_token)

curl -X POST https://example.com/api/v1/articles \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"column_id":1,"title":"API 创建的文章","content":"<p>正文</p>","status":"draft"}'
```

## 四、Python SDK

仓库内 `sdk/` 提供零侵入的官方客户端（独立包，不影响主程序依赖）：

```bash
pip install ./sdk
```

```python
from zhycms_sdk import Client

client = Client('https://example.com')
client.login('admin', 'password')

for item in client.content.articles('news', page=1, per_page=10).items:
    print(item['title'])

# 开启写端点后
client.content.create_article(1, 'SDK 创建的文章', content='<p>正文</p>')
```

`Client` 在 access token 过期（401）时自动用 refresh token 续期并重放一次；
GET 遇到网络错误或 5xx 额外重试一次，写请求不自动重试。接口错误统一抛
`ZhyCMSAPIError`（含 `status` / `code` / `message`）。

## 五、契约维护

```bash
python scripts/generate_openapi.py    # 重新生成 docs/openapi.yaml
python scripts/check_openapi.py       # 门禁：路由覆盖率 + 文件一致性
```

新增 `/api/v1/` 路由时必须挂 `@openapi_doc`，或在 `app/api/openapi.py` 的
`OPENAPI_SKIP` 中显式排除并写明原因，否则门禁失败。
