# 可视化页面构建器（v3.0.0）

ZhyCMS v3.0.0 起内置轻量可视化页面构建器。本文档包含两部分：

1. **用户手册**：运营/编辑如何使用构建器搭建页面；
2. **组件开发 API**：开发者如何自定义组件（主题覆写或插件注册）。

---

## 一、用户手册

### 1. 设计原则：双轨制，老站零风险

- 每个页面有两条渲染路径：**构建器布局**与**手写主题模板**。
- 只有在后台创建并**发布**过构建布局的页面才走构建器；其余页面与升级前完全一致。
- 删除构建记录后页面立即回退到手写模板（首页记录不可删除，可清空布局后发布空页面）。
- 构建器只接管页面**内容区**；header、导航、footer、SEO 基础信息仍由主题与系统设置统一控制。

### 2. 覆盖的页面类型

| 作用域 | 对应页面 | 数据上下文 |
| --- | --- | --- |
| 首页 | `/` | 全站最新文章等 |
| 单页 | `type=page` 的叶子栏目 | 栏目正文、自定义字段 |
| 列表页 | `type=list` 的叶子栏目 | 当前栏目文章、分页 |
| 文章详情页 | 每篇文章 | 文章正文、字段、上下篇、侧栏最新；栏目级布局缺省回退全局默认 |

### 3. 快速上手

1. 后台左侧菜单「**页面构建**」进入页面管理（需要 `builder:manage` 权限）。
2. 在对应分组中新建页面：首页/文章详情为全局页面；单页、列表页选择具体栏目。
3. 进入编辑器后，点击「**载入默认布局**」可得到一份与原手写模板等价的初始布局。
4. 从左侧组件库拖拽组件到中间画布；点击组件后在右侧编辑属性、在图层树中调整结构。
5. 修改会**自动保存草稿**（防抖 800ms）；草稿对前台访客不可见。
6. 点击右上角「**发布**」后布局才上线；每次发布都会生成一条修订记录，可在「修订历史」中一键回滚。
7. 「查看前台」打开线上地址（无已发布布局时显示手写模板）；「预览」始终展示当前草稿。

### 4. 编辑器界面

- **左栏 · 组件库**：按 布局组件 / 基础组件 / 数据组件 三组分类，只显示当前页面作用域允许的组件；插件提供的组件在插件禁用时置灰。
- **中栏 · 画布**：iframe 内是服务端真实渲染的页面（使用当前主题、真实栏目与文章数据），支持桌面 / 平板 / 手机三种宽度预览。组件上可直接拖拽排序、跨容器移动；拖入时显示蓝色插入指示条。
- **右栏 · 属性 + 图层**：
  - 属性表单按组件 Schema 自动生成：文本、多行文本、富文本（CKEditor5）、数字、下拉、开关、颜色、图片（上传复用后台媒体接口）、图标、栏目选择、重复项列表（如轮播图）。
  - 文案类字段支持中/英双语 Tab；开启多语言后访客按当前语言看到对应文案（缺省语言自动回退）。
  - 「可见性」支持按**语言白名单**与**会员限定**控制节点显隐。
  - 图层树展示完整嵌套结构，支持选中、删除、复制、上移/下移。

### 5. 内置组件（24 个）

| 分组 | 组件 |
| --- | --- |
| 布局（6） | section、container、grid-row（行，自动带两列）、grid-col（列）、spacer（间距）、divider（分隔线） |
| 基础（8） | heading（标题）、text（段落）、richtext（富文本）、image（图片）、button（按钮）、icon-box（图标卡）、alert（提示条）、video-embed（视频嵌入） |
| 数据（10） | article-list（文章列表/分页）、article-detail（文章详情）、page-content（单页正文）、breadcrumb（面包屑）、fragment（内容碎片）、carousel（轮播图）、contact-card（联系卡片）、cta-banner（行动横幅）、friend-links（友情链接）、stat-numbers（数字统计） |

