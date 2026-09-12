# 主题模板开发 API 文档

> 适用版本：ZhyCMS ≥ 2.6.4　|　配套参考：[插件开发手册](PLUGIN_DEV.md)、`docs/` 目录

前台基于 **Jinja2 + Bootstrap 4.6**，采用「多主题 + 栏目级模板」双层机制。内置 8 套主题：`default` / `blue` / `manufacturing` / `service` / `default_en` / `manufacturing_en` / `education`（v2.6.3）/ `catering`（v2.6.3）。

---

## 1. 机制总览

### 1.1 模板解析链（三级回退）

```
主题覆盖  themes/<active_theme>/<name>.html
   ↓ 不存在
插件自带  plugins/<slug>/templates/<name>.html（如 banner/hero_carousel.html）
   ↓ 不存在
default 主题兜底  themes/default/<name>.html
```

### 1.2 主题目录结构

```
themes/<slug>/
├── manifest.json          # 主题元数据（builtin=true 内置保护）
├── base.html              # 基础布局（必备）
├── index.html             # 首页（必备）
├── list.html              # 列表页默认（必备）
├── article.html           # 文章详情默认（必备）
├── page.html              # 单页默认（必备）
├── 404.html / 500.html    # 错误页（必备）
├── closed.html            # 维护/关闭提示（建议）
├── column_children.html   # 父栏目子列表页（可选）
├── search.html            # 搜索结果页（建议）
├── list_card.html …       # 栏目级备选模板（可选，命名见 §9）
├── css/ js/ images/ fonts/  # 静态资源（仅这四个子目录对外可访问）
└── (其他任意 .html 备选模板)
```

### 1.3 manifest.json 字段

| 字段 | 说明 |
| --- | --- |
| `slug` | 主题标识，**必须与目录名一致** |
| `name` / `version` / `description` / `author` | 展示信息 |
| `builtin` | `true` 为内置主题：禁止覆盖上传与删除 |
| `template_required` | 追加必备模板声明（数组或逗号分隔字符串），与系统必备集合并 |

系统必备模板（7 个）：`index.html list.html article.html page.html base.html 404.html 500.html`。上传/启用前强制检查，任一缺失拒绝启用。

---

## 2. base.html 契约

所有页面通过 `{% extends theme_base %}` 继承当前主题 base.html。base.html 必须提供 **5 个 block**（参考 `themes/default/base.html`）：

```jinja
{% block title %}{{ seo.title }}{% endblock %}      {# <title>，拼接 site_settings.site_name #}
{% block css %}{% endblock %}                        {# 子页附加样式 #}
{% block locale_switcher %}…{% endblock %}           {# 语言切换器（子页可整体替换） #}
{% block content %}{% endblock %}                    {# 页面主体 #}
{% block js %}{% endblock %}                         {# 子页附加脚本 #}
```

标准骨架要素（建议保留）：

| 要素 | 写法 |
| --- | --- |
| 样式 | Bootstrap 4.6.2、Font Awesome 5.15.4、主题 CSS（见 §6.4） |
| SEO meta | `{{ seo.keywords }}` / `{{ seo.description }}` |
| 导航 | 遍历 `nav`（结构见 §5.2），末尾 `{{ member_user_menu() }}` + locale_switcher |
| 搜索框 | `action="{{ url_for('frontend.search') }}" method="get"`，参数名 `q` |
| flash 消息 | `{% with messages = get_flashed_messages(with_categories=true) %}` |
| 统计代码 | `<head>` 内 `{{ analytics_head()|safe }}`、`</body>` 前 `{{ analytics_body()|safe }}` |
| 页脚 | `{{ site_settings.footer_copyright }}` + ICP 碎片（见 §5.3） |

---

## 3. 全局模板变量（每个前台页面自动注入）

