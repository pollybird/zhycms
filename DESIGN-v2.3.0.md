# ZhyCMS v2.3.0 设计规划

> 版本：v2.3.0 ｜ 状态：规划中 ｜ 日期：2026-09-01
> 依据：v2.2.0 插件优先架构（[README.md](README.md) §v2.2.0 更新内容）之上的三大特性扩展
> 参考实现：v2.2.0 将「友情链接」由核心转为内置插件的完整迁移（[plugins/friend_link](plugins/friend_link)）作为特性三的样板

---

## 一、版本概览

### 1.1 三大特性

| # | 特性 | 一句话定位 | 主要落点 |
| --- | --- | --- | --- |
| 1 | 国际化（i18n） | 基于 Flask-Babel 实现中英文自由切换，可扩展多语种 | `app/` 全局 + 全部模板 |
| 2 | 第三方统计可视化插件 | 百度统计 / Google Analytics / 站长工具等代码嵌入，后台配置即时生效 | 新增 `plugins/analytics/` |
| 3 | 自定义表单插件化 | 将自定义表单从核心功能转为内置插件（参照 v2.2.0 友情链接迁移） | 新增 `plugins/form/`，瘦身 `app/` |

### 1.2 兼容性原则

- **无破坏性数据库结构变更**：特性三沿用 v2.2.0 友情链接迁移策略——表名、审计模块代码、后台路由路径、设置键全部保持不变，老站数据与历史审计日志无缝保留。
- **老站升级即生效**：升级后首次启动自动启用表单插件一次（标记位门控），无需手工操作。
- **新装站点**：初始化向导写入迁移标记，表单插件按勾选状态启用，与既有插件流程一致。
- **i18n 默认不改变现有行为**：默认 locale 为 `zh`，未启用多语种时前台渲染与 v2.2.0 完全一致。

---

## 二、特性一：国际化（Flask-Babel）

### 2.1 设计目标

- 中英文自由切换：前台 + 后台均支持。
- 可扩展多语种：新增语种仅需追加翻译目录 + 编译，无需改代码。
- 切换方式：URL 参数 / 会话 / Cookie / Accept-Language 自动检测，可配置。
- 后台可视化配置默认语种与可用语种清单。

### 2.2 技术方案

#### 2.2.1 依赖与初始化

- `requirements.txt` 新增：`Flask-Babel>=4.0,<5.0`
- [app/extensions.py](app/extensions.py) 新增 `babel = Babel()`
- [app/__init__.py](app/__init__.py) `create_app()` 中在 `db/login_manager/cache` 之后、注册蓝图之前 `babel.init_app(app)`，并注册 `localeselector`。

#### 2.2.2 Locale 选择优先级

```python
@babel.localeselector
def select_locale():
    from flask import request, session, g
    from .models.setting import Setting
    available = (Setting.get('i18n_available_locales') or 'zh').split(',')
    # 1. URL ?lang=en  （一次性，写回 session）
    # 2. session['locale']
    # 3. cookie 'locale'
    # 4. Accept-Language 头自动匹配 available
    # 5. Setting.get('i18n_default_locale') 兜底 'zh'
```

> locale 代码约定：`zh`（中文，默认）、`en`（英文）。扩展如 `ja`/`ko` 仅需追加翻译。

#### 2.2.3 翻译文件结构

```
app/
├── translations/
│   ├── messages.pot          # 模板（提取产物）
│   ├── zh/LC_MESSAGES/
│   │   ├── messages.po       # 中文源翻译（占位/同义校对）
│   │   └── messages.mo       # 编译产物
│   └── en/LC_MESSAGES/
│       ├── messages.po
│       └── messages.mo
└── babel.cfg                 # 提取配置（jinja2 + python）
```

`babel.cfg` 关键内容：

```ini
[python: app/**.py]
[jinja2: app/**/templates/**.html]
extensions=jinja2.ext.autoescape,jinja2.ext.with_
```

#### 2.2.4 设置项（Setting 模型）