数据组件自动适配页面上下文：例如「文章列表」放在列表页并选择「当前栏目（自动）」时，分页、伪静态 URL、缓存键全部沿用系统既有规则，一套布局可复用于多个栏目。

### 6. 权限

| 权限点 | 默认拥有角色 | 能力 |
| --- | --- | --- |
| `builder:manage` | content_auditor、content_editor | 进入构建器、编辑、存草稿、看预览 |
| `builder:publish` | content_auditor | 发布、回滚、删除构建记录 |

创建、发布、回滚、删除均写入系统审计日志（模块：页面构建）。

### 7. 安全与限制

- 布局 JSON 仅存数据库，不生成磁盘文件。
- 服务端对每次保存做 allowlist 校验：组件类型、属性键、枚举值、数字/开关类型、重复项子字段、语言键均须合法。
- 单页三重上限：**嵌套深度 ≤ 8、节点数 ≤ 300、文档体积 ≤ 256KB**。
- 单个组件取数或渲染异常会被隔离：前台跳过该组件，编辑器画布里显示黄色占位并记录日志，不会白屏。
- 插件被禁用后，其组件在前台输出为空、编辑器提示「所属插件未启用」；卸载插件前若仍有页面引用其组件，系统拒绝卸载并列出引用页面。

---

## 二、组件开发 API

### 1. 核心概念

```
布局 JSON（Schema v1）
   └─ 组件注册表（Widget 元数据 + prop_schema）
        └─ 渲染器：节点 → Widget.context() 取数 → Jinja partial
```

- 组件是一个 `Widget` 子类 + 一个 Jinja 模板。
- 模板解析顺序：`themes/<当前主题>/builder/widgets/<type>.html`
  → `builder/widgets/<type>.html`（核心目录或插件模板目录）。
- 核心代码见 `app/builder/`：`registry.py`（注册）、`schema.py`（校验）、
  `renderer.py`（渲染）、`service.py`（发布/修订）、`widgets/`（内置组件）。

### 2. 布局 JSON 结构

```json
{
  "version": 1,
  "root": [
    {
      "id": "a1b2c3d4",
      "type": "section",
      "props": {"fluid": false},
      "visibility": {"locales": ["zh", "en"], "member_only": false},
      "children": [
        {"id": "e5f6g7h8", "type": "heading",
         "props": {"text": {"zh": "你好", "en": "Hello"}, "level": 2},
         "visibility": {}, "children": []}
      ]
    }
  ]
}
```

### 3. Widget 类

```python
from app.builder.registry import Widget
from app.constants import Builder as B

class MyWidget(Widget):
    type = 'my-widget'             # 全局唯一，小写中划线
    label = '我的组件'
    icon = 'fa-star'               # FontAwesome 图标类
    description = ''               # 组件库中的说明
    category = B.CAT_BASIC         # layout / basic / data
    scopes = B.SCOPES              # 或 (B.SCOPE_HOME, B.SCOPE_PAGE)
    allowed_children = ()          # ()叶子；('*',)任意；('grid-col',) 限定
    default_children = 0           # 新建时自动生成几个子组件
    default_props = {'title': '默认标题'}
    prop_schema = [
        {'key': 'title', 'label': '标题', 'type': 'text'},
    ]

    def context(self, node, page_ctx):
        """返回追加进模板上下文的 dict；抛异常会被渲染器隔离。"""
        return {'rows': db_my_rows()}
```

### 4. prop_schema 字段类型

