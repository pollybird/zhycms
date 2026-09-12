# 运维故障排查 FAQ

> 适用版本：ZhyCMS ≥ 2.6.4　|　覆盖：启动、数据库迁移、缓存、主题插件、伪静态、上传、搜索、Docker、备份

通用排查三板斧：

1. **看日志**：开发模式看控制台；生产看 `journalctl -u <服务名>` 或 gunicorn 输出；Docker 用 `docker compose logs -f app`。Alembic/Redis 等非致命问题以 `WARNING` 记录，不中断启动。
2. **健康检查**：`curl http://127.0.0.1:5000/healthz` 返回 200 即应用存活（Docker HEALTHCHECK 同此）。
3. **定位设置**：很多「突然失效」是 `settings` 表开关项（缓存/伪静态/API/主题）被改动，先到后台系统设置核对。

---

## 1. 启动与部署

### Q：启动报 `ModuleNotFoundError` / `ImportError`
- 虚拟环境没激活或依赖不完整：`pip install -r requirements.txt -r requirements-prod.txt`（生产需 gunicorn/gevent）。
- 升级后新增依赖未安装：对照 `UPGRADE.md` 该版本章节。
- 插件导入报错：启动日志会标红该插件并继续加载其余插件；修复或移除该插件目录后重启。

### Q：`Address already in use` 端口 5000 被占
`lsof -i:5000` 找到进程；或修改启动命令端口。生产建议用 Nginx 反代 + gunicorn。

### Q：Gunicorn 多 worker 下行为不一致
ZhyCMS 的启停类开关全部存数据库（settings 表），多 worker 天然一致；出现不一致时检查是否有人改了环境变量级配置但未重启全部 worker。

---

## 2. 数据库与 Alembic 迁移

### 2.1 迁移版本对照表

| Revision | 版本 | 内容 |
| --- | --- | --- |
| 0001 | baseline | v2.3.0 基线 |
| 0002 | v2.4.0 | search_index 表 |
| 0003 | v2.4.0 | 搜索设置种子 |
| 0004 | v2.4.0 | 对象存储设置 |
| 0005 | v2.5.0 | 内容级 i18n |
| 0006 | v2.5.0 | 插件 i18n |
| 0007 | v2.5.2 | 插件 i18n 结构化字段 |
| 0008 | v2.6.4 | 栏目 member_only |

插件自有的 `plugins/<slug>/migrations/versions/*.py` 由核心启动时自动合并进 `version_locations`。

### 2.2 迁移自动执行机制（bootstrap）

启动时 `_alembic_bootstrap()` 自动判断：

- **全新安装**（无核心表）：`db.create_all()` 建全部表 → `stamp 0001`；
- **v2.3.0 及更早旧库**（有核心表、无 `alembic_version`）：`stamp 0001` → `upgrade head` 增量；
- **正常升级**：直接 `upgrade head`；
- bootstrap 异常仅记录 `WARNING: Alembic bootstrap 跳过（非致命）`，不阻断启动——**但需尽快手工修复**，否则后续版本字段缺失。

### Q：启动日志出现 `Alembic bootstrap 跳过（非致命）`
处理步骤：

```bash
# 1) 查看当前版本与错误
flask-alembic 无法直用时，用 Python：
python -c "from app import create_app; app=create_app()"
# 2) 手工执行迁移
cd 项目根
python -m flask --app wsgi:app db upgrade   # 或下方原生方式
alembic -x ... # 项目用 flask_migrate，推荐：
python - <<'PY'
from app import create_app
from flask_migrate import upgrade
app = create_app()
with app.app_context():
    upgrade(directory='migrations')
PY
```

常见失败原因与处理：

| 报错 | 原因 | 处理 |
| --- | --- | --- |
| `Can't locate revision identified by 'xxxx'` | 库里 `alembic_version` 指向不存在/已被删除的历史版本（如手工清理过 migrations 目录） | 确认库结构后 `stamp` 到正确版本：`flask_migrate.stamp(revision='0008')`（字段缺失时先补 0002-0008 对应字段） |
| `Table 'xxx' already exists` | 手工建过表或 create_all 与迁移并发 | 该表已在则跳过对应迁移；必要时在迁移脚本中加存在性判断后重跑 |
| `Duplicate column name` | 旧库字段已手工加过 | 同上，跳过或改判断式迁移 |
| 迁移卡死/超时 | 大表加索引锁等待 | 低峰执行；MySQL 检查 `SHOW PROCESSLIST`，必要时先 `SET lock_wait_timeout` |
| 插件迁移报 `Can't locate revision`（插件 rev 链断裂） | 插件被卸载导致其迁移文件消失 | 重新安装该插件目录，或 `alembic_version` 中删去对应插件 revision（`DELETE FROM alembic_version WHERE version_num='xxx'` 前先备份） |