| 变量 | 类型 | 说明 |
| --- | --- | --- |
| `site_settings` | dict | 全部站点设置：`site_name` `site_subtitle` `site_logo` `footer_copyright` 等 |
| `site_fragments` | dict | 碎片，键为 slug，取值 `{{ site_fragments.icp.value }}` |
| `nav_columns` | list | 顶层启用栏目树（`Column` 对象） |
| `nav` | list | 当前页导航树（节点结构见 §5.2；list/search/article 页由视图传入） |
| `current_user` | obj | Flask-Login 后台登录用户（前台一般为匿名） |
| `current_theme` | str | 当前主题 slug |
| `theme_base` | str | 当前主题 base.html 路径（`{% extends theme_base %}`） |
| `cms_name` / `cms_copyright` / `cms_version` | str | **CMS 自身标识**（固定常量，仅供后台模板；前台用 `site_settings`） |

---

## 4. Jinja 全局函数

### 4.1 核心函数

| 函数 | 签名 | 说明 |
| --- | --- | --- |
| `url_for` | 标准 Flask | 已补丁：后台 URL 自动跟随自定义前缀 |
| `admin_url_for` | `admin_url_for(endpoint, **values)` | Python/模板生成后台地址（自动拼当前前缀） |
| `frontend_pager_url` | `frontend_pager_url(column, page)` | **列表分页专用**：伪静态开 → `/{slug}.html` `/{slug}-{N}.html`；关 → `/column/{slug}?page=N`。切换设置后链接自动适配 |
| `t` | `t(obj, field)` | 内容级多语言取值，无翻译回退主表（v2.5） |
| `_p` | `_p('<插件slug>', '原文')` | 插件域翻译（v2.3） |
| `_` | Flask-Babel | 核心域翻译 |
| `available_locales()` | → list | 启用的语言列表：`{'code','label','active'}` |
| `current_locale()` | → str | 当前语言代码 |

### 4.2 插件贡献函数（插件禁用时返回安全空值）

| 函数 | 返回 | 说明 |
| --- | --- | --- |
| `banner_items(slug, limit=None)` | list | 指定分组当前生效的轮播图：`[{'title','image_url','link_url','link_target'}]` |
| `member_user_menu()` | HTML | 右上角会员菜单（游客显示登录/注册，会员显示头像下拉）；禁用返回空串 |
| `current_member` | obj/None | 当前登录前台会员 |
| `member_cfg` | str | 会员插件配置片段 |
| `friend_links()` | list | 友情链接 |
| `notices(limit)` / `recruit_jobs(limit, only_open)` / `tutorials(limit)` … | list | 各内容插件模板函数（见各插件文档） |
| `analytics_head()` / `analytics_body()` | HTML | 统计代码位 |
| `auto_translate_assets` | HTML | 翻译资产（语言切换辅助） |

> 主题模板应假设任何插件函数都可能返回空值，用 `{% if … %}` 包裹。

### 4.3 过滤器

| 过滤器 | 示例 | 输出 |
| --- | --- | --- |
| `date` | `{{ a.published_at|date }}` | 2026-08-06（可传 fmt） |
| `datetime` | `{{ a.published_at|datetime }}` | 2026-08-06 22:30:00 |
| `datetime_format` | 同 datetime 别名 | 历史命名兼容 |
| `truncate_text` | `{{ a.summary|truncate_text(80) }}` | 截断加 `...` |
| `highlight` | `{{ r.title|highlight(keyword) }}` | 搜索关键词 `<mark>` 高亮（内部已转义，防 XSS） |
| `status_label` / `filesize` / `op_type_label` / `audit_detail` | 后台模板用 | 状态/文件大小/审计格式化 |

---

## 5. 数据对象与页面上下文

### 5.1 各页面模板收到的变量

