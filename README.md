

# ZhyCMS

一个基于 Flask 的轻量级企业内容管理系统，内置多主题模板引擎、栏目级模板选择、自定义字段、表单收集、SEO 优化等能力，适合搭建企业官网、资讯门户、产品展示站等。

## 特性一览

- **多主题模板系统**：前台模板按主题组织，后台一键切换。内置 `default`、`blue` 通用聚合主题，以及 `manufacturing`（制造业）、`service`（服务业）两套行业专用主题。
- **演示数据一键生成**：初始化时可选择「制造业」或「服务业」示例，自动生成配套栏目、文章、碎片、友情链接与演示图片，并切换到对应行业主题。
- **CMS 标识与企业标识分离**：后台 CMS 名称/版权固定不可改，前台网站名称/版权可独立配置。
- **栏目级模板选择**：每个栏目可指定独立的列表页/内容页/单页模板，未指定自动回退默认。
- **自定义字段**：栏目和文章支持自定义字段（文本/富文本/图片/文件/URL/数字等）。
- **表单收集**：可视化表单设计，支持文本/手机/邮箱/单选/多选/文件上传，提交数据可导出。
- **SEO 优化**：每个栏目、文章可单独设置 SEO 标题/关键词/描述。
- **安全加固**：支持自定义后台路由前缀（如 `manage-x8y2`），避免后台地址被轻易猜测。

## 快速开始

### 环境要求

- Python 3.9+
- SQLite（默认）或 MySQL/PostgreSQL

### 安装与运行

```bash
# 克隆代码
git clone https://gitee.com/pollybird/zhycms
cd zhycms

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
python run.py
```

浏览器访问 [http://127.0.0.1:5000](http://127.0.0.1:5000)，首次访问会自动跳转到 `/admin/setup` 初始化向导。

### 生产部署

```bash
ZHOCMS_ENV=production ZHOCMS_SECRET_KEY=your-secret python run.py
# 或使用 gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 "run:app"
```

## 目录结构

```
zhycms/
├── app/
│   ├── admin/              # 后台模块（栏目、文章、表单、设置等）
│   ├── frontend/           # 前台模块
│   │   └── templates/
│   │       └── themes/     # 前台主题模板目录
│   │           ├── default/        # 通用聚合主题
│   │           ├── blue/           # 通用聚合主题（蓝色）
│   │           ├── manufacturing/  # 制造业专用主题
│   │           └── service/        # 服务业专用主题
│   ├── models/             # 数据模型 (Article, Column, User, Setting, etc.)
│   ├── utils/              # 工具模块 (主题、上传、验证码、引导程序等)
│   ├── static/             # 静态资源 (uploads/, admin/)
│   ├── __init__.py         # 应用工厂
│   ├── config.py           # 配置
│   └── extensions.py       # 扩展初始化
├── instance/               # 实例数据（数据库、配置等）
├── requirements.txt
└── run.py                  # 启动入口
```

## 核心功能详解

### 演示数据与行业主题

首次访问初始化向导除设置管理员外，可选择生成演示数据：

| 选项 | 生成内容 | 自动切换主题 |
| --- | --- | --- |
| 不生成 | 空站点 | 保持 `default` |
| 制造业 | 机械制造示例：产品中心、新闻中心等 | `manufacturing` |
| 服务业 | 咨询公司示例：服务项目、客户案例等 | `service` |

演示数据位于 `app/utils/bootstrap.py`，生成前会自动清理旧数据。

### CMS 标识与网站标识

系统严格区分「CMS 自身标识」与「前台企业标识」：

| 概念 | 用途 | 可否修改 |
| --- | --- | --- |
| **CMS 名称** | 后台顶栏/登录页 | ❌ 固定为 `钟毓企业网站CMS` |
| **网站名称** | 前台导航/首页 | ✅ 系统设置中可改 |

### 后台安全（自定义后台路由）

后台默认挂载在 `/admin`。为提升安全性，可在 **系统设置 → 后台安全** 中将路由改为任意自定义值（如 `manage-x8y2`）。

**注意**：修改后必须**重启服务**才能生效。忘记路由可删除 `instance/admin_config.json` 恢复默认。

## 模板制作指南

zhycms 前台采用 **多主题 + 栏目级模板** 的双层机制。

### 1. 主题目录结构

主题位于 `app/frontend/templates/themes/<主题名>/`。

必备文件：
- `base.html` (基础布局，必须提供 `title`, `css`, `content`, `js` block)
- `index.html` (首页)
- `list.html` (列表页默认模板)
- `article.html` (文章详情页默认模板)
- `page.html` (单页默认模板)

### 2. 模板继承

所有页面必须通过 `{% extends theme_base %}` 继承当前主题的 `base.html`。

### 3. 栏目级备选模板

在主题目录下创建 `list_xxx.html` 或 `article_xxx.html`，后台栏目编辑时即可选择该模板作为备选。

> 模板制作详情请参考 [app/utils/bootstrap.py](app/utils/bootstrap.py) 及 [app/utils/themes.py](app/utils/themes.py)。

## 许可证

本项目基于 [Apache License 2.0](LICENSE) 开源。