### Q：如何安全降级
ZhyCMS 不承诺自动降级（迁移含数据变更）。标准做法：**恢复升级前的备份**（`instance/backups/` 或mysqldump），而非 `downgrade`。执行 `downgrade` 仅用于刚失败、未写数据的场景。

### Q：SQLite 换 MySQL/PostgreSQL
`instance/zhycms.db` 与服务端数据库之间不做自动搬迁。流程：新库安装最新版 → 旧站导出（备份功能/SQL 导出）→ 按表导入 → 上传目录 `app/static/uploads/` 与 `instance/`（uploads、search_index 等）原样复制。uploads 中相对路径存储，直接复制即可。

### Q：`OperationalError: (1045, "Access denied for user")`
数据库账号密码错误。Docker 场景注意：**数据卷首次初始化时的密码才有效**，改 `.env` 密码不会改已初始化卷的密码——见 §8 Docker 专项。

### Q：MySQL 报 `Specified key was too long` / 字符集问题
建库统一 `utf8mb4`：`CREATE DATABASE zhycms CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`

---

## 3. 缓存与 Redis

### Q：日志出现 `[Redis] REDIS_URL=... 但连接失败，回退 SimpleCache`
Redis 不可达时的自动降级，站点仍可用（本地内存缓存 + Cookie Session）。多 worker 部署建议修复：检查 Redis 是否启动、密码、`REDIS_URL` 格式（`redis://:密码@host:6379/0`）。

### Q：改了内容/设置前台不生效（缓存不刷新）
- 后台保存内容与设置时会自动清缓存；直改数据库不会。
- 手工清空：重启应用（SimpleCache 即清），或 Redis 场景 `redis-cli FLUSHDB`（注意该库不要与其他系统混用）。
- 主题切换后页面仍旧样式：确认使用了 v2.6.3+（此版本修复了「缓存键含主题 + 切换清缓存」）。

### Q：多 worker 下用户登录态丢失
Session 依赖 Redis（服务端 Session）；Redis 掉线回退 Cookie Session 后，各 worker 密钥需一致（`SECRET_KEY` 固定，勿每次随机）。

---

## 4. 主题与插件

### Q：`TemplateNotFound: xxx.html`
1. 看路径是否带了双后缀（`login.html.html` 类问题多为插件 `_render` 拼接错误）；
2. 确认文件位于正确目录：主题 `themes/<slug>/`，插件 `plugins/<slug>/templates/`；
3. 自定义主题缺必备模板会被拒绝启用；已启用后缺文件则回退 default，仍报错说明 default 也缺（升级覆盖不完整时重装 default 主题）。

### Q：主题上传被拒绝
对照 8 步校验：格式白名单（zip/tar.gz/tgz）→ 压缩包完整性 → 路径穿越 → symlink → manifest 合法性与 slug 正则 → 7 个必备模板齐全 → 形态 A/B 自动归一化 → 内置主题禁覆盖/同名需先删。报错信息会指明第几步失败。

### Q：插件启用失败：提示版本/依赖
v2.6.4 强校验顺序 **min_core_version → requires → extends**。按提示先升级核心或启用依赖插件；禁用被依赖插件被拦截时，提示中会列出需先禁用哪些插件。

### Q：插件显示「加载失败」
启动日志该插件的 import traceback 即原因。典型：模型字段与数据库不匹配（见 §2 迁移）、依赖包缺失、`__init__.py` 忘写 `plugin = XxxPlugin()`。

### Q：删除插件/主题时提示要验证码
危险操作独立一次性验证码（端点 `/captcha/delete-confirm`，不区分大小写），输入页面图片中的字符即可；内置或启用中的对象拒绝删除，需先禁用。

---

## 5. 伪静态与路由

### Q：开启伪静态后列表第 2 页 404
Nginx 需把 `/(slug).html`、`/(slug)-N.html` 一并转发到应用（一般 `try_files $uri $uri/ @app;` + `@app` 到 gunicorn 即可）。确认请求确实到达应用：直接访问 `/column/<slug>?page=2`（动态形式，始终兼容返回 200）能通，则是 Web 服务器转发问题。

### Q：`/article-5.html` 打不开或被当成栏目分页
`article-` 前缀规则优先级高于分页规则；若自定义主题/插件注册了冲突路由（如 `/article-<x>.html`），会出现劫持。排查：grep 插件目录中的 `article-` 路由。