| 模板 | 变量 |
| --- | --- |
| `index.html` | `nav` `first_page`（第一个单页栏目） `latest_articles`（`[(column, article)]`） `about_col` `products_col/products` `services_col/services` `news_col/news` `cases_col/cases` `courses_col/courses` `teachers_col/teachers` `campus_news_col/campus_news` `dishes_col/dishes` `food_news_col/food_news` `seo` |
| `list*.html`（列表栏目） | `column` `articles`（当前页文章） `pagination`（Flask-SQLAlchemy 分页对象） `nav` `seo` |
| `page*.html`（单页栏目） | `column`（`page_content|safe` 输出正文） `fields`（自定义字段） `nav` `seo` |
| `column_children.html`（父栏目） | `column` `children` `nav` `seo` |
| `article*.html`（文章详情） | `column` `article` `fields` `latest_articles` `prev_article` `next_article` `nav` `seo` |
| `search.html` | `keyword` `results`（dict 列表，含 `title/summary/url/type…`） `total` `page` `per_page` `nav` `seo` |
| `closed.html`（维护页） | `seo`（状态码 503） |
| `404.html` / `500.html` / `403.html` | 常规全局变量 |

> `seo` 统一为 `{'title','keywords','description'}`，文章页自动带文章 SEO 字段并回退栏目/站点设置。

### 5.2 导航节点结构

`nav` 是树形列表，每个节点 `{'node': Column对象, 'children': [子节点…]}`：

```jinja
{% for node in nav %}
  {% set col = node.node %}
  {% if col.type == 'link' %}
    <a href="{{ col.link_url }}" target="{{ col.link_target }}">{{ col.name }}</a>
  {% elif node.children %}
    …下拉子菜单，子项取 child.node
  {% else %}
    <a href="{{ url_for('frontend.column_detail', slug=col.slug) }}">{{ col.name }}</a>
  {% endif %}
{% endfor %}
```

### 5.3 Column 字段速查

| 字段 | 说明 |
| --- | --- |
| `name` / `slug` / `type` | 名称 / 标识 / 类型（`page` 单页、`list` 列表、`link` 外链） |
| `summary` / `page_content` | 栏目简介 / 单页正文（`|safe` 输出） |
| `parent_id` / `is_parent` / `parent_mode` | 层级与父栏目模式（`first_child` 跳首个子栏目 / `list_children` 列子栏目） |
| `link_url` / `link_target` | 外链地址与打开方式 |
| `page_size` | 列表每页条数（分页 per_page） |
| `list_template` / `detail_template` / `page_template` | 栏目级指定模板 |
| `seo_title` / `seo_keywords` / `seo_description` | 栏目 SEO |
| `member_only` | v2.6.4 会员可见性（仅登录会员可见） |

### 5.4 Article 字段速查

| 字段 | 说明 |
| --- | --- |
| `title` / `summary` / `content` | 标题 / 摘要 / 正文（富文本 `|safe`） |
| `cover` | 封面图（空时主题可用渐变+图标占位） |
| `author` / `source` / `viewed` | 作者 / 来源 / 浏览量 |
| `published_at` / `created_at` / `updated_at` | 时间字段（配 `|date` `|datetime`） |
| `status` | 工作流状态（前台仅返回 `published`） |
| `get_field_value(field_id)` | 自定义字段值（配合 `fields` 遍历：`field.field_key` `field.label` `field.field_type`） |

### 5.5 pagination 对象（Flask-SQLAlchemy）

```jinja
{{ pagination.page }} / {{ pagination.pages }} / {{ pagination.total }}
{{ pagination.has_prev }} / {{ pagination.has_next }}
{% for p in pagination.iter_pages() %}…{% endfor %}   {# 页码序列，None 为省略号 #}
```

分页链接**必须**使用 `frontend_pager_url(column, p)`（自动适配伪静态开关，且缓存按页独立）：

```jinja
{% if pagination.has_prev %}
  <a href="{{ frontend_pager_url(column, pagination.page - 1) }}">上一页</a>
{% endif %}
{% for p in pagination.iter_pages() %}
  {% if p %}
    <a class="{{ 'active' if p == pagination.page }}"
       href="{{ frontend_pager_url(column, p) }}">{{ p }}</a>
  {% else %}
    <span>…</span>
  {% endif %}
{% endfor %}
```

### 5.6 URL 生成规范

