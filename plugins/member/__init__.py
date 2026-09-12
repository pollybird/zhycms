"""前台用户中心插件（社区插件 v1.0.0）。

提供前台会员注册/登录（用户名密码、短信验证码、微信/QQ 一键登录）、
个人资料维护、找回密码，以及后台会员管理、注册协议编辑、栏目会员
可见性配置。会员体系（members 表）与后台管理员（users 表）完全隔离。

目录结构：
  manifest.json        元数据（builtin: false 社区插件）
  models.py            Member / MemberOauth / MemberSmsCode
  settings.py          member_* 配置项（存核心 Setting 表）
  security.py          前台会话、member_required 守卫
  sms.py               短信验证码（日志/阿里云/通用HTTP）
  oauth.py             微信/QQ OAuth2
  admin.py             后台路由（挂核心 admin_bp）
  frontend_routes.py   前台蓝本 member_frontend
  templates/           前台（frontend/）与后台（admin/）模板
"""
from flask import session, url_for
from flask_babel import gettext as _gettext
from markupsafe import Markup, escape

from app.plugin_api import PluginBase

from . import admin as _admin  # noqa: F401  导入即注册后台路由
from .frontend_routes import member_frontend  # noqa: F401


def _render_user_menu():
    """渲染导航栏右上角会员用户菜单（HTML 片段）。

    未登录展示「登录 / 注册」按钮；已登录展示头像下拉菜单（会员中心、
    个人资料、修改密码、退出）。由主题 base.html 在 navbar 右侧调用。
    """
    from .security import current_member

    member = current_member()
    if member is None:
        return Markup(
            '<div class="d-inline-block ml-2 mb-2 mb-lg-0">'
            '<a href="{}" class="btn btn-outline-light btn-sm">'
            '<i class="fas fa-sign-in-alt mr-1"></i>{}</a>'
            '<a href="{}" class="btn btn-outline-light btn-sm ml-1">'
            '<i class="fas fa-user-plus mr-1"></i>{}</a>'
            '</div>'
        ).format(
            url_for('member_frontend.login'), _gettext('登录'),
            url_for('member_frontend.register'), _gettext('注册'),
        )

    name = escape(member.display_name)
    avatar = escape(member.avatar) if member.avatar else ''
    avatar_html = (
        f'<img src="{avatar}" class="rounded-circle mr-1" '
        f'style="width:20px;height:20px;object-fit:cover;">'
        if avatar else '<i class="fas fa-user-circle mr-1"></i>'
    )
    return Markup(
        '<div class="d-inline-block ml-2 mb-2 mb-lg-0 dropdown">'
        '<button class="btn btn-outline-light btn-sm dropdown-toggle" '
        'type="button" data-toggle="dropdown">'
        '{avatar}{name}'
        '</button>'
        '<div class="dropdown-menu dropdown-menu-right">'
        '<a class="dropdown-item" href="{center}">'
        '<i class="fas fa-user mr-2"></i>{center_text}</a>'
        '<a class="dropdown-item" href="{profile}">'
        '<i class="fas fa-cog mr-2"></i>{profile_text}</a>'
        '<a class="dropdown-item" href="{password}">'
        '<i class="fas fa-key mr-2"></i>{password_text}</a>'
        '<div class="dropdown-divider"></div>'
        '<a class="dropdown-item" href="{logout}">'
        '<i class="fas fa-sign-out-alt mr-2"></i>{logout_text}</a>'
        '</div></div>'
    ).format(
        avatar=Markup(avatar_html), name=name,
        center=url_for('member_frontend.center'),
        center_text=_gettext('会员中心'),
        profile=url_for('member_frontend.profile'),
        profile_text=_gettext('个人资料'),
        password=url_for('member_frontend.change_password'),
        password_text=_gettext('修改密码'),
        logout=url_for('member_frontend.logout'),
        logout_text=_gettext('退出'),
    )


class MemberPlugin(PluginBase):
    slug = 'member'
    version = '1.0.0'
    author = '社区贡献'

    permissions = [
        ('member:manage', '前台会员管理', '查看/编辑/禁用前台会员、会员设置与栏目可见性'),
    ]
    preset_role_grants = {}

    @property
    def name(self):
        return self._('前台用户中心')

    @property
    def description(self):
        return self._(
            '前台会员体系：注册登录、短信验证码登录、手机找回密码、微信/QQ 一键登录、'
            '注册协议管理、栏目会员可见性控制。'
        )

    @property
    def audit_modules(self):
        return [('member', self._('前台会员'))]

    def get_admin_menu(self):
        return [
            {'label': self._('会员列表'), 'endpoint': 'admin.member_index',
             'icon': 'fa-users', 'permission': 'member:manage',
             'active_prefix': 'member_list'},
            {'label': self._('会员设置'), 'endpoint': 'admin.member_settings',
             'icon': 'fa-cog', 'permission': 'member:manage',
             'active_prefix': 'member_settings'},
            {'label': self._('栏目可见性'), 'endpoint': 'admin.member_columns',
             'icon': 'fa-eye', 'permission': 'member:manage',
             'active_prefix': 'member_columns'},
        ]

    def get_admin_menu_icon(self):
        return 'fa-user-circle'

    def get_frontend_blueprint(self):
        return member_frontend

    def get_frontend_menu(self):
        """不向主导航贡献菜单项：会员登录/注册/中心/退出由右上角用户菜单展示。"""
        return []

    def get_frontend_guard(self):
        """核心前台访问守卫：member_only 栏目据此隐藏/拦截。"""
        from .security import is_authenticated, login_url
        return {'is_authenticated': is_authenticated, 'login_url': login_url}

    def get_jinja_globals(self):
        from .security import current_member
        from .settings import cfg as member_cfg

        return {
            'current_member': current_member,
            'member_cfg': member_cfg,
            'member_plugin_enabled': lambda: True,
            'member_user_menu': _render_user_menu,
        }

    def get_jinja_fallbacks(self):
        return {
            'current_member': None,
            'member_cfg': '',
            'member_plugin_enabled': False,
            'member_user_menu': '',
        }

    def on_disabled(self):
        """禁用后清除前台整页缓存。

        member_only 栏目对游客返回的 302 跳转可能已被页面缓存，禁用后守卫
        立即失效，必须清除缓存避免游客在 TTL 内仍被跳转至已下线的 /login。
        """
        try:
            from app.utils.helpers import clear_content_cache
            clear_content_cache()
        except Exception:
            pass


plugin = MemberPlugin()
