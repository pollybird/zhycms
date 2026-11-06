# 安全策略（Security）

## 支持的版本

| 版本 | 支持状态 | 说明 |
| --- | --- | --- |
| 3.1.x | ✅ 完整支持 | 当前发布线，**最新版本 v3.1.8**（v3.1.8 安全加固专项：SAST 深度审计 P0+P1 共 7 个漏洞修复 + CSP 第三方资源白名单），建议运行 v3.0.x 及更早的站点覆盖代码升级 |
| 3.0.x | ✅ 完整支持 | 可视化页面构建器 + 插件默认布局贡献，建议升级至 3.1.x |
| 2.6.x | ✅ 完整支持 | 前台会员体系 + 插件依赖强校验，建议升级至 3.1.x |
| 2.5.x | ✅ 完整支持 | 内容级多语言 + Redis 缓存与 Session，建议升级至 3.1.x |
| 2.4.x | ✅ 完整支持 | 安全加固线（CSRF 同源校验 + 纯文本字段 XSS 防御），建议升级至 3.1.x |
| 2.3.x | ⚠️ 仅严重漏洞 | 建议升级至 3.1.x |
| 2.0.x ~ 2.2.x | ⚠️ 仅严重漏洞 | 建议升级至 3.1.x |
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
- **页面构建器（v3.0.0）**：编辑/发布/回滚全部后台端点受 RBAC 权限点门控（`builder:manage` / `builder:publish`）并写审计日志；预览页 `/admin/builder/preview/<id>` 仅登录后可访问，不产生可匿名访问的渲染端点；布局 JSON 服务端 allowlist 校验（组件类型/props 白名单/深度 ≤ 8/节点 ≤ 300/体积 ≤ 256KB），非法输入返回 400，拒绝存储与渲染；富文本组件复用 CKEditor5 受控录入，纯文本 props 服务端转义；组件图片/图标上传复用统一上传校验（MIME + 后缀 + 内容嗅探）；插件贡献的布局片段在插件启用前经同一套校验，非法片段拒绝启用；插件卸载前扫描布局引用，防止残留悬空组件；`<style>` 全局样式经服务端白名单键生成，不接受任意 CSS 注入。
- **第三方主题上传（v3.0.0）**：主题包内 `builder/<scope>.json` 上传时按同一套布局校验，非法整包拒绝；默认布局文件解析带 slug 正则 + realpath 防护，杜绝路径穿越读取任意文件。
- **表单输入保护（v3.1.2 M1）**：文章/栏目/碎片/搜索/分页等表单参数全部经 `safe_int()` 安全转换，非数字输入回退默认值而非 500；`page`/`limit`/`per_page` 同步加 `max(1, ...)` 拒负数。
- **上传子目录白名单（v3.1.2 M2）**：`save_upload_file` 与 `/admin/upload` 入口对 `sub_dir/type` 参数做双层校验（白名单 `common/image/file/avatar/editor/article/theme/site/column/fragment` + 段格式正则），任一 `../` 或绝对路径均回退到 `common`，杜绝路径穿越到任意目录写文件。
- **CKEditorFuncNum 反射型 XSS（v3.1.2 M3）**：富文本上传回调的 `CKEditorFuncNum` 仅接受 `^\d{1,6}$`，非法 400；`file_url`/`err` 经 `html.escape(..., quote=True)` 后再拼入 `<script>` 字符串。
- **SVG 上传管控（v3.1.2 M4）**：默认 `upload_allow_svg=off`，开启后做内容嗅探（拒绝 `<script>`/`onload=`/`onclick=`/`href="javascript:"`/`<foreignObject>`/`onerror=`/`onmouseover=`）+ 512KB 大小上限；`.svg` 静态响应强制 `Content-Type: image/svg+xml` + `nosniff` + `CSP: sandbox; default-src 'none'`，兜底防护存量 SVG。
- **登录验证码一次性消费（v3.1.2 M5）**：登录提交后**无论密码比对结果**先 `session.pop('captcha', None)`，杜绝同码复用枚举密码。
- **设置读取请求级缓存（v3.1.3 M7）**：`Setting.get()` 请求内整表缓存、`set()` 写后失效，消除渲染链路逐键 SQL；缓存仅存活于单请求，多 worker 无一致性问题。
- **浏览量写放大收口（v3.1.3 M8）**：浏览量改为缓存累加 + 周期/阈值合并回库（合并失败增量放回不丢数），消除逐请求写事务并修复整页缓存命中时计数不增长。
- **首页 N+1 治理（v3.1.3 M9）**：首页区块 3 条 SQL 批量拉取、栏目树请求级缓存（内容 CRUD 后经 `clear_content_cache` 统一失效），降低高频页面的 DB 压力面。
- **用户名唯一性竞态兜底（v3.1.3 M10）**：并发重名提交捕获 `IntegrityError` 回滚为业务错误提示，不再泄漏 500 异常页。

