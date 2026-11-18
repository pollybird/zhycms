# 多站点部署指南

本指南面向同一套 ZhyCMS 实例承载多个站点（站群）的部署方式。单站点部署不需要阅读本文，也不需要修改 nginx。

## 一、部署形态

推荐「单实例多站」：

```text
浏览器 → nginx（按 Host 分流）→ zhycms:5000 → 按 Host 解析站点
```

- 只运行一个 zhycms 容器或进程；
- 站点在后台「站点管理」中创建，**不是一站一容器**；
- 新站点只需要新增 DNS 记录与 nginx server 块；
- 上传文件自动落在 `app/static/uploads/site{N}/`，缓存键为 `frontend/site{N}/...`。

多实例形态（可选）见 `docker/compose.multi.example.yml` 中注释的 `app-b`：两个实例共享数据库与 Redis，并必须启用 Redis 会话。

## 二、前置条件

- 已部署可访问的 ZhyCMS（`python run.py` 或 Docker）；
- 根域名或一级域名可配置 DNS；
- nginx 已安装，且可修改 `conf.d` / `sites-enabled`；
- 后台账号拥有 `site:manage` 权限（超级管理员默认拥有）。

## 三、DNS

| 站点类型 | 记录 | 示例 |
| --- | --- | --- |
| 独立域名 | A 记录指向服务器 IP | `shop.example.com → 203.0.113.10` |
| 子域站点 | A 记录 + 泛解析 | `news.example.com`、`*.example.com → 203.0.113.10` |

DNS 生效后再继续，可用 `dig +short shop.example.com` 验证。

## 四、后台创建站点

1. 登录后台 →「全局设置 → 站点管理」→「新增站点」；
2. 填写名称与唯一标识（slug）；
3. 按需填写：
   - **精确域名**：`shop.example.com`（优先匹配）；
   - **子域标签**：`news`，配合基础域名 `example.com` 生成 `news.example.com`；
4. 保存后记录站点 ID（文件名与日志路径会用到）。

默认站点（`id=0`）会生成 `server_name _;` 兜底块，承接未匹配任何域名的请求，与应用的解析回退行为一致。

## 五、生成并落地 nginx 配置

```bash
# 1. 生成到 build/nginx（重复执行会覆盖同名文件）
python scripts/generate_nginx_sites.py \
  --base-domain example.com \
  --upstream 127.0.0.1:5000 \
  --output-dir build/nginx

# 2. 只预览，不写文件
python scripts/generate_nginx_sites.py --base-domain example.com --stdout

# 3. 只生成某个站点
python scripts/generate_nginx_sites.py --site-id 2 --stdout
```

生成规则：

- 每个站点一个 `zhycms-site{N}.conf`；
- 独立域名写 `server_name shop.example.com;`；
- 子域写 `server_name news.example.com;`；
- 默认站点追加 `_` 兜底并排在最后；
- 含 `client_max_body_size`、访问/错误日志、ACME 验证目录与反代头；
- 非法域名（含空格、`;`、`}` 等）会跳过并在 stderr 提示，不会写入配置。

落地与校验：

```bash
sudo cp build/nginx/*.conf /etc/nginx/conf.d/
sudo nginx -t
sudo nginx -s reload
```

> 生成脚本默认会尝试用本机 `nginx -t` 校验；本地没有 nginx 时自动跳过，可用 `--skip-validate` 显式跳过。

## 六、HTTPS（可选）

先确保 HTTP 访问正常，再申请证书：

```bash
sudo certbot certonly --webroot \
  -w /var/www/letsencrypt \
  -d shop.example.com
```

然后重新生成带 SSL 的配置：

```bash
python scripts/generate_nginx_sites.py --base-domain example.com --ssl
sudo cp build/nginx/*.conf /etc/nginx/conf.d/
sudo nginx -t && sudo nginx -s reload
```

后台「站点管理 → 部署」会读取 `/etc/letsencrypt/live/{domain}/cert.pem` 并显示剩余天数；读不到时显示「未配置」，不影响页面访问。

## 七、Docker 部署

单实例多站：

```bash
cp docker/.env.example .env
# 按需修改 .env 中的域名、数据库与 Redis 连接
docker compose -f docker/compose.multi.example.yml up -d
```

多实例（可选）：

1. 取消 `docker/compose.multi.example.yml` 中 `app-b` 的注释；
2. 两个实例共用同一 `ZHYCMS_DB_URI` 与 `REDIS_URL`；
3. nginx upstream 同时指向 `127.0.0.1:5001` 与 `127.0.0.1:5002`；
4. 未启用 Redis 会话时不要使用多实例，否则登录态不共享。

## 八、验证清单

- [ ] `curl -H 'Host: shop.example.com' http://127.0.0.1:5000/` 返回对应站点首页；
- [ ] `curl -H 'Host: news.example.com' http://127.0.0.1:5000/` 返回子域站点首页；
- [ ] 未匹配域名返回默认站点；
- [ ] 两个站点的上传文件分别落在 `uploads/site{N}/`；
- [ ] 后台「站点资源」能看到两个站点，磁盘/文章数正常；
- [ ] 站点管理员仅能看到被授权站点；
- [ ] `python scripts/audit_plugins_site_scope.py` 无「未适配」插件；
- [ ] 日志中出现 `[site=N]` 标签，能区分请求来源。

## 九、常见问题

| 现象 | 排查 |
| --- | --- |
| 访问域名仍进入默认站点 | DNS 未生效、`server_name` 拼写错误、nginx 未 reload |
| 生成脚本提示跳过站点 | 站点没有 domain/subdomain，或域名含非法字符 |
| 子域没有生成 | 未传 `--base-domain`，且站点设置中的 `site_url` 为空 |
| 上传 413 | 调大 nginx `client_max_body_size` 与后台「单文件最大 MB」 |
| 证书显示未配置 | 证书路径不是 `/etc/letsencrypt/live/{domain}/`，或进程无读取权限 |
