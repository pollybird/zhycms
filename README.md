# zhycms

一个基于 Flask 的轻量级内容管理系统，内置多主题模板引擎、栏目级模板选择、自定义字段、表单收集、SEO 优化等能力，适合搭建企业官网、资讯门户、产品展示站等。

## 特性一览

- **多主题模板系统**：前台模板按主题组织，后台一键切换，主题之间互不影响。内置 `default`、`blue` 两套通用聚合主题，以及 `manufacturing`（制造业）、`service`（服务业）两套行业专用主题
- **演示数据一键生成**：初始化时可选择「制造业」或「服务业」示例，自动生成配套栏目、文章、碎片、友情链接与演示图片，并切换到对应行业主题
- **CMS 标识与企业标识分离**：后台 CMS 名称/版权固定不可改，前台网站名称/版权可独立配置（详见下文「CMS 标识与网站标识」）
- **栏目级模板选择**：每个栏目可指定独立的列表页/内容页/单页模板，未指定自动回退默认
- **自定义字段**：栏目和文章支持自定义字段（文本/富文本/图片/文件/URL/数字等）
- **表单收集**：可视化表单设计，支持文本/手机/邮箱/单选/多选/文件上传，提交数据可导出
- **SEO 优化**：每个栏目、文章可单独设置 SEO 标题/关键词/描述
- **碎片管理**：站点公告、联系方式、二维码等内容可后台维护，模板任意调用
- **友情链接**：后台管理，前台侧边栏自动展示
- **图片上传**：内置图片压缩、水印、格式校验、大小限制
- **验证码登录**：后台登录带图形验证码
- **可自定义后台路由**：后台访问前缀默认 `admin`，可在「系统设置 → 后台安全」改为任意值，避免后台地址被轻易猜测（详见下文「后台安全（自定义后台路由）」）
- **首次初始化引导**：全新安装自动跳转初始化向导

## 快速开始

### 环境要求

- Python 3.9+
- SQLite（默认，开箱即用）或 MySQL/PostgreSQL

### 安装与运行

```bash
# 克隆代码
git clone <your-repo-url> zhycms
cd zhycms

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖（国内建议使用镜像源加速）
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
# 清华源：-i https://pypi.tuna.tsinghua.edu.cn/simple

# 启动开发服务器
python run.py
```

> `requirements.txt` 已内置 MySQL 驱动 `PyMySQL` 与 PostgreSQL 驱动 `psycopg2-binary`，
> 初始化时选择对应数据库类型即可，无需额外安装。