### v3.1.8 安全加固专项（GitCode issue #12，SAST 深度审计 P0+P1）

- **主题模板 SSTI 修复（VULN-001）**：**全站模板环境统一沙箱化**（`_SandboxedFlaskEnvironment`，前台 render_template 链与构建器直渲链同源），沙箱阻断 `__class__`/`__mro__`/`__subclasses__`/`__globals__` 等属性内省及 `|attr` 过滤器拼接绕过；模板 globals 与渲染上下文不暴露 `config` 对象，`request` 以只读白名单代理注入（阻断 `request.application.config` 逃逸链）；主题包上传模板静态审计（`app/utils/template_safety.py`）在表达式维度拦截 `|attr`、`config` 引用、`request` 白名单外属性/下标、`cycler`/`joiner`/`namespace`/`lipsum` 等。官方 8 套主题全量扫描零命中。
- **插件包上传 RCE 修复（VULN-002/009）**：插件包直传开关 `plugin_upload_enabled` **默认关闭**（插件管理页可显式开启）；上传包经 **AST 语法树源码审计**（`app/utils/plugin_safety.py`）：禁止导入 `subprocess`/`importlib`/`sys`/`builtins`/`operator` 等高危模块，禁止 `from os import system` 具名导入、`os.system` 限定名调用、`eval`/`exec`/`__import__`/`compile` 裸调用、危险 dunder 属性访问与动态属性名 `getattr`，杜绝字符串黑名单的拼接/变体绕过。官方插件为预装不经审计。
- **敏感凭证加密入库（VULN-003）**：`oss_*_secret`、`*_password`、`api_token`、`jwt_secret_key`、`search_meili_key` 等敏感配置改为 Fernet（`cryptography`）加密入库，密文 `gAAAAA` 前缀可识别；历史明文首次读取时自动加密回写（惰性迁移，无需 Alembic 脚本）。加密密钥与 SECRET_KEY 独立：环境变量 `ZHYCMS_ENC_KEY` > `instance/enc_key` 持久化文件（0600）> 首次启动自动生成。密钥不可用时优雅降级并告警。
- **SSRF 防护统一（VULN-004/005）**：公共工具 `app/utils/url_safety.py::assert_safe_external_url`（协议白名单 + hostname 精确白名单 + 内网/回环/链路本地/保留/多播/未指定 IP 拒绝），并覆盖非常规 IPv4 字面量（十进制 `2130706433`、十六进制 `0x7f000001`、八进制 `0177.0.0.1`、短格式 `127.1`，经 `socket.inet_aton` 归一化）、IPv4-mapped IPv6 递归判定与 `0.0.0.0/8`；非白名单域名经 `getaddrinfo` 解析后逐条记录判定（防 DNS 重绑定，解析失败 fail closed），白名单精确命中的可信域名跳过解析。企业微信 Webhook 强制 HTTPS + 域名精确等于 `qyapi.weixin.qq.com`（修复子串匹配绕过）；会员插件短信 Webhook 在保存时与发送前（占位符替换后的最终 URL）各校验一次。
- **JWT 密钥隔离（VULN-006）**：移除 `jwt_secret_key` 为空时回退复用 SECRET_KEY 的逻辑；未配置时启动自动生成随机密钥并加密持久化，DB 不可用阶段使用本次运行临时随机密钥，绝不回退 SECRET_KEY。升级后存量 JWT 全部失效，API 客户端需重新登录。
- **CSP 第三方资源白名单（F-001）**：CSP 构建抽为 `_build_csp()`，基础策略与 v3.1.7 逐字节一致；后台「系统设置 → 后台安全」可为 `script-src`/`style-src`/`img-src`/`font-src`/`connect-src`/`media-src`/`frame-src` 配置换行分隔的来源白名单（`https://host[:port]` 精确源或 `*.example.com` 子域通配），保存时逐行校验（拒绝裸 `*`、非 http/https、userinfo、query/fragment、空格引号）。`frame-ancestors` 防点击劫持基线与 SVG 沙箱 CSP 永不读取白名单。

