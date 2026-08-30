# 安全策略（Security）

## 支持的版本

| 版本 | 支持状态 | 说明 |
| --- | --- | --- |
| 2.1.x | ✅ 完整支持 | 当前发布线，安全修复优先发布于此 |
| 2.0.x | ⚠️ 仅严重漏洞 | 建议升级至 2.1.x（覆盖代码即可，无数据库变更） |
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
- **会话**：Flask 签名 Cookie；**生产环境必须设置强随机的 `ZHYCMS_SECRET_KEY` 环境变量**（前缀为 ZHYCMS_，与项目名一致；旧前缀 ZHOCMS_ 仅兼容保留）。
- **权限**：RBAC 逐接口校验（视图装饰器 + 菜单逐项过滤），栏目级授权优先于全局角色。

## 安全配置基线（部署方自查）

1. `ZHYCMS_SECRET_KEY` 必须设置为随机长字符串（`python -c "import secrets; print(secrets.token_urlsafe(48))"`）；
2. 以 `ZHYCMS_ENV=production` 或 gunicorn 运行（关闭 DEBUG）；
3. 数据库账号遵循最小权限原则，`instance/` 整目录权限 600/700；
4. 前置 Nginx 反代并启用 HTTPS，托管 `app/static/` 静态资源；
5. 定期在后台「备份运维」导出备份，并验证 `instance/backups/` 的磁盘余量。
