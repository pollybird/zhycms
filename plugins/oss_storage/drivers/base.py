"""云端对象存储驱动基类（v2.4.0 oss_storage 插件）。

封装三家云厂商共性逻辑：
- 配置从 Setting 读取（凭证不入库代码，后台可视化配置）；
- SDK 懒加载 + 缺失时抛 StorageDependencyError（携带 pip 安装命令）；
- 必填配置缺失抛 StorageConfigError；
- 上传/删除/查询失败统一包装为 StorageUploadError；
- URL 拼接标准化（域名去尾斜杠、key 去前导斜杠），杜绝斜杠粘连。
"""
import importlib

from app.utils.storage import (
    StorageDriver,
    StorageDependencyError,
    StorageConfigError,
    StorageUploadError,
)


class CloudStorageDriver(StorageDriver):
    """云驱动基类，子类需实现 name / pip_package / sdk_import_name /
    required_config / _build_client / _put_object / _object_exists /
    _delete_object / _health / _default_domain。"""

    keeps_local_copy = False

    #: pip 包名（缺包提示用）
    pip_package = ''
    #: import 模块名
    sdk_import_name = ''
    #: 必填配置键 [(setting_key, 中文说明)]
    required_config = ()

    def __init__(self):
        from app.models.setting import Setting
        self._settings = Setting.get_dict()
        self._client = None

    # ---- 配置 ----

    def _cfg(self, key):
        return (self._settings.get(key) or '').strip()

    def _validate_config(self):
        missing = [label for key, label in self.required_config if not self._cfg(key)]
        if missing:
            raise StorageConfigError(
                '缺少必填配置：{0}（请到后台「对象存储」配置页填写）'.format('、'.join(missing)))

    @staticmethod
    def _normalize_domain(domain):
        d = (domain or '').strip().rstrip('/')
        if d and not d.startswith(('http://', 'https://')):
            d = 'https://' + d
        return d

    @staticmethod
    def _normalize_key(key):
        return (key or '').replace('\\', '/').lstrip('/')

    # ---- SDK / client 懒加载 ----

    def _import_sdk(self):
        try:
            return importlib.import_module(self.sdk_import_name)
        except ImportError:
            raise StorageDependencyError(
                '云存储 SDK 未安装，请在服务器执行：'
                'pip install {0} -i https://pypi.tuna.tsinghua.edu.cn/simple'.format(
                    self.pip_package))

    def _build_client(self, sdk):
        raise NotImplementedError

    @property
    def client(self):
        if self._client is None:
            sdk = self._import_sdk()
            self._validate_config()
            try:
                self._client = self._build_client(sdk)
            except (StorageDependencyError, StorageConfigError):
                raise
            except Exception as e:
                raise StorageConfigError('存储客户端初始化失败：{0}'.format(e))
        return self._client

    # ---- 公共 URL ----

    def _public_base(self):
        """公开访问域名（含 scheme，无尾斜杠）。子类实现。"""
        raise NotImplementedError

    def public_url(self, key):
        return '{0}/{1}'.format(self._public_base(), self._normalize_key(key))

    # ---- 存储操作（子类实现底层调用） ----

    def _put_object(self, local_path, key):
        raise NotImplementedError

    def _object_exists(self, key):
        raise NotImplementedError

    def _delete_object(self, key):
        raise NotImplementedError

    def _health(self):
        """返回 (ok, message)，异常由 health_check 兜底捕获。"""
        raise NotImplementedError

    def save(self, local_path, key):
        key = self._normalize_key(key)
        try:
            self._put_object(local_path, key)
        except (StorageDependencyError, StorageConfigError, StorageUploadError):
            raise
        except Exception as e:
            raise StorageUploadError('{0} 上传失败：{1}'.format(self.name, e))
        return self.public_url(key)

    def exists(self, key):
        key = self._normalize_key(key)
        try:
            return bool(self._object_exists(key))
        except (StorageDependencyError, StorageConfigError):
            raise
        except Exception as e:
            raise StorageUploadError('{0} 查询对象失败：{1}'.format(self.name, e))

    def delete(self, key):
        key = self._normalize_key(key)
        try:
            self._delete_object(key)
        except (StorageDependencyError, StorageConfigError):
            raise
        except Exception:
            pass  # 删除不存在的对象不报错

    def health_check(self):
        try:
            self._import_sdk()
        except StorageDependencyError as e:
            return False, str(e)
        try:
            self._validate_config()
        except StorageConfigError as e:
            return False, str(e)
        try:
            return self._health()
        except Exception as e:
            return False, '连接失败：{0}'.format(e)