在 [app/models/setting.py](app/models/setting.py) 默认配置区追加：

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `i18n_enable` | `0` | 国际化总开关；关闭时全站按默认中文渲染，不读 `.mo` |
| `i18n_default_locale` | `zh` | 默认语种 |
| `i18n_available_locales` | `zh` | 可用语种清单（逗号分隔），如 `zh,en` |

新增后台「系统设置 → 国际化」页（权限 `system:settings`），可视化配置上述三项，改动写入审计。

#### 2.2.5 语言切换器

- **后台**：顶栏新增语种下拉，提交到 `/admin/set-locale?lang=xx&next=...`，写入 session 后重定向回 `next`。
- **前台**：主题 `base.html` 新增 `{% block locale_switcher %}`，由 `available_locales()` 全局函数渲染下拉；未启用 i18n 时该区块为空。
- 切换路由归属核心（非插件），因为 i18n 是核心能力。

#### 2.2.6 模板全局函数

在 [app/__init__.py:400-408](app/__init__.py) 的 `register_template_filters` 处或 context_processor 注入：

- `_`（Flask-Babel 自动注入 `gettext` 为 `_`，无需手工注册）
- `available_locales()`：返回 `[{code, label}]` 供切换器渲染
- `current_locale()`：当前 locale 代码

#### 2.2.7 提取与编译流程

```bash
# 提取（更新模板）
pybabel extract -F babel.cfg -o app/translations/messages.pot app/
# 新增语种
pybabel init -i messages.pot -d app/translations -l en
# 更新翻译
pybabel update -i messages.pot -d app/translations
# 编译（部署前必做）
pybabel compile -d app/translations
```

> `.mo` 文件不入版本库（加入 `.gitignore`），由部署/构建步骤编译；开发期可临时提交以便首次运行。

### 2.3 工作量与分阶段

i18n 是本版本最大工作量项，按层分阶段：

