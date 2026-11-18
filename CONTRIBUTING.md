# 贡献指南（Contributing）

感谢你对 **钟毓企业网站 CMS（zhycms）** 的关注！欢迎通过 Issue 报告问题、提交 Pull Request 改进代码或完善文档。

## 开发环境搭建

```bash
# 1. 克隆并创建虚拟环境（Python 3.10+，推荐 3.12）
git clone https://gitee.com/pollybird/zhycms.git
cd zhycms
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 启动开发服务（首次访问 http://127.0.0.1:5000 自动进入 /admin/setup 初始化向导）
python run.py
```

- 默认使用 SQLite（`instance/zhycms.db`），无需额外配置即可开发。
- 如需 MySQL/PostgreSQL：初始化向导中选择，或通过环境变量 `ZHYCMS_DB_URI` 指定（注意前缀是 **ZHYCMS_**，与项目名一致）。
- `instance/` 目录为本地配置（数据库凭据、后台前缀、备份），**不要提交到版本库**。
- 仓库同时托管在 Gitee（主仓库）、GitHub 与 GitCode，提交前请确认目标远程；三个远程的分支保持同步。

## 开发规范

### Python 代码

- 遵循 [PEP 8]；缩进 4 空格，UTF-8 编码。
- **注释与文档字符串使用中文**，与现有代码风格保持一致。
- 路由按蓝图组织（`admin/` 后台、`frontend/` 前台、`api/`），公共工具放 `utils/`，跨模块业务逻辑放 `services/`。
- 数据库模型变更使用 Flask-Migrate：在 `migrations/versions/` 新增迁移文件，文件名遵循 `00xx_vX_Y_Z_描述.py`，并保证 `upgrade()` / `downgrade()` 幂等、可重复执行。

### 模板与前端

- 后台基于 AdminLTE 3（Bootstrap 4），模板位于 `app/admin/templates/admin/`。
- 前台主题位于 `app/frontend/templates/themes/<主题>/`，主题的 CSS、字体等资源随主题目录存放。
- 列表模板分页请使用全局助手 `frontend_pager_url`（兼容伪静态开关）。
- 后台菜单新增项**必须同步加权限过滤**（参考 `app/admin/templates/admin/base.html` 的 `current_user.has_permission` / `has_any_permission` 判据）。

### 硬约束（不可破坏的项目约定）

- CMS 标识常量：`CMS_NAME='钟毓企业网站CMS'`、`CMS_COPYRIGHT`、版本号 `Setting.CMS_VERSION`（改版本只动该常量）。
- `robots.txt` / `sitemap.xml` / `favicon.ico` 必须**豁免**未初始化检测与维护模式拦截。
- 配置项读写一律通过 `Setting`（键名与后台表单字段保持 1:1，新增配置需同步 `Setting.DEFAULTS`、视图保存逻辑与模板字段名）。
- 审计日志的 detail JSON 需要考虑「详情中文化」过滤器（`app/utils/helpers.py` 的 `audit_detail`），新增键请同步补充翻译字典。

### 测试

项目使用 **PyTest** 作为主要回归手段（`unittest.mock` 隔离外部依赖 + Flask `test_client` 真实流程 + 幂等清理）：

```bash
# 全量测试
.venv/bin/python -m pytest tests/ -q

# 单个测试文件 / 单个用例
.venv/bin/python -m pytest tests/test_sites_v328.py -q
.venv/bin/python -m pytest tests/test_sites_v328.py::test_import_new_remaps_and_rewrites -q

# 按标记运行（如站群相关）
.venv/bin/python -m pytest tests/ -m sites -q
```

新增测试请遵循现有模式：使用 `app` / `client` fixture，测试数据带唯一前缀并在清理 fixture 中删除；涉及 Store、邮件、Webhook 等外部调用时使用 `monkeypatch` 替换。

提交 PR 前必须通过以下门禁：

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/check_excepts.py
.venv/bin/python scripts/check_constants.py
.venv/bin/python scripts/check_release.py --version <当前版本>
```

提交功能类 PR 前，请确保涉及的页面手工走通：后台操作 → 前台呈现 → 审计记录详情可读。

## 提交规范

提交信息使用 `<type>: <摘要>` 格式，摘要用中文简述「为什么」。常用 type：

| type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 仅文档变更 |
| `test` | 仅测试变更 |
| `refactor` | 不改变行为的重构 |
| `perf` | 性能优化 |
| `release` | 版本发布（同时更新 `Setting.CMS_VERSION`、README、CHANGELOG，打 tag） |
| `chore` | 依赖/工具等杂项 |

重大变更（数据库结构、配置键、行为变更）请在 `CHANGELOG.md` 顶部新增对应版本段落，并同步相关文档（`README.md` / `wiki.html` / `UPGRADE.md`）。版本号以 `Setting.CMS_VERSION` 为准，发布前用 `python scripts/check_release.py --version <版本>` 校验各处一致。

## Issue 与 Pull Request

1. 报 bug 请附：复现步骤、期望/实际行为、环境（Python/数据库/浏览器）、相关日志。
2. PR 请保持**小而聚焦**——一个 PR 解决一件事；新功能先开 Issue 讨论。
3. PR 描述需说明：改了什么、为什么、如何验证；涉及 UI 的请附截图。

## 许可

提交即表示你同意代码以项目现有许可证发布。