| type | 说明 | 关键属性 |
| --- | --- | --- |
| `text` / `textarea` | 单行/多行文本 | `localized: True` 时编辑器显示中英 Tab，值为 `{'zh','en'}` |
| `richtext` | CKEditor5 富文本（入库净化） | — |
| `number` | 数字 | `min` / `max` / `step` |
| `select` | 下拉 | `options: [['值','显示名'], ...]`（值按字符串双向兼容，数字值 2 与 '2' 等价） |
| `toggle` | 布尔开关 | — |
| `color` | 颜色选择器 | — |
| `image` | 图片上传器（缩略图预览 + 上传/更换/清除，可粘贴外部 URL 兜底；repeater 子项同样支持上传） | — |
| `url` | 链接输入框，附「站内页面快捷选择」下拉（首页/栏目页，选中自动填入 `/column/slug`） | — |
| `icon` | FontAwesome 图标：常用图标预设下拉 + 实时预览，可切「自定义类名」输入 `fab fa-*` / `far fa-*` | — |
| `column` | 栏目选择器（存栏目 id） | — |
| `fragment` | 碎片选择器：下拉列出「碎片管理」中启用的碎片（按分组 optgroup），值存碎片 slug | — |
| `repeater` | 重复项 | `itemLabel`、`fields: [...]`（子字段支持 text/textarea/number/select/toggle/color/image/url） |

### 5. 组件模板可用变量

| 变量 | 说明 |
| --- | --- |
| `props` / `zbw_p('key', default)` | 组件属性 |
| `localized('key', '默认值')` | 取当前语言文案，自动回退 |
| `node` / `preview` / `locale` | 原始节点、是否预览态、当前语言 |
| `node_attrs()` | 输出组件根元素的预览属性（生产态为空串），根元素必须调用 |
| `children_attrs()` | 容器的拖放区域属性；`render_children()` 输出子组件 HTML |
| `render_node(node)` | 渲染指定子节点 |
| `page_ctx` 及页面级变量 | `scope`、`column`、`article`、`articles`、`pagination`、`fields`、`nav`、`seo`、`is_member` 等 |
| 全站变量 | `site_settings`、`site_fragments`、`theme_base`、`nav_columns`、`current_theme` 等（与整页模板一致） |

最小叶子组件模板：

```html
<div class="zbw-my-widget" {{ node_attrs() }}>
  <h3>{{ zbw_p('title') }}</h3>
</div>
```

容器组件模板：

```html
<section class="zbw-section" {{ node_attrs() }}>
  <div class="container" {{ children_attrs() }}>
    {{ render_children() }}
  </div>
</section>
```

> 样式约定：组件结构用 Bootstrap4 工具类，自定义样式统一加 `.zbw-` 前缀，
> 集中在 `app/static/builder/css/widgets.css`；预览态样式在 `preview.css`。

### 6. 两种注册方式

**A. 主题内置（随主题分发）**：直接在 `app/frontend/templates/themes/<theme>/builder/widgets/`
放置与核心组件同名的模板即可覆写渲染；新增组件类型仍需通过插件注册类。

**B. 插件注册（推荐）**：在插件入口实现 `get_builder_widgets()` 返回 Widget 子类列表，
模板放插件 `templates/builder/widgets/`。完整示例与卸载门控说明见
[PLUGIN_DEV.md](PLUGIN_DEV.md) §8.7。

### 7. 服务端 API（`app.builder`）

```python
from app.builder import service, registry, schema

registry.register_widget(MyWidget, owner='core')   # 插件 owner 传插件 slug
registry.get_widget('my-widget')                   # 门控后的组件（未启用返回 None）
registry.widget_catalog(scope='home')              # 编辑器组件库分组

service.get_or_create_page('list', column_id)
service.init_default_layout('list', column_id)     # 载入 fixtures 默认布局
service.save_draft(page, layout, author_id=uid)
service.publish_page(page, layout, note='v1')      # 写修订 + 清整页缓存
service.rollback_revision(page, revision_id)
service.pages_referencing_widget_types(['my-widget'])  # 卸载前引用检查

schema.validate_layout(layout)                     # 非法抛 LayoutError
schema.normalize_layout(raw)                       # 容错规整（丢弃坏节点）
```

### 8. 默认布局 fixtures

`app/builder/fixtures/{home,page,list,article}.json` 是「载入默认布局」使用的
初始布局，修改后请确保：通过 `validate_layout`、节点 id 固定且唯一、
四套作用域与组件 `scopes` 一致，并运行
`pytest tests/test_builder_schema.py tests/test_builder_render.py`。
