# -*- coding: utf-8 -*-
"""一键翻译插件（v2.5.1 官方内置）。

在文章、栏目、碎片、产品、表单、招聘、友情链接等编辑页的「多语言版本」
标签页中提供「一键翻译」按钮：填写默认语言（中文）内容后点击，自动调用
配置好的翻译服务，把标题、摘要、正文、SEO 字段翻译并填充到对应语言。

- 支持百度翻译 / 有道翻译 / Google 翻译 / DeepSeek 大模型，凭证在插件设置页配置；
- 富文本（正文）字段按 HTML 翻译，尽量保留排版标签；
- 翻译结果填入表单后仍需人工校对并保存，不直接写库；
- 插件禁用时不注入任何脚本、翻译接口 404，对后台零影响。

目录结构：
  manifest.json   元数据（builtin: true，min_core_version: 2.5.0）
  __init__.py      插件入口（PluginBase 子类）
  service.py       翻译服务商统一抽象（百度/有道/Google/DeepSeek）
  admin.py         后台设置页 + 翻译 JSON API（挂核心 admin_bp）
  assets.py        编辑页引导脚本（Jinja 全局 auto_translate_assets）
  templates/auto_translate/settings.html  后台设置页
"""
from app.plugin_api import PluginBase
from app.constants import Roles as _R

from . import admin as _admin  # noqa: F401  导入即注册后台路由
from .assets import render_assets


class AutoTranslatePlugin(PluginBase):
    slug = 'auto_translate'
    version = '1.0.0'
    author = 'ZhyCMS 官方'

    permissions = [
        ('auto_translate:manage', '一键翻译配置',
         '配置翻译服务商与 API 凭证'),
        ('auto_translate:use', '一键翻译使用',
         '在内容编辑页调用一键翻译填充多语言字段'),
    ]
    # 内容编辑、内容审核角色可直接使用；配置权限仅超级管理员（默认拥有全部权限）
    preset_role_grants = {
        _R.CONTENT_EDITOR: ['auto_translate:use'],
        _R.CONTENT_AUDITOR: ['auto_translate:use'],
    }

    @property
    def name(self):
        return self._('一键翻译')

    @property
    def description(self):
        return self._(
            '内容编辑页多语言字段一键翻译：配置百度/有道/Google/DeepSeek 翻译服务后，'
            '自动翻译标题、摘要、正文与 SEO 字段；v2.5.1 内置插件'
        )

    @property
    def audit_modules(self):
        return [('auto_translate', self._('一键翻译'))]

    def get_admin_menu(self):
        return [{
            'label': self._('一键翻译'),
            'endpoint': 'admin.auto_translate_index',
            'icon': 'fa-language',
            'permission': 'auto_translate:manage',
            'active_prefix': 'auto-translate',
        }]

    def get_admin_menu_icon(self):
        return 'fa-language'

    def get_frontend_blueprint(self):
        from flask import Blueprint
        # 无前台路由；注册蓝本仅为让插件模板进入 Jinja 搜索路径
        return Blueprint('auto_translate_frontend', __name__,
                         template_folder='templates')

    def get_jinja_globals(self):
        return {'auto_translate_assets': render_assets}

    def get_jinja_fallbacks(self):
        # 插件未启用/未加载时，后台 base.html 中的调用输出空字符串
        return {'auto_translate_assets': ''}


plugin = AutoTranslatePlugin()
