"""存储驱动抽象层测试（v2.6.2 W5）。

覆盖：
- 驱动注册表：register_driver / registered_drivers / 缺 name 报错
- get_driver 解析：显式名 / Setting 默认 / 未注册回退 local
- 归属插件门控：owner 插件禁用 → 回退 local，启用 → 放行（oss_storage 实测）
- LocalStorageDriver：save_bytes / exists / delete / health_check 往返
- CloudStorageDriver 契约：save_bytes 默认临时文件路径、配置缺失报错、
  SDK 缺失 health_check 提示、URL/key 标准化
"""
import os
import uuid

import pytest

from app.utils.storage import (
    LocalStorageDriver,
    StorageConfigError,
    StorageDriver,
    StorageDependencyError,
    StorageUploadError,
    active_driver_name,
    get_driver,
    register_driver,
    registered_drivers,
)

storage = pytest.mark.storage


@pytest.fixture(autouse=True)
def _restore_registry():
    """注册表快照还原：测试内注册的驱动不泄漏到其它用例。"""
    from app.utils import storage as mod
    drivers = dict(mod._DRIVERS)
    owners = dict(mod._DRIVER_OWNERS)
    yield
    mod._DRIVERS.clear()
    mod._DRIVERS.update(drivers)
    mod._DRIVER_OWNERS.clear()
    mod._DRIVER_OWNERS.update(owners)


class FakeDriver(StorageDriver):
    """内存版 FakeDriver：实现 StorageDriver 完整契约。"""

    name = 'fake'
    keeps_local_copy = False

    def __init__(self):
        self.store = {}
        self.saved = []

    def save(self, local_path, key):
        with open(local_path, 'rb') as f:
            self.store[key] = f.read()
        self.saved.append(key)
        return self.public_url(key)

    def save_bytes(self, data, key):
        self.store[key] = bytes(data)
        self.saved.append(key)
        return self.public_url(key)

    def delete(self, key):
        self.store.pop(key, None)

    def exists(self, key):
        return key in self.store

    def public_url(self, key):
        return f'https://cdn.example.com/{key}'


@storage
class TestRegistry:
    """驱动注册表契约。"""

    def test_register_and_list(self, app):
        register_driver(FakeDriver)
        assert 'fake' in registered_drivers()
        assert 'local' in registered_drivers()

    def test_register_without_name_rejected(self, app):
        class NoName(StorageDriver):
            pass
        with pytest.raises(ValueError):
            register_driver(NoName)

    def test_get_driver_explicit_name(self, app):
        register_driver(FakeDriver)
        drv = get_driver('fake')
        assert isinstance(drv, FakeDriver)

    def test_get_driver_unknown_falls_back_local(self, app):
        assert isinstance(get_driver('no_such_driver'), LocalStorageDriver)

    def test_get_driver_default_reads_setting(self, app):
        from app.models.setting import Setting
        from app.extensions import db
        with app.app_context():
            Setting.set('storage_driver', 'local')
            db.session.commit()
            assert isinstance(get_driver(), LocalStorageDriver)
            assert active_driver_name() == 'local'


@storage
class TestOwnerGating:
    """驱动按归属插件门控（v2.6.2 新契约）。"""

    def test_core_registered_driver_not_gated(self, app):
        """owner=None 的驱动不受任何插件启停影响。"""
        register_driver(FakeDriver)
        assert isinstance(get_driver('fake'), FakeDriver)

    def test_owned_driver_falls_back_when_plugin_disabled(self, app):
        register_driver(FakeDriver, owner_slug='oss_storage')
        from app.plugin_system import enable_plugin, disable_plugin
        with app.app_context():
            assert disable_plugin('oss_storage') is None
            assert isinstance(get_driver('fake'), LocalStorageDriver)
            # 启用归属插件后放行
            assert enable_plugin('oss_storage') is None
            assert isinstance(get_driver('fake'), FakeDriver)
            disable_plugin('oss_storage')

    def test_builtin_oss_drivers_gated_by_plugin(self, app):
        """官方三家云驱动由 oss_storage 插件注册并受其启停门控。"""
        with app.app_context():
            names = set(registered_drivers())
            assert {'aliyun', 'tencent', 'qiniu'} <= names
            from app.plugin_system import enable_plugin, disable_plugin
            with app.test_request_context('/'):
                assert isinstance(get_driver('aliyun'), LocalStorageDriver)
                assert enable_plugin('oss_storage') is None
                assert get_driver('aliyun').name == 'aliyun'
                disable_plugin('oss_storage')


