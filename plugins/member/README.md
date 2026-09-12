# 前台用户中心插件（member）

提供独立于后台管理员的前台会员体系，包含用户注册、登录（密码/短信验证码/微信/QQ 一键登录）、个人资料编辑、修改密码、手机找回密码，以及后台会员管理、注册协议编辑、栏目会员可见性控制。

- **插件类型**：社区插件（`builtin: false`），需手动启用
- **最低核心版本**：v2.6.4
- **适用场景**：企业官网会员区、资讯门户用户体系、需登录才能查看的专属内容

---

## 目录

- [安装与启用](#安装与启用)
- [前台功能](#前台功能)
  - [用户注册](#用户注册)
  - [用户登录](#用户登录)
  - [找回密码](#找回密码)
  - [会员中心](#会员中心)
  - [个人资料](#个人资料)
  - [修改密码](#修改密码)
- [一键登录（微信/QQ）](#一键登录微信qq)
- [短信验证码](#短信验证码)
- [栏目会员可见性](#栏目会员可见性)
- [后台管理](#后台管理)
  - [会员列表](#会员列表)
  - [会员设置](#会员设置)
  - [栏目可见性](#栏目可见性)
- [数据模型](#数据模型)
- [配置项速查](#配置项速查)
- [安全说明](#安全说明)

---

## 安装与启用

插件位于 `plugins/member/`，随项目分发。启用方式：

**方式一：后台界面**

进入「后台 → 插件管理」，找到「前台用户中心」，点击启用。

**方式二：命令行**

```python
from app.plugin_system import enable_plugin
enable_plugin('member')
```

启用后会自动：

1. 创建 `members`、`member_oauths`、`member_sms_codes` 三张数据表（幂等，已存在则跳过）
2. 注册权限 `member:manage`（前台会员管理）
3. 注册前台路由蓝图（`/register`、`/login`、`/member` 等）
4. 注入前台访问守卫，使栏目的 `member_only` 标记生效
5. 在后台侧边栏新增「前台用户中心」菜单组
6. 向主题模板注入 `member_user_menu()` 全局函数，在导航栏右上角渲染会员用户菜单

禁用插件后前台路由返回 404、栏目访问限制自动失效、右上角用户菜单自动隐藏（已注册的会员数据保留不删）。

### 右上角用户菜单

插件不向主导航贡献菜单项。会员相关入口（登录/注册、会员中心/退出）统一在导航栏右上角展示：

- **游客**：显示「登录」「注册」按钮
- **已登录会员**：显示头像 + 昵称下拉菜单，包含「会员中心」「个人资料」「修改密码」「退出」

主题模板在 `{% block locale_switcher %}` 之前调用 `{{ member_user_menu() }}` 即可，无需额外改造。插件未启用时该函数返回空字符串，页面不显示用户菜单。

---

## 前台功能

### 用户注册

- **地址**：`/register`
- **字段**：用户名（3-32 位字母/数字/下划线/连字符）、密码（≥6 位）、确认密码、手机号（选填）、邮箱（选填）
- 注册前需勾选「同意注册协议」，协议内容在后台「会员设置 → 基础设置」中编辑（富文本）
- 注册成功后自动登录并跳转首页
- 关闭注册：后台设置 `member_register_enable` 为 off，注册页将提示并跳转登录页

### 用户登录

- **地址**：`/login`
- 支持**密码登录**与**短信验证码登录**双 Tab 切换
- **密码登录**：用户名、手机号、邮箱三种标识符均可登录
- **短信登录**：输入手机号 → 获取验证码 → 验证通过即登录；若该手机号未注册，按配置决定是否自动建号（`member_auto_register_sms`）
- 登录页底部展示微信/QQ 一键登录按钮（需在后台开启对应渠道）
- 支持「记住我」（延长 session 有效期）
- 连续 5 次密码错误锁定账号 10 分钟

### 找回密码

- **地址**：`/forgot-password`
- 流程：输入手机号 → 获取验证码 → 设置新密码（≥6 位，需确认一致）
- 验证码用途标记为 `reset`，与登录验证码独立计数

### 会员中心

- **地址**：`/member`（需登录，未登录跳登录页并回跳）
- 展示账号信息（用户名、昵称、手机、邮箱、注册时间、最近登录）
- 展示已绑定的第三方账号状态（微信/QQ）
- 提供资料编辑、修改密码入口

### 个人资料

- **地址**：`/member/profile`（需登录）
- 可编辑：昵称（必填）、邮箱、手机号、性别、个性签名
- 支持头像上传（自动走核心上传组件，子目录 `member/`，仅允许图片扩展名）
- 邮箱、手机号需唯一（排除自身）

### 修改密码

- **地址**：`/member/password`（需登录）
- 需输入旧密码验证身份，新密码 ≥6 位且确认一致

---

## 一键登录（微信/QQ）

支持微信开放平台（网站应用扫码登录）与 QQ 互联两个渠道。

### 微信扫码登录

1. 在[微信开放平台](https://open.weixin.qq.com/)创建网站应用，获取 AppID 和 AppSecret
2. 将回调地址配置为 `https://你的域名/oauth/wechat/callback`
3. 后台「会员设置 → 微信登录」填入 AppID、AppSecret，勾选启用

### QQ 登录

1. 在[QQ 互联](https://connect.qq.com/)创建网站应用，获取 App ID 和 App Key
2. 将回调地址配置为 `https://你的域名/oauth/qq/callback`
3. 后台「会员设置 → QQ 登录」填入 AppID、AppSecret，勾选启用

### 回调流程

OAuth 回调 `/oauth/<provider>/callback` 按以下优先级处理：

| 场景 | 行为 |
|------|------|
| 该第三方账号已绑定会员 | 直接登录，跳转会员中心 |
| 当前已登录会员 | 将该第三方账号绑定到当前会员，跳转资料页 |
| 未绑定且未登录 | 按 `member_oauth_auto_register` 配置：开启则自动建号并登录；关闭则跳转注册页 |

state 参数用于防 CSRF，校验失败将提示并跳回登录页。

---

## 短信验证码

用于短信验证码登录与手机找回密码，由后台「会员设置 → 短信设置」配置。

### 三种发送通道

| 通道 | 适用环境 | 说明 |
|------|----------|------|
| `log` | 开发/测试 | 验证码写入应用日志，不产生真实短信费用（默认） |
| `aliyun` | 生产 | 阿里云短信 SendSms，RPC 风格 HMAC-SHA1 签名，无需安装 SDK |
| `webhook` | 生产 | 通用 HTTP 接口，URL 支持 `{phone}`、`{code}` 占位符，GET/POST 可选 |

### 频控策略

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 发送间隔 | 60 秒 | 同一手机号两次发送的最短间隔 |
| 每日上限 | 10 条 | 同一手机号每日（自然日）最大发送量 |
| 验证码有效期 | 300 秒 | 过期后验证码失效 |

### 验证码安全

- 验证码为 6 位随机数字，仅存储 SHA-256 哈希值，不留存明文
- 校验使用 `hmac.compare_digest` 防时序攻击
- 验证码一次性消费，使用后立即标记 `used=True`
- 按 `phone + purpose` 维度独立校验（登录验证码不能用于重置密码）

### 阿里云短信配置示例

后台「会员设置 → 短信设置」选择通道 `aliyun`，填入：

- AccessKey ID
- AccessKey Secret
- 签名名称（SignName）
- 模板代码（TemplateCode，如 `SMS_123456789`）

模板变量需包含 `${code}`，系统将发送 `{"code": "123456"}` 作为 TemplateParam。

### 通用 Webhook 配置示例

选择通道 `webhook`，填入接口地址，如：

```
https://your-sms-gateway.com/send?mobile={phone}&content=您的验证码是{code}
```

- GET 方式：参数拼接在 URL 占位符中
- POST 方式：以 JSON body 发送 `{"phone": "...", "code": "..."}`

---

## 栏目会员可见性

插件启用后，栏目编辑页新增「仅会员可见」开关（在「启用」开关旁边）。

- **开启**：该栏目（及其文章详情页）仅已登录的前台会员可访问，游客自动跳转登录页
- **关闭**（默认）：所有访客可见
- 导航栏对游客自动隐藏 `member_only` 栏目，对已登录会员正常显示
- **缓存安全**：已登录会员绕过整页缓存（避免与游客缓存串页）；游客的缓存页面不包含会员专属内容
- **插件禁用后**：`member_only` 标记自动失效，所有栏目恢复公开访问

后台「栏目可见性」页提供树形批量勾选界面，可一次性设置多个栏目的会员可见性。

---

## 后台管理

需拥有 `member:manage` 权限。超级管理员自动拥有所有权限。

### 会员列表

- **地址**：`/admin/members`
- 支持按用户名/昵称/手机号/邮箱关键词搜索
- 支持按状态筛选（启用/禁用）
- 分页展示（每页 20 条）

### 会员编辑

- **地址**：`/admin/members/<id>/edit`
- 可编辑昵称、手机号、邮箱、性别
- 可重置密码（输入新密码，≥6 位）
- 可启用/禁用会员账号

### 会员删除

- **地址**：`/admin/members/<id>/delete`（POST）
- 软删除（标记 `is_deleted=True`），不实际删除数据

### 会员设置

- **地址**：`/admin/member/settings`
- 分为基础设置、短信设置、微信登录、QQ 登录四个 Tab
- **基础设置**：注册开关、注册协议（CKEditor 5 富文本）、短信登录开关、自动建号开关、第三方自动建号开关
- **短信设置**：通道选择、阿里云参数、Webhook 参数、频控参数
- 保存时仅写入当前 Tab 允许的键，不会误改其他 Tab 的配置

### 栏目可见性

- **地址**：`/admin/member/columns`
- 树形展示所有栏目，勾选「仅会员可见」
- 提交后批量更新栏目的 `member_only` 字段

---

## 数据模型

会员体系与后台管理员（`users` 表）完全独立，不共享数据。

### members（会员主表）

| 字段 | 类型 | 说明 |
|------|------|------|
| `username` | String(64) | 用户名，唯一 |
| `password_hash` | String(255) | 密码哈希（Werkzeug），第三方/短信注册用户初始可为空 |
| `nickname` | String(64) | 昵称 |
| `avatar` | String(255) | 头像 URL |
| `email` | String(128) | 邮箱 |
| `phone` | String(20) | 手机号 |
| `gender` | String(8) | 性别（male/female/空） |
| `signature` | String(255) | 个性签名 |
| `is_enabled` | Boolean | 是否启用 |
| `is_deleted` | Boolean | 软删除标记 |
| `last_login_at` | DateTime | 最近登录时间 |
| `last_login_ip` | String(64) | 最近登录 IP |
| `login_fail_count` | Integer | 连续登录失败次数 |
| `locked_until` | DateTime | 锁定截止时间 |

### member_oauths（第三方账号绑定）

| 字段 | 类型 | 说明 |
|------|------|------|
| `member_id` | Integer | 关联会员 ID |
| `provider` | String(20) | 渠道（wechat/qq） |
| `openid` | String(128) | 第三方唯一标识 |
| `unionid` | String(128) | 微信 UnionID（如有） |
| `nickname` | String(128) | 第三方昵称 |
| `avatar` | String(255) | 第三方头像 |

唯一约束：`provider + openid`

### member_sms_codes（短信验证码）

| 字段 | 类型 | 说明 |
|------|------|------|
| `phone` | String(20) | 手机号 |
| `code_hash` | String(64) | 验证码 SHA-256 哈希（仅存哈希，不留明文） |
| `purpose` | String(20) | 用途（login/reset） |
| `expires_at` | DateTime | 过期时间 |
| `used` | Boolean | 是否已使用（一次性消费） |
| `ip` | String(64) | 请求来源 IP |

---

## 配置项速查

所有配置存储于核心 `Setting` 键值表，统一 `member_` 前缀。

### 基础设置

| 键 | 默认值 | 说明 |
|----|--------|------|
| `member_register_enable` | on | 是否开放注册 |
| `member_agreement` | （空） | 注册协议（富文本 HTML） |
| `member_login_sms_enable` | on | 短信验证码登录开关 |
| `member_auto_register_sms` | on | 短信登录时手机号未注册则自动建号 |
| `member_oauth_auto_register` | on | 第三方登录未绑定时自动建号 |

### 短信设置

| 键 | 默认值 | 说明 |
|----|--------|------|
| `member_sms_provider` | log | 通道：log / aliyun / webhook |
| `member_sms_aliyun_key_id` | （空） | 阿里云 AccessKey ID |
| `member_sms_aliyun_key_secret` | （空） | 阿里云 AccessKey Secret |
| `member_sms_aliyun_sign` | （空） | 阿里云签名名称 |
| `member_sms_aliyun_template` | （空） | 阿里云模板代码 |
| `member_sms_webhook_url` | （空） | 通用短信接口地址（支持 `{phone}`/`{code}` 占位符） |
| `member_sms_webhook_method` | GET | 请求方式：GET / POST |
| `member_sms_code_ttl` | 300 | 验证码有效期（秒） |
| `member_sms_send_interval` | 60 | 同手机号发送间隔（秒） |
| `member_sms_daily_limit` | 10 | 同手机号每日发送上限 |

### 微信登录

| 键 | 默认值 | 说明 |
|----|--------|------|
| `member_wechat_enable` | （空） | 启用开关（on=启用） |
| `member_wechat_appid` | （空） | 微信开放平台 AppID |
| `member_wechat_secret` | （空） | 微信开放平台 AppSecret |

### QQ 登录

| 键 | 默认值 | 说明 |
|----|--------|------|
| `member_qq_enable` | （空） | 启用开关（on=启用） |
| `member_qq_appid` | （空） | QQ 互联 App ID |
| `member_qq_secret` | （空） | QQ 互联 App Key |

---

## 安全说明

- **会话隔离**：会员登录态使用独立 session 键 `member_id`，与后台管理员的 Flask-Login 键 `_user_id` 完全隔离，互不影响
- **密码安全**：使用 Werkzeug `generate_password_hash` / `check_password_hash` 存储与校验
- **验证码安全**：SHA-256 哈希存储 + `hmac.compare_digest` 防时序攻击 + 一次性消费
- **登录锁定**：连续 5 次密码错误锁定账号 10 分钟
- **OAuth 防 CSRF**：state 参数随机生成，回调时严格校验
- **文件上传**：头像上传走核心 `save_upload_file`，仅允许图片扩展名（`app.constants.Upload.IMAGE_EXTS`）
- **后台权限**：所有会员管理路由需 `member:manage` 权限，无权限返回 403
- **缓存隔离**：已登录会员绕过整页缓存，游客缓存页面不包含会员专属内容，禁用插件时自动清除前台缓存