### Q：改了后台路由前缀后后台打不开
前缀修改即时生效，无需重启；打不开通常是使用了保留字（如 `form`，与表单插件前台冲突）。直接改回：`instance/db_config.json` 同级 settings 中恢复，或用数据库改 `admin_prefix` 设置项。

### Q：robots.txt / sitemap.xml / favicon.ico 404
三者动态生成且在初始化拦截/维护模式中豁免，正常始终可访问；404 多为应用根本没启动成功（Nginx 静态兜底返回了 404），回到 §1 查启动日志。

---

## 6. 文件上传

### Q：中文文件名上传后扩展名丢失/类型被拒
上传类型判断从**原始文件名**提取后缀（v2.4+ 已修复）；若仍出现，确认未绕过核心 `save_upload_file()` 自行调用 `secure_filename` 后再取后缀。

### Q：上传大文件 413
Nginx `client_max_body_size`（默认 1m）需调大；同时检查后台上传大小限制设置与 `MAX_CONTENT_LENGTH`。

### Q：图片不显示
- 检查 `app/static/uploads/` 写权限（Docker 中 uid 1000）；
- 直链图片有实时缩略/缓存（`instance/image_cache/`），磁盘满或该目录权限错误会导致图片 500，清空该目录可重建。

---

## 7. 全站搜索

### Q：搜不到刚发布的内容
保存时会实时索引（`reindex_object`）。若索引异常，核心自动回退 SQL LIKE 兜底（应有结果）；连兜底都无结果时检查文章 `status=published`、`is_deleted=0`、栏目启用。

### Q：搜索报错或结果混乱
后台「重建索引」；仍异常时删除 `instance/search_index/` 下对应语言目录再重建（索引可随时全量重建，无数据风险）。

### Q：插件内容搜索 404
插件禁用会清理其索引残留；若禁用前未清（旧版本），升级后手动重建索引即可。

---

## 8. Docker 专项

### Q：容器反复重启，日志 `database not reachable after 60s`
entrypoint 等待数据库 60 秒超时。检查 db 服务健康状态与 `ZHYCMS_DB_URI`；首次启动 MySQL/PG 初始化慢时耐心等待。

### Q：`Access denied` 且明确提示「数据卷由旧密码初始化」
数据卷密码与当前配置不一致（改了 `.env` 密码但卷没重建）。方案 A：按旧密码重装（install.sh 选「复用已有数据」）；方案 B（**清数据**）：`docker compose --profile <mysql|mariadb|postgres> down -v` 后重装。

### Q：worker 启动失败 / Permission denied 写 instance/
entrypoint 以 root 自愈挂载目录属主（chown 1000:1000）后降权运行；若宿主 `instance/` 被手工 chown 到其他用户，容器重启会自动修正。仍失败时检查 SELinux/挂载参数。

### Q：镜像拉取超时（国内网络）
install.sh 内置多源回退（daocloud → 1ms.run → xuanyuan.me → hub.rat.dev，每站重试 2 次并跳过本地已有镜像）。手动拉取可指定镜像站前缀后 retag。

### Q：健康检查失败（unhealthy）
`docker exec <容器> curl -s http://localhost:5000/healthz` 看返回；常见为数据库未就绪（§8 第一条）或应用异常（§1）。

---

## 9. 备份与恢复

- **内置备份**：后台「备份与恢复」，产物存 `instance/backups/`（含数据库 + uploads）。
- **手动兜底**：数据库 `mysqldump`/`pg_dump`/SQLite 文件复制 + `app/static/uploads/` + `instance/` 目录。
- **恢复后注意**：`alembic_version` 随库走，恢复到旧版本库后直接启动新代码会自动 `upgrade head` 补齐迁移。
- 恢复演练建议每季度一次（详见 wiki「备份与恢复」）。

---

## 10. 快速诊断命令速查

```bash
# 应用存活
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5000/healthz

# 查看当前迁移版本
python -c "
from app import create_app
from sqlalchemy import text
app = create_app()
with app.app_context():
    from app.extensions import db
    print(db.session.execute(text('SELECT version_num FROM alembic_version')).all())
"

# 重建索引 / 修复缓存
后台 → 系统设置：关闭再开启缓存；搜索页 → 重建索引
rm -rf instance/image_cache/*   # 缩略图缓存可安全清空重建

# Docker 常用
docker compose --profile mysql logs -f app
docker compose --profile mysql ps
docker compose --profile mysql down -v   # ⚠️ 清空数据卷
```

> 提交 issue/求助时请附：版本号（后台首页可见）、启动日志最后 50 行、复现步骤。
