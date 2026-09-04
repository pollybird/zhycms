"""对象存储 OSS 插件（v2.4.0 官方内置）。

支持阿里云 OSS / 腾讯云 COS / 七牛云 Kodo 三家云端对象存储，与本地磁盘
存储一键切换。核心上传入口（app/utils/uploads.py）通过存储抽象层
（app/utils/storage.py）调用本插件注册的云驱动：

- 默认 local 本地驱动，插件启用但未配置时不产生任何云端调用；
- 云 SDK 为可选依赖（oss2 / cos-python-sdk-v5 / qiniu），懒加载；
- 插件禁用时存储驱动自动重置为本地，新上传不再走云端；
- 后台「对象存储」配置页：凭证配置、连接测试、本地文件一键迁移云端。

目录结构：
  manifest.json   元数据（builtin: true，min_core_version: 2.4.0）
  __init__.py      插件入口（PluginBase 子类）
  drivers/         三家云驱动（base.py 公共基类）
  admin.py         后台配置/测试/迁移路由（挂核心 admin_bp）
  migrate.py       本地 → 云端一键迁移（dry-run + 幂等执行）
  templates/oss_storage/settings.html  后台配置页
  translations/    插件独立翻译域（v2.3 国际化规范）
"""
from app.plugin_api import PluginBase

from . import admin as _admin  # noqa: F401  导入即注册后台路由


class OSSStoragePlugin(PluginBase):
    slug = 'oss_storage'
    version = '1.0.0'
    author = 'ZhyCMS 官方'

    permissions = [
        ('oss_storage:manage', '对象存储管理',
         '配置云存储凭证、切换存储驱动、本地文件迁移云端'),
    ]
    preset_role_grants = {}

    @property
    def name(self):
        return self._('对象存储')

    @property
    def description(self):
        return self._(
            '阿里云 OSS / 腾讯云 COS / 七牛云 Kodo 云端对象存储支持，'
            '本地与云端一键切换，支持历史文件批量迁移云端；v2.4.0 内置插件'
        )

    @property
    def audit_modules(self):
        return [('oss_storage', self._('对象存储'))]

    def get_admin_menu(self):
        return [{
            'label': self._('对象存储'),
            'endpoint': 'admin.oss_storage_index',
            'icon': 'fa-cloud-upload-alt',
            'permission': 'oss_storage:manage',
            'active_prefix': 'oss-storage',
        }]

    def get_admin_menu_icon(self):
        return 'fa-cloud-upload-alt'

    def get_frontend_blueprint(self):
        from flask import Blueprint
        # 无前台路由；注册蓝本仅为让插件模板进入 Jinja 搜索路径
        return Blueprint('oss_storage_frontend', __name__,
                         template_folder='templates')

    def get_storage_drivers(self):
        from .drivers.aliyun import AliyunOSSDriver
        from .drivers.tencent import TencentCOSDriver
        from .drivers.qiniu import QiniuDriver
        return [AliyunOSSDriver, TencentCOSDriver, QiniuDriver]

    def on_disabled(self):
        """禁用插件：存储驱动强制回到本地，防止新上传指向不可用配置。"""
        try:
            from app.models.setting import Setting
            if Setting.get('storage_driver', 'local') != 'local':
                Setting.set('storage_driver', 'local')
        except Exception:
            pass


plugin = OSSStoragePlugin()
