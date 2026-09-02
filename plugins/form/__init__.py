"""自定义表单插件（v2.3.0 起由核心功能转为内置插件）。

目录结构（参照 friend_link / product 插件）：
  manifest.json        元数据（builtin: true 官方内置）
  __init__.py           Plugin 类定义与实例（插件入口）
  models.py             Form / FormField / FormSubmission / FormSubmissionValue
                       （导入即注册，启用时自动建表；表名沿用核心原表
                        forms / form_fields / form_submissions /
                        form_submission_values，老站升级后数据无缝保留）
  admin.py              后台管理路由（挂核心 admin_bp，原 /forms 路径不变）
  frontend_routes.py   前台表单展示与提交蓝本 form_frontend（/form/<slug>）
  notify.py             提交通知触发层（调用核心传输层 send_email /
                       send_wechat_webhook）
  demo.py               演示数据钩子（在线留言表单）
  templates/admin/form/ 后台管理页面（由插件蓝本模板目录提供）

迁移兼容说明：
  - 表结构、审计模块代码（form / form_submission）、后台路由路径
    (/forms)、权限点（form:manage / form:view）与核心版完全一致，
    历史审计日志在插件启用后自动正常翻译显示；
  - 老站点升级后由 create_app 一次性自动启用本插件
    （Setting 标记 form_plugin_migrated），无需手工操作。
"""
from app.plugin_api import PluginBase

from . import admin as _admin  # noqa: F401  导入即注册后台路由（并引入 models）
from .frontend_routes import form_frontend  # noqa: F401


class FormPlugin(PluginBase):
    slug = 'form'
    version = '1.0.0'
    author = 'ZhyCMS 官方'

    # ---- 声明式注册 ----
    # 沿用核心时代权限点：form:manage 表单配置 / form:view 查看导出；
    # 不向内容角色默认授权（仅超管默认可管，可在「角色权限」中授权自定义角色）
    permissions = [
        ('form:manage', '表单管理', '表单的增删改与提交记录管理'),
        ('form:view', '表单查看', '查看表单与导出提交记录'),
    ]
    preset_role_grants = {}

    # ---- 代码钩子 ----

    @property
    def name(self):
        return self._('自定义表单')

    @property
    def description(self):
        return self._(
            '可视化表单设计与提交收集：字段类型/验证/文件上传/提交记录导出/'
            '邮件·企业微信通知；v2.3.0 起由核心功能转为内置插件，老站数据无缝保留'
        )

    @property
    def audit_modules(self):
        return [('form', self._('表单')),
                ('form_submission', self._('表单提交'))]

    def get_admin_menu(self):
        return [{
            'label': self._('自定义表单'),
            'endpoint': 'admin.form_index',
            'icon': 'fa-comments',
            'permission': 'form:view',
            'active_prefix': 'form',
        }]

    def get_admin_menu_icon(self):
        # 后台使用 Font Awesome 5（fas/far），wpforms 为品牌图标（fab）不适用；
        # 沿用核心时代 fas fa-comments 视觉，迁移前后图标一致
        return 'fa-comments'

    def get_frontend_blueprint(self):
        # 返回 form_frontend 蓝本：既注册 /form/<slug> 前台路由，
        # 其 template_folder 又把后台管理页模板（admin/form/*）接入
        # Jinja 搜索路径
        return form_frontend

    def generate_demo_data(self, industry):
        from .demo import generate
        generate(industry)


plugin = FormPlugin()
