# 贡献指南（Contributing）

感谢你对 **钟毓企业网站 CMS（zhycms）** 的关注！欢迎通过 Issue 报告问题、提交 Pull Request 改进代码或完善文档。

## 开发环境搭建

```bash
# 1. 克隆并创建虚拟环境（Python 3.9+，推荐 3.12）
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

## 开发规范

### Python 代码

- 遵循 [PEP 8]；缩进 4 空格，UTF-8 编码。
- **注释与文档字符串使用中文**，与现有代码风格保持一致。
- 路由按蓝图组织（`admin/` 后台、`frontend/` 前台、`api/`），公共工具放 `utils/`。
- 数据库模型变更需同步考虑 `scripts/` 下的迁移脚本兼容性（幂等、可重复执行）。

### 模板与前端

- 后台基于 AdminLTE 3.2（Bootstrap 4），前台主题位于 `app/templates/themes/` 与 `app/static/themes/`。
- 列表模板分页请使用全局助手 `frontend_pager_url`（兼容伪静态开关）。
- 后台菜单新增项**必须同步加权限过滤**（参考 `app/admin/templates/admin/base.html` 的 `current_user.has_permission` / `has_any_permission` 判据）。

### 硬约束（不可破坏的项目约定）

- CMS 标识常量：`CMS_NAME='钟毓企业网站CMS'`、`CMS_COPYRIGHT`、版本号 `Setting.CMS_VERSION`（改版本只动该常量）。
- `robots.txt` / `sitemap.xml` / `favicon.ico` 必须**豁免**未初始化检测与维护模式拦截。
- 配置项读写一律通过 `Setting`（键名与后台表单字段保持 1:1，新增配置需同步 `Setting.DEFAULTS`、视图保存逻辑与模板字段名）。
- 审计日志的 detail JSON 需要考虑「详情中文化」过滤器（`app/utils/helpers.py` 的 `audit_detail`），新增键请同步补充翻译字典。

### 测试

项目以**端到端验证脚本**为主要回归手段（`unittest.mock` 隔离外部依赖 + Flask `test_client` 真实流程 + 幂等清理）：

```python
# 参考模式（pytest 兼容亦可）：
# 1. create_app() 真实应用
# 2. test_client 登录/前台提交流程
# 3. mock smtplib / requests.post 等外部调用
# 4. finally 中还原全部被改动的 Setting / 删除测试数据
```

提交功能类 PR 前，请确保涉及的页面手工走通：后台操作 → 前台呈现 → 审计记录详情可读。

## 提交规范

提交信息使用 `<type>: <摘要>` 格式，摘要用中文简述「为什么」。常用 type：

| type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `release` | 版本发布（同时更新 `Setting.CMS_VERSION`、README、CHANGELOG，打 tag） |
| `chore` | 依赖/工具/文档等杂项 |

重大变更（数据库结构、配置键、行为变更）请同步更新 `CHANGELOG.md` 的 `[Unreleased]` 段落与相关文档（`README.md` / `wiki.html` / `UPGRADE.md`）。

## Issue 与 Pull Request

1. 报 bug 请附：复现步骤、期望/实际行为、环境（Python/数据库/浏览器）、相关日志。
2. PR 请保持**小而聚焦**——一个 PR 解决一件事；新功能先开 Issue 讨论。
3. PR 描述需说明：改了什么、为什么、如何验证；涉及 UI 的请附截图。

## 许可

提交即表示你同意代码以项目现有许可证发布。
