"""存储抽象层（v2.4.0）：本地磁盘 / 云端对象存储统一接口。

核心上传唯一入口 ``app.utils.uploads.save_upload_file`` 通过本模块获取
"当前驱动"，不感知任何云厂商：

- 默认驱动 :class:`LocalStorageDriver`（文件保存在 ``app/static/uploads/``）；
- 云端驱动由官方内置插件 ``oss_storage`` 通过
  ``PluginBase.get_storage_drivers()`` 钩子注册（阿里云 OSS / 腾讯云 COS /
  七牛云 Kodo）；
- 插件禁用、驱动未注册或实例化异常时一律安全回退本地驱动；
- 云端上传失败抛显式异常（不静默回退本地，避免混合存储数据归属混乱）。

对象 key 约定：与本地相对路径一致，如 ``uploads/article/20260903/xxx.jpg``。
云端公开 URL = ``CDN 域名/对象 key``，域名统一做去尾斜杠标准化。
"""
import os

from flask import current_app, url_for


# ============================================================
# 异常体系：区分三类失败原因，便于定位与界面提示
# ============================================================

class StorageError(Exception):
    """存储层基础异常。"""


class StorageDependencyError(StorageError):
    """云厂商 SDK 未安装。"""


class StorageConfigError(StorageError):
    """凭证 / 桶等必填配置缺失。"""


class StorageUploadError(StorageError):
    """云端上传 / 删除 / 查询失败（携带原始错误）。"""


# ============================================================
# 驱动协议
# ============================================================

class StorageDriver:
    """存储驱动基类。云驱动由 oss_storage 插件实现并注册。"""

    #: 驱动标识（local / aliyun / tencent / qiniu）
    name = ''
    #: 上传后是否保留本地磁盘副本（本地驱动 True，云驱动 False）
    keeps_local_copy = True

    def save(self, local_path, key):
        """把本地文件发布到存储，返回可访问 URL。"""
        raise NotImplementedError

    def save_bytes(self, data, key):
        """把字节流发布到存储，返回可访问 URL。"""
        raise NotImplementedError

    def delete(self, key):
        """删除对象（不存在不报错）。"""
        raise NotImplementedError

    def exists(self, key):
        """对象是否存在。"""
        raise NotImplementedError

    def public_url(self, key):
        """根据对象 key 生成公开访问 URL。"""
        raise NotImplementedError

    def health_check(self):
        """连通性 / 配置自检，返回 (ok: bool, message: str)。"""
        return True, 'ok'


class LocalStorageDriver(StorageDriver):
    """本地磁盘驱动（默认）：文件已在 UPLOAD_FOLDER 原位，save 为 no-op。"""

    name = 'local'
    keeps_local_copy = True

    def _abs_path(self, key):
        upload_root = current_app.config['UPLOAD_FOLDER']
        # key 形如 uploads/article/.../x.jpg；UPLOAD_FOLDER 指向 static/uploads
        rel = key
        if rel.startswith('uploads/'):
            rel = rel[len('uploads/'):]
        return os.path.join(upload_root, rel.replace('/', os.sep))

    def save(self, local_path, key):
        return self.public_url(key)

    def save_bytes(self, data, key):
        path = self._abs_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
        return self.public_url(key)

    def delete(self, key):
        try:
            path = self._abs_path(key)
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def exists(self, key):
        return os.path.exists(self._abs_path(key))

    def public_url(self, key):
        return url_for('static', filename=key)

    def health_check(self):
        upload_root = current_app.config['UPLOAD_FOLDER']
        if not os.path.isdir(upload_root):
            return False, f'上传目录不存在：{upload_root}'
        if not os.access(upload_root, os.W_OK):
            return False, f'上传目录不可写：{upload_root}'
        return True, '本地存储目录可写'


# ============================================================
# 驱动注册表
# ============================================================

_DRIVERS = {'local': LocalStorageDriver}

#: 提供云端驱动的官方插件 slug（禁用该插件时强制回退本地）
OSS_PLUGIN_SLUG = 'oss_storage'


def register_driver(driver_cls):
    """注册驱动类（插件启动时调用）。"""
    if not getattr(driver_cls, 'name', ''):
        raise ValueError('存储驱动必须定义 name 属性')
    _DRIVERS[driver_cls.name] = driver_cls


def registered_drivers():
    """返回已注册驱动名列表。"""
    return sorted(_DRIVERS.keys())


def _cloud_plugin_enabled():
    """oss_storage 插件是否启用（未安装/异常时按 False 处理）。"""
    try:
        from ..plugin_system import plugin_enabled
        return plugin_enabled(OSS_PLUGIN_SLUG)
    except Exception:
        return False


def get_driver(name=None):
    """获取驱动实例。

    :param name: 驱动名；None 时读 Setting ``storage_driver``（默认 local）。
    :return: StorageDriver 实例。云端驱动要求插件启用且已注册，
             否则安全回退 :class:`LocalStorageDriver`。
    """
    if name is None:
        try:
            from ..models.setting import Setting
            name = (Setting.get('storage_driver', 'local') or 'local').strip()
        except Exception:
            name = 'local'

    if name == 'local' or name not in _DRIVERS:
        return LocalStorageDriver()

    # 云端驱动：插件必须启用
    if not _cloud_plugin_enabled():
        return LocalStorageDriver()

    cls = _DRIVERS[name]
    return cls()


def active_driver_name():
    """当前实际生效的驱动名（考虑插件禁用 / 驱动缺失的回退）。"""
    try:
        return get_driver().name
    except Exception:
        return 'local'
