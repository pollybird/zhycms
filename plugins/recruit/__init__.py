"""招聘插件（社区示例插件，非官方内置）。

目录结构：
  manifest.json          元数据（builtin=false，可上传/卸载）
  __init__.py            Plugin 类定义与实例（插件入口）
  models.py              RecruitJob / RecruitApplication 模型（导入即注册，启用时自动建表）
  admin.py               后台管理路由（岗位 CRUD + 申请管理，挂核心 admin_bp）
  frontend.py            recruit_jobs() / recruit_job_url() 模板函数
  frontend_routes.py     前台蓝本（岗位列表/详情/申请提交，动态 + 伪静态）
  templates/recruit/     后台页面 + 前台兜底模板（主题可覆盖）
"""
from app.plugin_api import PluginBase

from . import admin as _admin       # noqa: F401  导入即注册后台路由（并引入 models）
from .frontend import recruit_job_url, recruit_jobs


class RecruitPlugin(PluginBase):
    slug = 'recruit'
    version = '1.0.0'
    author = 'ZhyCMS 社区示例'

    # ---- 声明式注册 ----
    permissions = [('recruit:manage', '招聘管理',
                    '招聘岗位维护与求职申请处理')]
    preset_role_grants = {
        'content_editor': ['recruit:manage'],
        'content_auditor': ['recruit:manage'],
    }

    # ---- 代码钩子 ----

    @property
    def name(self):
        return self._('招聘管理')

    @property
    def description(self):
        return self._(
            '招聘岗位发布与在线求职申请：岗位介绍、招聘截止时间、简历上传（word/excel/pdf），截止后自动关闭提交'
        )

    @property
    def audit_modules(self):
        return [('recruit', self._('招聘管理'))]

    def get_admin_menu(self):
        return [
            {
                'label': self._('招聘岗位'),
                'endpoint': 'admin.recruit_job_index',
                'icon': 'fa-briefcase',
                'permission': 'recruit:manage',
                'active_prefix': 'recruit_job',
            },
            {
                'label': self._('求职申请'),
                'endpoint': 'admin.recruit_application_index',
                'icon': 'fa-user-graduate',
                'permission': 'recruit:manage',
                'active_prefix': 'recruit_app',
            },
        ]

    def get_frontend_menu(self):
        """前台导航追加「招贤纳士」入口（插件启用时自动出现）。"""
        try:
            from flask import url_for
            url = url_for('recruit_frontend.job_list')
        except Exception:
            url = '/jobs'
        return [{'label': self._('招贤纳士'), 'url': url, 'target': ''}]

    def get_frontend_blueprint(self):
        from .frontend_routes import recruit_frontend
        return recruit_frontend

    def get_jinja_globals(self):
        from .frontend import recruit_job_url, recruit_jobs
        return {
            'recruit_job_url': recruit_job_url,
            'recruit_jobs': recruit_jobs,
        }

    def get_jinja_fallbacks(self):
        return {
            'recruit_job_url': '#',
            'recruit_jobs': [],
        }

    def get_sitemap_urls(self):
        """开放申请的岗位详情页收录（loc 为完整 URL）。"""
        from flask import has_request_context, request
        from app.models.setting import Setting
        from .models import RecruitJob
        from .frontend import recruit_job_url

        base = request.url_root.rstrip('/') if has_request_context() else ''
        if not base:
            base = (Setting.get('site_url') or '').strip().rstrip('/')
        freq = Setting.get('seo_sitemap_changefreq_article') or 'monthly'
        prio = Setting.get('seo_sitemap_priority_article') or '0.6'
        urls = []
        for j in RecruitJob.query.filter_by(is_enabled=True, is_deleted=False) \
                .order_by(RecruitJob.updated_at.desc()).limit(2000):
            urls.append({
                'loc': base + recruit_job_url(j),
                'lastmod': j.updated_at.strftime('%Y-%m-%d')
                if j.updated_at else '',
                'changefreq': freq,
                'priority': prio,
            })
        return urls


plugin = RecruitPlugin()