```jinja
{# 首页 / 栏目 / 文章（动态路由，始终可用） #}
{{ url_for('frontend.index') }}
{{ url_for('frontend.column_detail', slug=column.slug) }}
{{ url_for('frontend.article_detail', slug=column.slug, aid=article.id) }}
{{ url_for('frontend.search') }}

{# 伪静态开关两种形态（视图已做双向兼容，模板无需关心） #}
/{slug}.html  /{slug}-{N}.html  /article-{id}.html
```

### 5.7 主题静态资源引用

```jinja
<link rel="stylesheet" href="{{ url_for('frontend.theme_asset', slug=current_theme, filename='css/style.css') }}">
<img src="{{ url_for('frontend.theme_asset', slug=current_theme, filename='images/logo.png') }}" alt="">
```

服务端仅放行 `css/ js/ images/ fonts/` 四个子目录，拒绝路径穿越；响应带 1 天浏览器缓存。

---

## 6. i18n 模板规范（v2.3 / v2.5）

| 场景 | 写法 |
| --- | --- |
| 界面文案 | `{{ _('首页') }}`（核心域）或 `{{ _p('member', '登录') }}`（插件域） |
| 内容字段 | `{{ t(article, 'title') }}`、`{{ t(column, 'name') }}` — 无翻译自动回退默认语言 |
| 语言切换器 | `available_locales()` + `current_locale()`（见 base.html 标准实现，切换链接 `{{ request.path }}?lang={{ loc.code }}`） |

> 未启用 i18n 时 `t()` 直接返回主表字段，模板无需判断。

---

## 7. 图片与占位约定

- 封面位逻辑：`{% if a.cover %}<img src="{{ a.cover }}">{% else %}渐变+图标占位{% endif %}`；
- 正文/摘要中的 `<img>` 若无 ALT，视图层自动注入默认 ALT（文章/单页），模板无需处理；
- 富文本输出一律 `|safe`；其他用户可控内容**禁止** `|safe`。

## 8. 缓存注意事项

- 整页缓存开启时，匿名访客的列表/文章页按「页面+参数+语言+主题」缓存，模板内**不要**输出 per-user 内容（登录态内容走 `member_user_menu()` 等独立异步/函数位）；
- 主题切换、发布内容时核心已自动清缓存，主题开发无需处理。

## 9. 栏目级备选模板

在主题目录创建 `list_xxx.html` / `article_xxx.html` / `page_xxx.html`，后台栏目编辑页「模板」下拉自动出现。受保护模板不会被列为备选：`base、404、500、closed、form_closed、index、search、column_children、form`。栏目指定模板在当前主题缺失时自动回退默认模板，不报错。

## 10. 主题打包上传与校验

| 校验 | 规则 |
| --- | --- |
| 格式 | 仅 `.zip` / `.tar.gz` / `.tgz` |
| 必备文件 | `manifest.json` + 7 个必备模板（含 `template_required` 追加项） |
| 安全 | 路径穿越（`../`/绝对路径）拒绝、symlink 跳过、损坏包拒绝 |
| slug | 合法 JSON、slug 匹配正则且与目录名一致 |
| 形态 | 形态 A（根目录即主题）/ 形态 B（单层子目录）自动归一化 |
| 覆盖 | 内置主题（`builtin: true`）禁止覆盖；同名自定义主题需先删除再传，删除需验证码 |
| 启用 | 启用动作写 OP_CONFIG_CHANGE 审计日志，并无条件清空整页缓存 |

## 11. 主题制作检查清单

- [ ] 7 个必备模板齐全，`manifest.json` 的 slug 与目录名一致
- [ ] 所有页面 `{% extends theme_base %}`，base 提供 5 个 block
- [ ] 分页链接统一 `frontend_pager_url(column, p)`
- [ ] 富文本 `|safe`，用户可控字符串不 `|safe`
- [ ] 导航包含 `member_user_menu()` 与语言切换器位
- [ ] 接入 `analytics_head()/analytics_body()`
- [ ] `closed.html` / `search.html` / `403.html` 已适配
- [ ] 伪静态开关两种模式下列表/详情链接均正确
- [ ] 静态资源仅放四个白名单目录
