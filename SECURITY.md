# 安全策略（Security）

## 支持的版本

| 版本 | 支持状态 | 说明 |
| --- | --- | --- |
| 2.6.x | ✅ 完整支持 | 当前发布线，**最新安全版本 v2.6.4**（前台会员体系 + 栏目会员可见性 + 插件依赖强校验），建议运行 v2.5.x 及更早的站点覆盖代码 + 执行迁移升级 |
| 2.5.x | ✅ 完整支持 | 内容级多语言 + Redis 缓存与 Session |
| 2.4.x | ✅ 完整支持 | 安全加固线（CSRF 同源校验 + 纯文本字段 XSS 防御） |
| 2.3.x | ⚠️ 仅严重漏洞 | 建议升级至 2.6.x |
| 2.0.x ~ 2.2.x | ⚠️ 仅严重漏洞 | 建议升级至 2.6.x |
| 1.x 及更早 | ❌ 不再支持 | 自 v2.0 起包含登录安全加固/上传校验/RBAC 等安全模块，请尽快升级 |

## 报告漏洞

**请勿通过公开 Issue 报告安全漏洞。**

推荐方式（按优先级）：

1. **GitHub 私密安全报告**：仓库页 → Security → Report a vulnerability（[直达链接](https://github.com/pollybird/zhycms/security/advisories/new)）；
2. Gitee 仓库通过 Issue 私密模块或联系维护者（维护者主页：[pollybird](https://gitee.com/pollybird)）。

报告请尽量包含：

- 漏洞类型（如 XSS / SQL 注入 / 越权 / 文件上传绕过 / 会话固定）；
- 影响版本与部署形态（SQLite / MySQL、开发 / 生产）；
- 复现步骤（PoC 代码、请求报文、截图）；
- 建议的缓解措施（如有）。

## 响应承诺

- **48 小时内**确认收到并评估严重性；
- **7 天内**给出初步结论（接受 / 不构成 / 需更多信息）；
- 修复完成后在 `CHANGELOG.md` 披露（对未公开细节在补丁发布后才展开）；
- 报告者可选择被列入致谢名单。

## 安全设计要点（供渗透测试与自查参考）

- **登录防暴破**：密码错误计数锁定（默认 5 次 / 10 分钟，可配置）、图形验证码、锁定先于密码比对。
- **后台入口**：地址前缀可自定义（默认 `/admin`），保存后即时生效、旧地址立即 404；配置文件 `instance/admin_config.json` 权限 600。
- **上传安全**：MIME + 后缀双重校验，危险内容硬匹配（`<?php` / `#!` / ELF 头）直接拒绝；图片后缀强制内容为 `image/*`；SHA-256 内容去重。
- **审计日志**：后台操作全留痕，详情渲染全程 HTML 转义。
- **会话密钥（v2.4.1 修复 CWE-798）**：不再使用源码中硬编码的默认密钥。优先级为 环境变量 `ZHYCMS_SECRET_KEY` > `instance/secret_key` 持久化文件 > 首次启动自动生成 `secrets.token_hex(32)` 并落盘（权限 600）。**部署时仍强烈建议显式设置 `ZHYCMS_SECRET_KEY` 环境变量**（旧前缀 `ZHOCMS_SECRET_KEY` 仅兼容保留）。
- **会话 Cookie**：`HttpOnly` 始终启用；显式设置 `SameSite=Lax`；生产环境（`ProductionConfig`）启用 `Secure`，仅通过 HTTPS 传输。
- **Redis 服务端 Session（v2.5.0）**：设置环境变量 `REDIS_URL` 后，Session 从客户端 Cookie 迁移到 Redis 服务端存储，降低 XSS 窃取 Session 的风险，并支持多实例负载均衡。Redis 连接建议配置密码（`redis://:password@host:port/db`），生产环境建议 Redis 仅监听内网或通过防火墙限制访问。未配置 `REDIS_URL` 时回退 Cookie Session，行为与 v2.4.x 一致。
- **重定向校验**：登录与语种切换的 `next` 参数仅允许站内相对路径，拒绝协议相对 URL（`//evil.com`），杜绝开放重定向钓鱼。
- **CSRF 防护**：双机制纵深防御——(1) 会话 Cookie 显式 `SameSite=Lax`（v2.4.1）；(2) `before_request` 对所有 Cookie 鉴权的 POST/PUT/PATCH/DELETE 做 Origin/Referer 同源校验，跨站来源直接 403（v2.4.2）。REST API（`/api/`，X-API-Token 头鉴权，不依赖 Cookie）豁免；无 Origin/Referer 的非浏览器客户端（curl/SDK）放行。覆盖旧浏览器（不识别 SameSite）与同站子域名攻击场景。
- **输出转义**：搜索高亮过滤器先对原文与关键词做 HTML 转义再包裹 `<mark>`（v2.4.1）；v2.4.2 进一步把页脚版权、关站提示、表单说明、招聘岗位描述等**纯文本录入字段**的 `|safe` 全部移除（19 处模板），后台文本框内容一律自动 HTML 转义。富文本字段（文章正文、单页内容、richtext 自定义字段）为 CMS 设计的 HTML 内容，经受控编辑器录入。
- **数据导出**：表单导出 Excel 对公式注入字符（`= + - @` 等）前置单引号转义（CWE-1236）。
- **备份恢复**：上传的备份文件直接落盘到 `instance/backups`（非 Web 可访问目录），恢复完成后立即删除，不残留可被匿名下载的副本（CWE-552）。
- **安全响应头**：全站 `after_request` 统一注入 `X-Frame-Options: SAMEORIGIN`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: strict-origin-when-cross-origin`、`Content-Security-Policy`（含 `frame-ancestors 'self'`）。
- **调试模式**：`run.py` 的 `debug` 跟随配置类，不再硬编码 `True`；生产环境使用 `ZHYCMS_ENV=production` 或 gunicorn 启动。
- **权限**：RBAC 逐接口校验（视图装饰器 + 菜单逐项过滤），栏目级授权优先于全局角色。

## 安全配置基线（部署方自查）

1. **会话密钥**：生产环境显式设置 `ZHYCMS_SECRET_KEY` 为随机长字符串（`python -c "import secrets; print(secrets.token_hex(32))"`）；未设置时首次启动会自动生成并写入 `instance/secret_key`（权限 600），需妥善备份该文件（丢失会导致所有会话失效）。
2. **运行模式**：以 `ZHYCMS_ENV=production` 或 gunicorn（`wsgi:app`）运行，确保 `DEBUG=False`，避免暴露 Werkzeug 调试器。
3. **HTTPS**：前置 Nginx 反代并启用 HTTPS，会话 Cookie `Secure` 属性才能生效；反向代理负责剥离 `Server` 响应头。
4. **文件权限**：数据库账号遵循最小权限原则；`instance/` 整目录权限收敛为 600/700（含 `secret_key`、`db_config.json`、`backups/`）。
5. **备份**：定期在后台「备份运维」导出备份，验证 `instance/backups/` 的磁盘余量；恢复上传的备份文件不会残留 Web 目录。
6. **密钥轮换**：升级 v2.4.1 后若此前使用过默认硬编码密钥，请立即轮换 `ZHYCMS_SECRET_KEY`（或删除 `instance/secret_key` 让系统重新生成），旧会话会失效需重新登录。
7. **反向代理 / CSRF 同源校验（v2.4.2）**：CSRF 防护基于 `Origin/Referer` 与请求 `Host` 头比对，Nginx 反代需确保 `proxy_set_header Host $host;`（标准配置即满足）；若站点同时绑定多个域名访问，跨域名提交表单会被 403 拦截，属预期行为（同一域名访问正常）。REST API 调用（X-API-Token 鉴权）不受影响。
8. **Redis 安全（v2.5.0）**：启用 Redis 后，建议配置密码（`requirepass` 或 ACL），Redis 仅监听内网地址（`bind 127.0.0.1` 或内网 IP），生产环境通过防火墙限制 6379 端口访问。`REDIS_URL` 中的密码与数据库 URI 中的密码一样属于敏感信息，不应入版本库（`.env` 已在 `.gitignore` 中）。