浏览器访问 [http://127.0.0.1:5000](http://127.0.0.1:5000)，首次访问会自动跳转到 `/admin/setup` 初始化向导，按提示设置管理员账号即可。

### 生产部署

```bash
ZHOCMS_ENV=production ZHOCMS_SECRET_KEY=your-secret python run.py
# 或使用 gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 "run:app"
```

环境变量说明：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ZHOCMS_ENV` | `development` | 配置模式：`development` / `production` |
| `ZHOCMS_SECRET_KEY` | 内置默认值 | 会话加密密钥，**生产环境必须修改** |
| `ZHOCMS_DB_URI` | `sqlite:///instance/zhycms.db` | 数据库 URI，可换成 MySQL/PostgreSQL |

## 目录结构

```
zhycms/
├── app/
│   ├── admin/              # 后台模块（栏目、文章、表单、设置等）
│   ├── frontend/           # 前台模块（路由与视图）
│   │   └── templates/
│   │       └── themes/     # ★ 前台主题模板目录
│   │           ├── default/        # 通用聚合主题
│   │           ├── blue/           # 通用聚合主题（蓝色）
│   │           ├── manufacturing/  # 制造业行业专用主题（产品置顶）
│   │           └── service/        # 服务业行业专用主题（公司介绍置顶）
│   ├── models/             # 数据模型
│   ├── utils/              # 工具模块（主题、上传、验证码等）
│   ├── static/             # 静态资源（uploads/、admin/）
│   ├── __init__.py         # 应用工厂
│   ├── config.py           # 配置
│   └── extensions.py       # 扩展初始化
├── instance/               # 实例数据（数据库等）
├── requirements.txt
├── run.py                  # 启动入口
└── LICENSE                 # Apache 2.0
```

---

# 演示数据与行业主题

首次访问会进入初始化向导 `/admin/setup`，除设置管理员账号外，还可选择是否生成演示数据：

| 选项 | 生成内容 | 自动切换主题 |
| --- | --- | --- |
| 不生成 | 仅创建管理员，空站点 | 保持 `default` |
| 制造业 | 精密机械制造企业示例：关于我们、产品中心、新闻中心、联系我们等栏目 + 文章 + 碎片 + 友情链接 + 演示图片 | `manufacturing`（产品置顶） |
| 服务业 | 企业管理咨询公司示例：关于我们、服务项目、行业动态、客户案例、联系我们等栏目 + 文章 + 碎片 + 友情链接 + 演示图片 | `service`（公司介绍置顶） |

- 演示数据由 [app/utils/bootstrap.py](app/utils/bootstrap.py) 的 `generate_demo_data(industry)` 生成，制造业调用 `_generate_manufacturing_demo()`，服务业调用 `_generate_service_demo()`。
- 每次生成会先调用 `_clean_demo_data()` 按外键依赖顺序清理旧的演示数据（表单 → 文章 → 栏目 → 碎片 → 友情链接），因此可在两个行业之间反复切换而不会触发 `slug` 唯一约束冲突。
- 演示图片位于 `app/static/uploads/demo/`（制造业 `mfg_*`、服务业 `svc_*`），无需联网即可正常展示。
- 演示数据只写入**前台企业信息**（`site_name`、`site_subtitle`、`footer_copyright`、SEO 等），不会改动后台 CMS 名称与版权。

---

# CMS 标识与网站标识

系统严格区分「CMS 自身标识」与「前台企业标识」四个概念，避免演示数据或用户配置误改后台品牌：

| 概念 | 显示位置 | 取值来源 | 可否修改 |
| --- | --- | --- | --- |
| **CMS 名称** | 后台顶栏 / 登录页 / 后台页面标题 | `Setting.CMS_NAME` 固定常量 | ❌ 不可改 |
| **后台版权** | 后台底部 | `Setting.CMS_COPYRIGHT` 固定常量 | ❌ 不可改 |
| **网站名称** | 前台导航 / 首页 / 页脚 | `Setting 'site_name'`（企业名称） | ✅ 网站设置可改 |
| **前台版权** | 前台底部 | `Setting 'footer_copyright'`（企业版权） | ✅ 网站设置可改 |

- 两个 CMS 固定常量定义在 [app/models/setting.py](app/models/setting.py)（`CMS_NAME` / `CMS_COPYRIGHT`），不落库、不受设置或演示数据影响。
- 应用上下文处理器 [app/__init__.py](app/__init__.py) 将其注入为模板变量 `cms_name` / `cms_copyright`。
- **约定**：后台模板一律使用 `cms_name` / `cms_copyright`，**不得**读取 `site_settings.site_name` / `site_settings.footer_copyright`（那是前台企业信息）；前台模板则相反。

---

# 后台安全（自定义后台路由）

后台默认挂载在 `/admin` 前缀下（登录页 `/admin/login`）。固定且众所周知的后台地址容易被扫描器猜测并针对登录页发起暴力破解，因此系统允许管理员将后台路由前缀改为任意自定义值以增强安全性。

## 使用方法

1. 登录后台，进入 **系统设置 → 后台安全**；
2. 在「后台路由前缀」中填写自定义前缀（如 `manage-x8y2`），保存；
3. **重启服务**后，使用新地址 `/<新前缀>/login` 访问后台，旧地址将失效。

前缀规则：仅允许字母、数字、连字符(`-`)、下划线(`_`)，长度 2-32 位；不能与前台已占用路径（`column`、`article`、`form`、`search`、`captcha` 等）冲突。

## 实现说明

- 前缀落盘到 `instance/admin_config.json`（权限 `600`），与数据库配置 `db_config.json` 采用同一套落盘/容错模式（见 [app/utils/admin_prefix.py](app/utils/admin_prefix.py)）。
- 因 Flask 的 `register_blueprint(url_prefix=...)` 只在应用启动时执行一次，运行中**无法热切换**前缀，故修改后**必须重启服务**才能生效。应用启动时 [app/__init__.py](app/__init__.py) 在注册后台蓝本前读取该前缀。
- 后台所有链接与登录跳转均使用 `url_for('admin.*')` / `url_for('admin_auth.*')` 的 endpoint 名，前缀变化后自动跟随，无需改动任何模板或视图。

## 忘记路由怎么办

若忘记已设置的后台路由，删除服务器上的 `instance/admin_config.json` 文件并重启服务，即可恢复默认的 `/admin`。

---

# 模板制作详解

zhycms 的前台采用 **多主题 + 栏目级模板** 的双层机制，主题可在网站设置一键切换，栏目可单独指定列表/内容/单页模板。模板基于 Jinja2 + Bootstrap 4。

## 1. 主题目录结构

所有主题存放在 `app/frontend/templates/themes/` 下，每个主题是一个独立目录，目录名即主题名：

```
app/frontend/templates/themes/
├── default/                # 默认主题（通用聚合）
│   ├── base.html           # 基础布局（必须）
│   ├── index.html          # 首页（必须）
│   ├── list.html           # 列表页默认模板（必须）
│   ├── article.html        # 文章详情页默认模板（必须）
│   ├── page.html           # 单页默认模板（必须）
│   ├── list_card.html      # 卡片式列表（可选，作为栏目备选模板）
│   ├── column_children.html# 父栏目展示子栏目列表的模板
│   ├── search.html         # 搜索结果页
│   ├── form.html           # 表单提交页
│   ├── form_closed.html    # 表单关闭提示页
│   ├── closed.html         # 站点关闭提示页
│   ├── 404.html            # 404 页面
│   └── 500.html            # 500 页面
├── blue/                   # 通用聚合主题（蓝色，同 default 一套模板）
├── manufacturing/          # 制造业行业专用主题（首页产品置顶）
└── service/                # 服务业行业专用主题（首页公司介绍置顶）
```

> `default` / `blue` 为通用聚合主题，适配任意站点；`manufacturing` / `service` 为随演示数据配套的行业专用主题，首页布局按行业特点定制（制造业突出产品展示，服务业突出公司介绍）。

### 必备模板

每个主题至少包含以下文件，否则切换后会出现 404：

| 文件 | 用途 | 备注 |
| --- | --- | --- |
| `base.html` | 全站基础骨架 | 所有页面通过 `{% extends theme_base %}` 继承 |
| `index.html` | 站点首页 | |
| `list.html` | 列表栏目默认列表页 | 名称固定为 `list` |
| `article.html` | 文章详情默认页 | 名称固定为 `article` |
| `page.html` | 单页栏目默认页 | 名称固定为 `page` |
| `404.html` / `500.html` | 错误页 | |
| `closed.html` | 站点关闭时展示 | |

### 可选模板（栏目级备选）

凡以 `list`、`article`、`page` 开头的 `.html` 文件，会**自动**出现在后台栏目编辑页的下拉选项中：

- `list_xxx.html` → 列表栏目可选用
- `article_xxx.html` → 文章详情页可选用
- `page_xxx.html` → 单页栏目可选用

例如 `list_card.html`（卡片式列表）、`list_image.html`（纯图片列表）、`article_news.html`（新闻专用详情页）都会被自动识别。

### 受保护模板（不会出现在选项中）

以下文件即使以 `list`/`article`/`page` 开头也不会被列为栏目备选，因为它们是系统级模板：

`base`、`404`、`500`、`closed`、`form_closed`、`index`、`search`、`column_children`、`form`

## 2. 创建一个新主题

以创建名为 `green` 的绿色风格主题为例：

### 步骤 1：复制默认主题作为起点

```bash
cp -r app/frontend/templates/themes/default app/frontend/templates/themes/green
```

### 步骤 2：修改 `base.html` 中的样式

编辑 `app/frontend/templates/themes/green/base.html`，修改 `<style>` 块中的 CSS：

```css
/* 主题色：绿色 */
.navbar { background: linear-gradient(135deg, #2e7d32 0%, #1b5e20 100%) !important; }
.footer { background: linear-gradient(135deg, #2e7d32 0%, #1b5e20 100%); color: #e8f5e9; }
.card-header { background: #2e7d32; color: #fff; }
.btn-primary { background-color: #2e7d32; border-color: #2e7d32; }
a { color: #2e7d32; }
a:hover { color: #1b5e20; }
```

### 步骤 3：在后台启用

进入 **后台 → 网站设置 → 前台主题**，下拉框会自动出现 `green` 选项，选中保存即可。

> 主题的发现是**自动**的：扫描 `themes/` 下的所有子目录，无需在代码中注册。

## 3. 模板继承与 `theme_base`

所有页面模板通过 `{% extends theme_base %}` 继承当前主题的 `base.html`，而不是写死路径：

```jinja
{% extends theme_base %}

{% block title %}页面标题{% endblock %}

{% block content %}
  页面内容
{% endblock %}
```

`theme_base` 是由应用上下文处理器注入的变量，值类似 `themes/default/base.html`。这样模板代码无需关心当前是哪个主题，切换主题时自动找到对应的 `base.html`。

### `base.html` 必须提供的 block

| Block 名 | 用途 |
| --- | --- |
| `title` | `<title>` 标签内容 |
| `css` | 页面级 CSS（在 `<head>` 内） |
| `content` | 主体内容 |
| `js` | 页面级 JS（在 `</body>` 前） |

## 4. 全局模板变量

以下变量在所有前台模板中可直接使用（由 [app/__init__.py](app/__init__.py) 的 `context_processor` 注入）：

| 变量 | 类型 | 说明 |
| --- | --- | --- |
| `site_settings` | dict | 站点设置，含**前台企业标识**：`site_name`（网站名称/企业名）、`site_subtitle`、`site_logo`、`footer_copyright`（前台版权/企业版权）等 |
| `site_fragments` | dict | 碎片内容，键为碎片 `slug`，值为 Fragment 对象（访问 `.value`） |
| `nav_columns` | list | 顶层栏目列表 |
| `current_theme` | str | 当前主题名（如 `default`） |
| `theme_base` | str | 当前主题 base 模板路径 |
| `cms_name` | str | **CMS 名称**（固定 `钟毓企业网站CMS`），仅后台使用 |
| `cms_copyright` | str | **后台版权**（固定），仅后台使用 |
| `current_user` | object | 当前登录后台用户（前台一般不使用） |

> **注意**：前台模板展示企业信息用 `site_settings.site_name` / `site_settings.footer_copyright`；后台模板展示 CMS 自身信息用 `cms_name` / `cms_copyright`。两者严格区分，详见「CMS 标识与网站标识」一节。

### 视图函数传入的常用变量

不同路由会额外传入以下变量：

- **首页** `index.html`：`nav`（导航树）、`first_page`（首个单页栏目）、`latest_articles`（最新文章 `[(column, article), ...]`）、`friend_links`、`seo`；行业主题另有 `about_col`（关于我们单页）、`products_col`/`products`（产品，slug=`products`）、`services_col`/`services`（服务项目，slug=`services`）、`news_col`/`news`（新闻，slug=`news`）、`cases_col`/`cases`（客户案例，slug=`cases`）——这些按 slug 约定收集，通用主题未使用则忽略
- **列表页** `list.html` / `list_xxx.html`：`column`、`articles`、`pagination`、`nav`、`seo`
- **文章详情** `article.html` / `article_xxx.html`：`column`、`article`、`fields`（栏目自定义字段）、`latest_articles`、`prev_article`、`next_article`、`nav`、`seo`
- **单页** `page.html` / `page_xxx.html`：`column`、`nav`、`seo`
- **表单** `form.html`：`form`、`fields`、`nav`、`seo`
- **搜索** `search.html`：`keyword`、`results`、`nav`、`seo`
- **父栏目** `column_children.html`：`column`、`children`、`nav`、`seo`

## 5. 常用对象字段速查

### Article（文章）

```jinja
{{ article.title }}
{{ article.summary }}
{{ article.content|safe }}          {# 富文本内容，必须用 safe 过滤器 #}
{{ article.cover }}                 {# 封面图 URL #}
{{ article.author }}
{{ article.source }}
{{ article.viewed }}                {# 浏览次数 #}
{{ article.published_at|date }}      {# 发布日期，格式化 #}
{{ article.published_at|datetime }}  {# 发布日期时间 #}

{# 自定义字段值 #}
{{ article.get_field_value(field_id) }}
```

### Column（栏目）

```jinja
{{ column.name }}
{{ column.slug }}
{{ column.summary }}
{{ column.type }}                   {# list / page / link #}
{{ column.page_content|safe }}       {# 单页栏目的富文本内容 #}
{{ column.page_size }}              {# 列表分页大小 #}
{{ column.list_template }}          {# 指定的列表模板名 #}
{{ column.detail_template }}        {# 指定的内容模板名 #}
{{ column.page_template }}          {# 指定的单页模板名 #}

{# 栏目自定义字段值（单页栏目使用） #}
{% for fv in column.field_values %}
  {{ fv.field.label }}: {{ fv.value }}
{% endfor %}
```

### Pagination（分页对象）

```jinja
{{ pagination.page }}               {# 当前页码 #}
{{ pagination.pages }}              {# 总页数 #}
{{ pagination.has_prev }}           {# 是否有上一页 #}
{{ pagination.has_next }}           {# 是否有下一页 #}
{{ pagination.prev_num }}           {# 上一页页码 #}
{{ pagination.next_num }}           {# 下一页页码 #}

{% for p in pagination.iter_pages(left_edge=1, right_edge=1, left_current=2, right_current=2) %}
  {% if p %}
    <a href="{{ url_for('frontend.column_detail', slug=column.slug, page=p) }}">{{ p }}</a>
  {% else %}
    …
  {% endif %}
{% endfor %}
```

### Fragment（碎片）

```jinja
{# 判断碎片是否存在 #}
{% if site_fragments.contact_phone and site_fragments.contact_phone.value %}
  {{ site_fragments.contact_phone.value }}
{% endif %}

{# 富文本碎片用 safe 过滤器 #}
{{ site_fragments.home_notice.value|safe }}
```

## 6. 常用 URL 生成

```jinja
{# 首页 #}
{{ url_for('frontend.index') }}

{# 栏目页 #}
{{ url_for('frontend.column_detail', slug=column.slug) }}
{# 带分页参数 #}
{{ url_for('frontend.column_detail', slug=column.slug, page=2) }}

{# 文章详情页 #}
{{ url_for('frontend.article_detail', slug=column.slug, aid=article.id) }}

{# 表单页 #}
{{ url_for('frontend.form_submit', slug=form.slug) }}

{# 搜索页 #}
{{ url_for('frontend.search') }}
```

## 7. 自定义过滤器

系统注册了以下自定义过滤器（见 [app/utils/helpers.py](app/utils/helpers.py)）：

| 过滤器 | 用途 | 示例 |
| --- | --- | --- |
| `date` | 格式化日期 | `{{ article.published_at|date }}` → `2026-08-04` |
| `datetime` | 格式化日期时间 | `{{ article.published_at|datetime }}` → `2026-08-04 22:30` |
| `truncate_text` | 截断文本 | `{{ article.summary|truncate_text(80) }}` |

## 8. 制作栏目级备选模板

这是 zhycms 的核心特性之一。以制作一个「卡片式列表模板」为例：

### 步骤 1：在主题目录下创建 `list_card.html`

文件名必须以 `list` 开头，否则不会被识别为列表页模板：

```bash
touch app/frontend/templates/themes/default/list_card.html
```

### 步骤 2：编写模板内容

```jinja
{% extends theme_base %}

{% block title %}{{ column.name }}{% endblock %}

{% block content %}
<nav aria-label="breadcrumb">
  <ol class="breadcrumb">
    <li class="breadcrumb-item"><a href="{{ url_for('frontend.index') }}">首页</a></li>
    <li class="breadcrumb-item active">{{ column.name }}</li>
  </ol>
</nav>

<h1>{{ column.name }}</h1>
{% if column.summary %}<p class="text-muted">{{ column.summary }}</p>{% endif %}
<hr>

{% if articles %}
<div class="row row-cols-1 row-cols-md-3 g-4">
  {% for a in articles %}
  <div class="col">
    <a href="{{ url_for('frontend.article_detail', slug=column.slug, aid=a.id) }}"
       class="card h-100 text-decoration-none text-dark">
      {% if a.cover %}
        <img src="{{ a.cover }}" class="card-img-top" style="height:180px;object-fit:cover;">
      {% endif %}
      <div class="card-body">
        <h5 class="card-title">{{ a.title }}</h5>
        <p class="card-text text-muted small">{{ a.summary|truncate_text(60) }}</p>
      </div>
      <div class="card-footer bg-transparent">
        <small class="text-muted">{{ a.published_at|date }}</small>
      </div>
    </a>
  </div>
  {% endfor %}
</div>

{# 分页 #}
{% if pagination.pages > 1 %}
<nav>
  <ul class="pagination justify-content-center">
    <li class="page-item {{ 'disabled' if not pagination.has_prev }}">
      <a class="page-link" href="{{ url_for('frontend.column_detail', slug=column.slug, page=pagination.prev_num or 1) }}">&laquo;</a>
    </li>
    {% for p in pagination.iter_pages() %}
      {% if p %}
      <li class="page-item {{ 'active' if p == pagination.page }}">
        <a class="page-link" href="{{ url_for('frontend.column_detail', slug=column.slug, page=p) }}">{{ p }}</a>
      </li>
      {% else %}
      <li class="page-item disabled"><span class="page-link">…</span></li>
      {% endif %}
    {% endfor %}
    <li class="page-item {{ 'disabled' if not pagination.has_next }}">
      <a class="page-link" href="{{ url_for('frontend.column_detail', slug=column.slug, page=pagination.next_num or pagination.page) }}">&raquo;</a>
    </li>
  </ul>
</nav>
{% endif %}

{% else %}
<div class="text-center text-muted py-5">暂无内容</div>
{% endif %}
{% endblock %}
```

### 步骤 3：在后台栏目中选用

进入 **后台 → 栏目管理 → 编辑某栏目**，「模板设置」区块的「列表页模板」下拉框中会出现 `list_card` 选项（与默认的 `list` 并列）。选中保存后，该栏目前台列表页将使用卡片样式。

### 文件名前缀对应规则

| 前缀 | 对应栏目模板类型 | 出现在栏目表单的位置 |
| --- | --- | --- |
| `list_*` | 列表页模板 | 列表栏目的「列表页模板」下拉 |
| `article_*` | 内容页模板 | 列表栏目的「内容页模板」下拉 |
| `page_*` | 单页模板 | 单页栏目的「单页模板」下拉 |

> 若栏目指定的模板在当前主题中不存在（如切换主题后新主题没有该模板），系统会**自动回退**到默认模板（`list` / `article` / `page`），不会报错。

## 9. 完整模板示例：文章详情页

```jinja
{% extends theme_base %}

{% block title %}{{ article.title }} - {{ column.name }}{% endblock %}

{% block content %}
<ol class="breadcrumb">
  <li class="breadcrumb-item"><a href="{{ url_for('frontend.index') }}">首页</a></li>
  <li class="breadcrumb-item"><a href="{{ url_for('frontend.column_detail', slug=column.slug) }}">{{ column.name }}</a></li>
  <li class="breadcrumb-item active">{{ article.title|truncate_text(30) }}</li>
</ol>

<article class="row">
  <div class="col-md-9">
    <h1>{{ article.title }}</h1>

    <div class="text-muted mb-3">
      <span><i class="far fa-clock"></i> {{ article.published_at|datetime }}</span>
      {% if article.author %}<span class="ml-3">{{ article.author }}</span>{% endif %}
      <span class="ml-3">{{ article.viewed }} 浏览</span>
    </div>

    {# 文章正文 #}
    <div class="article-content">
      {{ article.content|safe }}
    </div>

    {# 自定义字段 #}
    {% if fields %}
    <hr>
    <table class="table">
      {% for f in fields %}
        {% set val = article.get_field_value(f.id) %}
        {% if val %}
        <tr>
          <th width="120">{{ f.label }}</th>
          <td>
            {% if f.field_type == 'image' %}<img src="{{ val }}" class="img-fluid">
            {% elif f.field_type == 'file' %}<a href="{{ val }}">下载</a>
            {% elif f.field_type == 'url' %}<a href="{{ val }}" target="_blank">{{ val }}</a>
            {% elif f.field_type == 'richtext' %}{{ val|safe }}
            {% else %}{{ val }}
            {% endif %}
          </td>
        </tr>
        {% endif %}
      {% endfor %}
    </table>
    {% endif %}

    {# 上一篇/下一篇 #}
    <div class="row mt-4">
      <div class="col-6">
        {% if prev_article %}
        <a href="{{ url_for('frontend.article_detail', slug=column.slug, aid=prev_article.id) }}"
           class="btn btn-outline-secondary btn-block text-left">
          <small>上一篇</small><br>{{ prev_article.title|truncate_text(20) }}
        </a>
        {% endif %}
      </div>
      <div class="col-6">
        {% if next_article %}
        <a href="{{ url_for('frontend.article_detail', slug=column.slug, aid=next_article.id) }}"
           class="btn btn-outline-secondary btn-block text-right">
          <small>下一篇</small><br>{{ next_article.title|truncate_text(20) }}
        </a>
        {% endif %}
      </div>
    </div>
  </div>

  {# 侧边栏：最新文章 #}
  <div class="col-md-3">
    <div class="card">
      <div class="card-header">最新文章</div>
      <div class="list-group list-group-flush">
        {% for a in latest_articles %}
        <a href="{{ url_for('frontend.article_detail', slug=column.slug, aid=a.id) }}"
           class="list-group-item list-group-item-action {{ 'active' if a.id == article.id }}">
          {{ a.title|truncate_text(25) }}
        </a>
        {% endfor %}
      </div>
    </div>
  </div>
</article>
{% endblock %}
```

## 10. 静态资源

主题若需要独立的 CSS/JS/图片资源，建议放在 `app/static/themes/<主题名>/` 下，模板中通过 `url_for` 引用：

```jinja
<link rel="stylesheet" href="{{ url_for('static', filename='themes/green/style.css') }}">
<script src="{{ url_for('static', filename='themes/green/theme.js') }}"></script>
```

上传文件统一存放在 `app/static/uploads/`，URL 由系统自动生成。

## 11. 模板制作检查清单

完成一个新主题后，按以下清单检查：

- [ ] 目录 `app/frontend/templates/themes/<主题名>/` 已创建
- [ ] 包含必备文件：`base.html`、`index.html`、`list.html`、`article.html`、`page.html`、`404.html`、`500.html`、`closed.html`
- [ ] 所有页面通过 `{% extends theme_base %}` 继承（不要硬编码主题路径）
- [ ] `base.html` 提供 `title` / `css` / `content` / `js` 四个 block
- [ ] 富文本内容使用 `|safe` 过滤器（`article.content`、`column.page_content`、碎片 value 等）
- [ ] 列表页、文章页的分页链接正确使用 `pagination` 对象
- [ ] 后台「网站设置 → 前台主题」下拉框能看到新主题
- [ ] 切换到新主题后，前台首页、栏目页、文章页、单页、404 均能正常访问
- [ ] 自定义字段在文章详情页和单页中正确渲染（按 `field_type` 区分图片/文件/URL/富文本）

## 12. 调试技巧

- **开启调试模式**：`python run.py` 默认开启 DEBUG，模板修改会自动重载
- **查看当前主题**：在任意模板中输出 `{{ current_theme }}` 验证
- **查看可用模板**：在 Python Shell 中执行：
  ```python
  from app import create_app
  from app.utils.themes import list_themes, list_theme_templates
  app = create_app()
  with app.app_context():
      print(list_themes())
      print(list_theme_templates(category='list'))
  ```
- **模板找不到报错**：检查文件名是否准确（区分大小写），以及是否放在正确的主题目录下

---

## 许可证

本项目基于 [Apache License 2.0](LICENSE) 开源。

Copyright 2026 zhycms

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
