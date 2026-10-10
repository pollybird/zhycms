# -*- coding: utf-8 -*-
"""数据库迁移插件（v3.0.0 内置插件，默认不启用）。

使用场景：本地用 SQLite 开发站点，开发完成后迁移到服务器的
MySQL / PostgreSQL，无需手工导表。

目录结构（参照 analytics 插件）：
  manifest.json                     元数据（builtin: true 官方内置，默认不启用）
  __init__.py                       Plugin 类定义与实例（插件入口）
  migrate.py                        迁移核心逻辑（建表 → 拷贝数据 → 序列重置）
  admin.py                          后台路由（挂核心 admin_bp，路径 /db-migrator）
  templates/db_migrator/index.html  后台页面

启用方式：后台「插件管理」启用后，侧边栏出现「数据库迁移」菜单。
安全：仅超级管理员或被授权 db_migrator:manage 的角色可用；本插件不向任何
预设角色默认授权（数据库迁移属高危操作）。
"""
from app.plugin_api import PluginBase

from . import admin as _admin  # noqa: F401  导入即注册后台路由


class DbMigratorPlugin(PluginBase):
    slug = 'db_migrator'
    version = '1.0.0'
    author = 'ZhyCMS 官方'

    # 高危操作：不向预设角色默认授权，仅超管或显式授权角色可用
    permissions = [
        ('db_migrator:manage', '数据库迁移',
         '在后台把当前数据库整体迁移到 MySQL / PostgreSQL'),
    ]
    preset_role_grants = {}

    # ---- 代码钩子 ----

    @property
    def name(self):
        return self._('数据库迁移')

    @property
    def description(self):
        return self._(
            '数据库类型迁移：把 SQLite 开发库整体迁移到 MySQL / PostgreSQL'
            '（建表、复制数据、重置序列），支持迁移后即时切换，免重启生效'
        )

    @property
    def audit_modules(self):
        return [('db_migrator', self._('数据库迁移'))]

    def get_admin_menu(self):
        return [{
            'label': self._('数据库迁移'),
            'endpoint': 'admin.db_migrator_index',
            'icon': 'fa-database',
            'permission': 'db_migrator:manage',
            'active_prefix': 'db-migrator',
        }]

    def get_frontend_blueprint(self):
        from flask import Blueprint
        # 无前台路由；注册蓝本仅为让插件模板（db_migrator/*.html）
        # 进入 Jinja 分发加载器搜索路径（后台 render_template 才能找到）
        return Blueprint('db_migrator_frontend', __name__,
                         template_folder='templates')


plugin = DbMigratorPlugin()