| 阶段 | 范围 | 说明 |
| --- | --- | --- |
| A 基础设施 | Babel 接线、localeselector、设置页、切换器、`babel.cfg` | 跑通 `_('测试')` 输出中文 |
| B 后台文案 | [app/admin/templates/admin/**](app/admin/templates) 全部模板 + [app/admin/**.py](app/admin) 视图内中文 | 工作量最大，逐模块标记 |
| C 前台主题 | 4 套主题（default/blue/manufacturing/service）`base.html` 及派生模板 | 主题间文案重叠度高，可批量 |
| D 编译验证 | `pybabel compile`，中英文切换走查 | 验收 |

### 2.4 风险与对策

- **遗漏字符串**：以 `pybabel extract` 报告的未标记项为验收依据，CI 增加提取差异检查。
- **插件文案**：插件自身的模板字符串不在核心 `messages.pot` 提取范围。约定**插件自带翻译目录** `plugins/<slug>/translations/`，在插件加载时通过 `babel.list_translations` 合并；首版可暂不要求插件 i18n，仅核心 + 主题先做。
- **数据库中文数据**：内容（栏目名、文章标题等动态数据）不在 i18n 范围，仅界面文案国际化；文档中明确说明。

---

## 三、特性二：第三方统计代码插件

### 3.1 设计目标

- 支持百度统计、Google Analytics、站长工具（cnzz/51la 等）及自定义代码嵌入。
- 后台单独配置模块，保存后前台自动生效（无需重启）。
- 作为内置插件，遵循 v2.2.0 插件机制，可一键启停、卸载。

### 3.2 插件结构

新增 `plugins/analytics/`：

```
plugins/analytics/
├── manifest.json          # builtin: true, min_core_version: 2.3.0
├── __init__.py            # AnalyticsPlugin(PluginBase) 实例 plugin
├── models.py              # AnalyticsConfig（或直接用 Setting 存）
├── admin.py               # @admin_bp.route('/analytics') 配置页
├── frontend.py            # analytics_head()/analytics_body() 注入函数
└── templates/
    └── analytics/
        └── settings.html   # 后台配置页
```

### 3.3 数据与设置

采用 Setting 键值存储（不建表，零迁移）：

| 键 | 说明 |
| --- | --- |
| `analytics_baidu` | 百度统计代码（JS 片段，含 `<script>`） |
| `analytics_google` | Google Analytics 代码（GA4 `<script>`） |
| `analytics_webmaster` | 站长工具代码（cnzz/51la 等） |
| `analytics_custom_head` | 自定义 `</head>` 前注入代码 |
| `analytics_custom_body` | 自定义 `</body>` 前注入代码 |
| `analytics_enable` | 总开关（0/1） |

> 权限点：`analytics:manage`（沿用友情链接策略——仅系统设置类角色默认可管，可向自定义角色授权）。
> 审计模块：`[('analytics', '统计代码')]`。

### 3.4 后台配置页

- 路由：`@admin_bp.route('/analytics')`，挂在核心 admin 蓝本，路径 `/<admin前缀>/analytics`。
- 页面：多文本域（带 `monospace`），每个服务商一框，保存即写 Setting 并记审计。
- **即时生效**：保存后 `Setting.set(...)` + `db.session.commit()`，下一次前台请求即读到新值（Setting 无服务级缓存，符合「保存即生效」语义）。

### 3.5 前台注入机制（关键设计决策）

**选定方案：插件 Jinja 全局函数 + 主题 `base.html` 注入点**，与 v2.2.0 友情链接 `friend_links()` 模板函数模式完全一致，零侵入核心。

#### 实现要点

1. 插件 `get_jinja_globals()` 返回：
   ```python
   {'analytics_head': analytics_head, 'analytics_body': analytics_body}
   ```
2. 插件 `get_jinja_fallbacks()` 返回：
   ```python
   {'analytics_head': '', 'analytics_body': ''}
   ```
   —— 核心自动包裹「插件启用守卫」（[app/plugin_system.py:134-163](app/plugin_system.py)），未启用时返回空串，模板调用零报错。
3. 在 4 套主题 `base.html` 中新增两个注入点：
   - `</head>` 前：`{{ analytics_head()|safe }}`
   - `</body>` 前（现有 `{% block js %}` 之后）：`{{ analytics_body()|safe }}`

#### 函数实现

```python
def analytics_head():
    from app.models.setting import Setting
    if Setting.get('analytics_enable') != '1':
        return ''
    parts = [Setting.get('analytics_google') or '',
             Setting.get('analytics_baidu') or '',
             Setting.get('analytics_custom_head') or '']
    return ''.join(p for p in parts if p.strip())

def analytics_body():
    from app.models.setting import Setting
    if Setting.get('analytics_enable') != '1':
        return ''
    return Setting.get('analytics_custom_body') or ''
```

#### 备选方案（未采纳，记录权衡）

- `app.after_request` 响应体重写注入：优点是零模板改动、跨未来主题通用；缺点是需正则定位 `</head>`/`</body>`、对非 HTML 响应需过滤、且 `PluginBase` 当前无 `after_request` 钩子（要扩展插件 API，对核心有侵入）。若后续多主题激增可重新评估。

### 3.6 支持的统计服务

| 服务商 | 注入位置 | 说明 |
| --- | --- | --- |
| 百度统计 | head | 官方建议放 head，账号 token 内嵌 |
| Google Analytics 4 | head | GA4 推荐 head，含 `<script>` 与配置 |
| 站长工具（cnzz/51la） | head/body 自适应 | 直接粘贴官方代码 |
| 自定义 head/body | 分离 | 任意第三方/埋点/像素代码 |

### 3.7 安全考虑

- 配置页输入为 JS 代码，**仅超级管理员或被显式授权 `analytics:manage` 的角色可编辑**。
- 渲染一律 `|safe`（统计代码本就是可执行 JS，无需转义），但保存时校验长度上限与基础黑白名单（拒绝含 `<script src=//已知恶意域名>` 的明显异常，可后续迭代）。
- 后台路径受自定义后台路由前缀保护（与友情链接一致）。
- 注入仅作用于前台主题页面，**不注入后台管理页**（避免后台流量污染统计）。

---

## 四、特性三：自定义表单插件化

### 4.1 设计目标与迁移原则

**目标**：将自定义表单（表单设计 + 前台提交 + 通知 + 后台管理 + 演示数据）从核心迁出为内置插件 `plugins/form/`，完全复刻 v2.2.0 友情链接迁移模式。

**迁移四原则**（来自 [plugins/friend_link/__init__.py:13-17](plugins/friend_link/__init__.py) 注释）：

1. 表名不变 → 老站数据无缝保留
2. 审计模块代码不变 → 历史审计日志正常翻译显示
3. 后台路由路径不变 → 收藏夹/书签不失效
4. 设置键不变 → 通知配置无缝保留

### 4.2 现状清单（要从核心搬走的内容）

经核查，当前核心表单相关代码分布如下：

| 层 | 文件:行 | 内容 |
| --- | --- | --- |
| 模型 | [app/models/form.py:7-31](app/models/form.py) | `Form`（表 `forms`） |
| 模型 | [app/models/form.py:34-70](app/models/form.py) | `FormField`（表 `form_fields`） |
| 模型 | [app/models/form.py:73-105](app/models/form.py) | `FormSubmission` / `FormSubmissionValue`（表 `form_submissions` / `form_submission_values`） |
| 后台视图 | [app/admin/form.py:41-109](app/admin/form.py) | `@admin_bp.route('/forms')` 列表/创建/编辑，权限 `form:view`/`form:manage` |
| 后台视图 | [app/admin/form.py:191-323](app/admin/form.py) | 删除/提交记录/批量操作/导出 Excel，审计 `MODULE_FORM`/`MODULE_FORM_SUBMISSION` |
| 前台提交 | [app/frontend/views.py:447-552](app/frontend/views.py) | `/form/<slug>` 提交入口（校验/保存/通知/跳转） |
| 通知 | [app/utils/notify_utils.py:17-176](app/utils/notify_utils.py) | `notify_form_submission()` + 邮件/企业微信发送实现 |
| 设置默认 | [app/models/setting.py:63-77](app/models/setting.py) | `form_notify_enable`/`form_notify_channels`/SMTP/Webhook 默认值 |
| 设置页 | [app/admin/setting.py:317-364](app/admin/setting.py) | 「消息通知」页表单通知开关/渠道/SMTP/收件人 |
| 演示数据 | [app/utils/bootstrap.py:787-816](app/utils/bootstrap.py) | 初始化向导生成的默认表单及字段 |
| 模板 | `app/admin/templates/admin/form/**` | 后台表单管理页模板（待迁移到插件目录） |
| 模板 | 前台表单渲染模板（如有） | 前台提交表单展示 |
| 邮件模板 | `app/**/templates/**notify**` | 表单提交通知邮件 HTML 模板 |

### 4.3 插件目录结构

```
plugins/form/
├── manifest.json
├── __init__.py            # FormPlugin(PluginBase) 实例 plugin
├── models.py              # Form/FormField/FormSubmission/FormSubmissionValue（表名不变）
├── admin.py               # @admin_bp.route('/forms') 等（路径不变，_gate 守卫）
├── frontend.py            # 前台蓝本：/form/<slug> 提交路由 + 模板函数
├── notify.py              # notify_form_submission()（从 notify_utils 迁入）
├── demo.py                # generate(industry) 演示数据
├── audit.py               # MODULE_FORM/MODULE_FORM_SUBMISSION 常量（沿用代码值）
└── templates/
    ├── admin/form/        # 后台管理页模板（从 app/admin/templates/admin/form/ 迁入）
    └── ...                # 前台/邮件模板
```

#### manifest.json

```json
{
  "slug": "form",
  "name": "自定义表单",
  "version": "1.0.0",
  "description": "可视化表单设计与提交收集：字段类型/验证/文件上传/提交记录导出/邮件·企业微信通知；v2.3.0 起由核心功能转为内置插件，老站数据无缝保留",
  "author": "ZhyCMS 官方",
  "builtin": true,
  "min_core_version": "2.3.0"
}
```

#### Plugin 类（骨架）

```python
class FormPlugin(PluginBase):
    slug = 'form'
    name = '自定义表单'
    version = '1.0.0'
    description = '...（同 manifest）'
    author = 'ZhyCMS 官方'

    permissions = [
        ('form:manage', '表单管理', '表单的增删改与提交记录管理'),
        ('form:view', '表单查看', '查看表单与导出提交记录'),
    ]
    preset_role_grants = {}   # 沿用核心时代：不向内容角色默认授权
    audit_modules = [('form', '表单'), ('form_submission', '表单提交')]

    def get_admin_menu(self):
        return [
            {'label': '自定义表单', 'endpoint': 'admin.form_index',
             'icon': 'fa-wpforms', 'permission': 'form:view',
             'active_prefix': 'form'},
        ]

    def get_frontend_blueprint(self):
        from flask import Blueprint
        return Blueprint('form_frontend', __name__,
                         template_folder='templates')

    # get_jinja_globals: 视前台模板是否需要表单辅助函数决定
    # get_jinja_fallbacks: 对应空值
    # generate_demo_data: 调用 demo.generate(industry)

plugin = FormPlugin()
```

### 4.4 迁移兼容（关键）

| 项 | 兼容措施 |
| --- | --- |
| **表名** | `__tablename__` 保持 `forms`/`form_fields`/`form_submissions`/`form_submission_values` 不变 → `db.create_all()` 兜底建表，老数据原地可用 |
| **审计模块代码** | `audit_modules` 声明 `[('form','表单'), ('form_submission','表单提交')]`，与 [app/models/audit.py](app/models/audit.py) 中 `MODULE_FORM`/`MODULE_FORM_SUBMISSION` 常量值**逐一核对一致** → 历史审计日志在筛选下拉与列表徽标中正常翻译（同友情链接策略） |
| **后台路由路径** | `@admin_bp.route('/forms')` 等路径与 endpoint 命名不变，并加 `_gate` 启用守卫（参照 [plugins/friend_link/admin.py:22-39](plugins/friend_link/admin.py)） |
| **权限点** | `form:manage`/`form:view` 沿用，启用时幂等种子写入 + 给预设角色补授权（沿用核心时代策略，仅超管默认可管） |
| **设置键** | `form_notify_*`、SMTP、Webhook 键名不变 |

### 4.5 通知解耦

当前 [app/utils/notify_utils.py:17-176](app/utils/notify_utils.py) 的 `notify_form_submission()` 与表单强耦合。拆分策略：

- **传输层留在核心**（`app/utils/notify_utils.py`）：邮件 SMTP 发送、企业微信 Webhook 发送封装为通用函数 `send_email(...)` / `send_wechat_webhook(...)`，未来插件可复用。
- **触发层迁入插件**（`plugins/form/notify.py`）：`notify_form_submission(form, submission, request)` 读取 `form_notify_*` 设置，组装 payload，调用核心传输函数。
- **设置页归属**：「消息通知」页（[app/admin/setting.py:317-364](app/admin/setting.py)）保留在核心——它配置的是通用传输通道（SMTP/Webhook），不仅服务表单。表单通知开关 `form_notify_enable`/`form_notify_channels` 的读写也留在该页，键名不变；插件触发逻辑读取同一组键。

> 即：**配置在核心，触发在插件**。这样既保留老站配置，又让表单功能可整体禁用（禁用后不再触发通知，配置仍可见）。

### 4.6 自动启用机制

在 [app/__init__.py:431-444](app/__init__.py) 的 v2.2 兼容块之后，追加 v2.3 兼容块：

```python
# ===== v2.3 升级兼容：老站点一次性自动启用内置表单插件 =====
try:
    from .models.setting import Setting
    from .plugin_system import enable_plugin
    if (User.query.filter_by(is_deleted=False).first() is not None
            and not Setting.get('form_plugin_migrated')):
        enable_plugin('form')
        Setting.set('form_plugin_migrated', '1')
        db.session.commit()
except Exception:
    db.session.rollback()
```

并在 [app/utils/bootstrap.py](app/utils/bootstrap.py) 初始化向导成功路径中（与 `friend_link_plugin_migrated` 同处，约 [bootstrap.py:31](app/utils/bootstrap.py)）写入 `form_plugin_migrated = '1'` 标记，避免新装站点误触发自动启用逻辑（新装按向导勾选状态启用）。

### 4.7 演示数据迁移

- 将 [app/utils/bootstrap.py:787-816](app/utils/bootstrap.py) 的表单演示数据生成逻辑迁入 `plugins/form/demo.py` 的 `generate(industry)`。
- 在 `bootstrap.py` 的演示数据主流程中，移除表单内联生成，改为通过插件 `generate_demo_data` 钩子调用（与其他插件一致）。
- 演示数据生成幂等：生成前清理旧表单数据（沿用现有清理逻辑）。

### 4.8 核心瘦身清单

迁移完成后从核心移除：

- [app/models/form.py](app/models/form.py)（整个文件）
- [app/admin/form.py](app/admin/form.py)（整个文件）
- [app/frontend/views.py:447-552](app/frontend/views.py) 的 `/form/<slug>` 路由（迁入插件蓝本）
- [app/utils/notify_utils.py](app/utils/notify_utils.py) 中 `notify_form_submission` 及 payload 构造（传输层保留）
- [app/utils/bootstrap.py:787-816](app/utils/bootstrap.py) 表单演示数据生成
- `app/admin/templates/admin/form/**` 模板（迁入插件 `templates/`）
- 后台侧边栏菜单项中表单条目（改由插件 `get_admin_menu` 提供）

> 核心保留：审计模块常量定义可保留为占位（或迁入插件 `audit.py`，需保证代码值一致）；通知设置页与传输层。

---

## 五、升级与迁移

### 5.1 升级路径

- **v2.2.x → v2.3.0**：仅覆盖代码 + `pip install -r requirements.txt`（新增 Flask-Babel）。无 DB 结构变更。
- 首次启动自动启用表单插件一次（`form_plugin_migrated` 标记位门控）。
- 启用后表单插件表由 `db.create_all()` 兜底（表已存在则跳过），老数据原地可用。
- i18n 默认关闭（`i18n_enable=0`），不影响现有中文站点渲染。

### 5.2 requirements.txt 变更

```
+ Flask-Babel>=4.0,<5.0
```

### 5.3 UPGRADE.md 增补

在 [UPGRADE.md](UPGRADE.md) 增加「v2.2.x → v2.3.0」章节，说明：

- 表单功能转为插件但自动启用、路径不变、数据保留。
- i18n 默认关闭，按需在「系统设置 → 国际化」开启。
- 统计代码插件可在「插件管理」启用后于「统计代码」页配置。

### 5.4 CHANGELOG.md

按现有格式追加 v2.3.0 的 Added / Changed / Fixed / Upgrade Note。

---

## 六、实施阶段与里程碑

建议按依赖关系分阶段，每阶段可独立验证：

| 阶段 | 内容 | 依赖 | 验收 |
| --- | --- | --- | --- |
| M1 | 特性三：表单插件化迁移 | 无 | 老站升级后表单功能原样可用，路径/数据/审计无变化 |
| M2 | 特性二：统计代码插件 | M1（复用插件模式） | 启用后配置百度/GA 代码，前台页面源码可见注入，禁用即消失 |
| M3 | 特性一：i18n 基础设施 | 无 | `_('测试')` 中英文切换生效，设置页配置可用 |
| M4 | 特性一：后台 + 前台文案标记 | M3 | 后台/前台主要文案中英文切换完整 |
| M5 | 收尾：CHANGELOG/UPGRADE/README 更新、`.mo` 编译流程、CI 提取检查 | M1-M4 | 文档完整、CI 通过 |

> M1 与 M3 可并行；M2 可与 M3/M4 并行。M1 优先（解耦核心、为后续减负）。

---

## 七、风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 表单审计模块代码与常量值不一致 | 历史审计日志筛选下拉出现重复/失翻译 | 迁移前核对 `MODULE_FORM`/`MODULE_FORM_SUBMISSION` 字符串值，与插件 `audit_modules` 声明逐一比对 |
| 表单通知逻辑迁出后遗漏触发 | 老站表单提交不再通知 | 迁移后回归测试：提交一条表单，验证邮件/企业微信仍收到；触发逻辑读同一组 `form_notify_*` 键 |
| i18n 遗漏字符串 | 切换英文时仍显示中文 | `pybabel extract` 未标记项清零作为验收门槛；CI 增加提取差异检查 |
| 4 套主题 base.html 注入点遗漏 | 统计代码在某些主题不生效 | 注入点统一在 M2 一次性补齐 4 套主题，逐主题截图验证 |
| Flask-Babel 与 Flask 3.1 兼容 | 初始化报错 | 锁定 `Flask-Babel>=4.0,<5.0`，本地接线后冒烟 |
| 插件模板未 i18n | 插件页英文缺失 | 首版仅要求核心 + 主题 i18n；插件 i18n 作为后续迭代项，文档明确范围 |

---

## 八、验收清单

### 8.1 表单插件化

- [ ] `plugins/form/` 完整目录，`manifest.json` 含 `builtin:true`、`min_core_version:2.3.0`
- [ ] 表名 `forms`/`form_fields`/`form_submissions`/`form_submission_values` 不变
- [ ] 后台路由 `/<admin>/forms` 不变，`form:manage`/`form:view` 权限不变
- [ ] 审计模块代码 `form`/`form_submission` 与核心常量一致
- [ ] 老站升级：自动启用一次（`form_plugin_migrated` 标记），表单数据/提交记录/历史审计无损
- [ ] 禁用表单插件：后台菜单消失、前台 `/form/<slug>` 返回 404，数据保留
- [ ] 表单提交通知（邮件/企业微信）仍正常触发
- [ ] 演示数据由插件钩子生成，制造业/服务业各生成示例表单

### 8.2 统计代码插件

- [ ] `plugins/analytics/` 完整，启用后后台 `/analytics` 配置页可用
- [ ] 配置百度统计/GA 代码保存后，前台页面 `</head>` 前出现注入，无需重启
- [ ] 禁用插件：前台注入消失（返回空串），后台菜单隐藏
- [ ] 4 套主题 base.html 注入点全部生效
- [ ] 仅超管或被授权 `analytics:manage` 角色可编辑
- [ ] 注入不作用于后台管理页

### 8.3 国际化

- [ ] `requirements.txt` 含 `Flask-Babel`，`create_app` 初始化 `babel`
- [ ] 「系统设置 → 国际化」页可配置默认语种与可用语种
- [ ] `?lang=en` 切换后全站主要文案变英文，`?lang=zh` 切回中文
- [ ] `i18n_enable=0` 时全站中文，行为与 v2.2.0 一致
- [ ] 后台顶栏 + 前台主题语言切换器可用
- [ ] `pybabel extract` 无未标记项（CI 检查通过）
- [ ] `.mo` 编译流程文档化

### 8.4 通用

- [ ] [CHANGELOG.md](CHANGELOG.md)、[UPGRADE.md](UPGRADE.md)、[README.md](README.md) 更新 v2.3.0 内容
- [ ] [CONTRIBUTING.md](CONTRIBUTING.md) 补充 i18n 标记规范与 `pybabel` 命令
- [ ] 全部现有用例回归通过（无 DB 结构变更，不应有回归）

---

## 附：关键接口与样板索引

- 插件基类与全部钩子签名：[app/plugin_api.py:20-91](app/plugin_api.py)
- 插件运行时发现/注册/守卫：[app/plugin_system.py:134-194](app/plugin_system.py)
- 友情链接迁移样板（特性三参照）：[plugins/friend_link/__init__.py](plugins/friend_link/__init__.py)、[plugins/friend_link/manifest.json](plugins/friend_link/manifest.json)、[plugins/friend_link/admin.py](plugins/friend_link/admin.py)、[plugins/friend_link/models.py](plugins/friend_link/models.py)
- 自动启用机制样板：[app/__init__.py:431-444](app/__init__.py)
- 模板全局函数注册点：[app/__init__.py:400-408](app/__init__.py)
- Setting 读写：[app/models/setting.py:109-131](app/models/setting.py)
- 前台主题 base.html（注入点）：[app/frontend/templates/themes/default/base.html:1-15](app/frontend/templates/themes/default/base.html)、[base.html:107-110](app/frontend/templates/themes/default/base.html)
- 后台 base.html：[app/admin/templates/admin/base.html:2-20](app/admin/templates/admin/base.html)