@storage
class TestLocalStorageDriver:
    """本地驱动：字节流往返与健康检查。"""

    def test_save_bytes_roundtrip(self, app, tmp_path):
        with app.test_request_context('/'):
            app.config['UPLOAD_FOLDER'] = str(tmp_path)
            drv = LocalStorageDriver()
            key = f'uploads/test/{uuid.uuid4().hex}.txt'
            url = drv.save_bytes('你好字节'.encode('utf-8'), key)
            assert url.startswith('/static/')
            assert drv.exists(key)
            path = tmp_path / 'test' / os.path.basename(key)
            assert path.read_bytes() == '你好字节'.encode('utf-8')
            drv.delete(key)
            assert not drv.exists(key)

    def test_health_check_ok(self, app, tmp_path):
        with app.test_request_context('/'):
            app.config['UPLOAD_FOLDER'] = str(tmp_path)
            ok, msg = LocalStorageDriver().health_check()
            assert ok is True


@storage
class TestCloudDriverContract:
    """CloudStorageDriver 公共契约（以假 SDK 客户端验证）。"""

    class _RecorderClient:
        """假 SDK 客户端：记录 put_object_from_file 的内容。"""

        def __init__(self):
            self.objects = {}

        def put_object_from_file(self, key, path):
            with open(path, 'rb') as f:
                self.objects[key] = f.read()

        def object_exists(self, key):
            return key in self.objects

        def delete_object(self, key):
            self.objects.pop(key, None)

        def get_bucket_info(self):
            info = type('Info', (), {})
            info.name = 'bucket-test'
            return info

    def _make_driver(self, app, **attrs):
        from plugins.oss_storage.drivers.base import CloudStorageDriver

        client = self._RecorderClient()

        class DummyCloud(CloudStorageDriver):
            name = 'dummy'
            pip_package = 'dummy-sdk'
            sdk_import_name = 'json'  # 用标准库模拟「SDK 可导入」
            required_config = attrs.get('required_config', ())

            def _build_client(self, sdk):
                return client

            def _public_base(self):
                return 'https://cdn.test'

            def _put_object(self, local_path, key):
                self.client.put_object_from_file(key, local_path)

            def _object_exists(self, key):
                return self.client.object_exists(key)

            def _delete_object(self, key):
                self.client.delete_object(key)

            def _health(self):
                return True, '连接成功，Bucket：bucket-test'

        with app.app_context():
            return DummyCloud(), client

    def test_save_bytes_via_temp_file(self, app):
        drv, client = self._make_driver(app)
        with app.app_context():
            url = drv.save_bytes(b'hello-cloud', 'dir/a.txt')
            assert url == 'https://cdn.test/dir/a.txt'
            assert client.objects == {'dir/a.txt': b'hello-cloud'}

    def test_save_bytes_normalizes_key(self, app):
        drv, client = self._make_driver(app)
        with app.app_context():
            drv.save_bytes(b'x', '/dir\\b.txt')
            assert 'dir/b.txt' in client.objects

    def test_save_upload_error_wrapped(self, app):
        drv, _client = self._make_driver(app)
        with app.app_context():
            def boom(path, key):
                raise RuntimeError('boom')
            drv._put_object = boom
            with pytest.raises(StorageUploadError):
                drv.save_bytes(b'x', 'k.txt')

    def test_missing_config_raises(self, app):
        drv, _client = self._make_driver(
            app, required_config=(('dummy_key', '密钥'),))
        with app.app_context():
            with pytest.raises(StorageConfigError):
                drv.save_bytes(b'x', 'k.txt')

    def test_health_check_reports_missing_sdk(self, app):
        from plugins.oss_storage.drivers.base import CloudStorageDriver

        class NoSdk(CloudStorageDriver):
            name = 'nosdk'
            sdk_import_name = 'definitely_not_installed_module_xyz'
            required_config = ()

            def _build_client(self, sdk):
                return None

            def _public_base(self):
                return 'https://cdn.test'

            def _put_object(self, local_path, key):
                pass

            def _object_exists(self, key):
                return False

            def _delete_object(self, key):
                pass

            def _health(self):
                return True, 'ok'

        with app.app_context():
            ok, msg = NoSdk().health_check()
            assert ok is False
            assert 'pip install' in msg

    def test_missing_sdk_dependency_error_on_save(self, app):
        from plugins.oss_storage.drivers.base import CloudStorageDriver

        class NoSdkSave(CloudStorageDriver):
            name = 'nosdksave'
            sdk_import_name = 'definitely_not_installed_module_xyz'
            required_config = ()

            def _build_client(self, sdk):
                return None

            def _public_base(self):
                return 'https://cdn.test'

            def _put_object(self, local_path, key):
                self.client.put_object_from_file(key, local_path)  # 触发 SDK 懒加载

            def _object_exists(self, key):
                return False

            def _delete_object(self, key):
                pass

            def _health(self):
                return True, 'ok'

        with app.app_context():
            drv = NoSdkSave()
            with pytest.raises(StorageDependencyError):
                drv.save_bytes(b'x', 'k.txt')