## 安全配置基线（部署方自查）

1. **会话密钥**：生产环境显式设置 `ZHYCMS_SECRET_KEY` 为随机长字符串（`python -c "import secrets; print(secrets.token_hex(32))"`）；未设置时首次启动会自动生成并写入 `instance/secret_key`（权限 600），需妥善备份该文件（丢失会导致所有会话失效）。
2. **运行模式**：以 `ZHYCMS_ENV=production` 或 gunicorn（`wsgi:app`）运行，确保 `DEBUG=False`，避免暴露 Werkzeug 调试器。
3. **HTTPS**：前置 Nginx 反代并启用 HTTPS，会话 Cookie `Secure` 属性才能生效；反向代理负责剥离 `Server` 响应头。
4. **文件权限**：数据库账号遵循最小权限原则；`instance/` 整目录权限收敛为 600/700（含 `secret_key`、`db_config.json`、`backups/`）。
5. **备份**：定期在后台「备份运维」导出备份，验证 `instance/backups/` 的磁盘余量；恢复上传的备份文件不会残留 Web 目录。
6. **密钥轮换**：升级 v2.4.1 后若此前使用过默认硬编码密钥，请立即轮换 `ZHYCMS_SECRET_KEY`（或删除 `instance/secret_key` 让系统重新生成），旧会话会失效需重新登录。
7. **反向代理 / CSRF 同源校验（v2.4.2）**：CSRF 防护基于 `Origin/Referer` 与请求 `Host` 头比对，Nginx 反代需确保 `proxy_set_header Host $host;`（标准配置即满足）；若站点同时绑定多个域名访问，跨域名提交表单会被 403 拦截，属预期行为（同一域名访问正常）。REST API 调用（X-API-Token 鉴权）不受影响。
8. **Redis 安全（v2.5.0）**：启用 Redis 后，建议配置密码（`requirepass` 或 ACL），Redis 仅监听内网地址（`bind 127.0.0.1` 或内网 IP），生产环境通过防火墙限制 6379 端口访问。`REDIS_URL` 中的密码与数据库 URI 中的密码一样属于敏感信息，不应入版本库（`.env` 已在 `.gitignore` 中）。
9. **加密密钥（v3.1.8）**：敏感配置加密密钥优先取环境变量 `ZHYCMS_ENC_KEY`（可用 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 生成）；未设置时首次启动自动生成并写入 `instance/enc_key`（权限 600），**务必随 `instance/` 目录一并备份**（丢失后已加密的敏感配置无法解密，需在后台重新录入）。多实例/容器部署必须各实例配置相同的 `ZHYCMS_ENC_KEY`；轮换密钥前请先在后台记录并重新保存各敏感配置。
10. **插件包直传（v3.1.8）**：`plugin_upload_enabled` 默认关闭，仅在确需后台上传第三方插件 zip 时临时开启，用完建议关闭；上传包需通过静态源码审计，请仍只安装来源可信的插件。
11. **SSRF 与 DNS 重绑定残余风险（v3.1.8）**：`url_safety.py` 已在校验时对外部域名做 DNS 解析并逐条记录判定（解析失败 fail closed），可拦截绝大多数重绑定攻击。但 DNS 校验与实际 HTTP 请求之间存在 TOCTOU 时间窗——攻击者理论上可在校验通过后翻转 DNS 记录指向内网（典型 TTL=0 双重应答）。**彻底防御需在网络层兜底**：生产环境应配置出口防火墙（egress firewall）或出口代理，禁止应用服务器主动访问内网网段（`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`169.254.0.0/16`、`127.0.0.0/8`、云元数据地址 `169.254.169.254` 等），仅放行确需访问的外部服务端口。iptables 示例：`iptables -A OUTPUT -d 169.254.169.254 -j DROP`。使用云主机时建议同时开启云厂商的元数据服务加固（如 IMDSv2 强制 token 模式）。
