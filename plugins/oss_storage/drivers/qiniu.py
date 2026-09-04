"""七牛云 Kodo 驱动（qiniu SDK）。

七牛对象存储没有默认下载域名，必须在后台配置绑定的 CDN 域名。
"""
from .base import CloudStorageDriver
from app.utils.storage import StorageConfigError


class QiniuDriver(CloudStorageDriver):
    name = 'qiniu'
    pip_package = 'qiniu'
    sdk_import_name = 'qiniu'
    required_config = (
        ('oss_qiniu_access_key', 'AccessKey'),
        ('oss_qiniu_secret_key', 'SecretKey'),
        ('oss_qiniu_bucket', '空间名称'),
        ('oss_qiniu_cdn_domain', '绑定 CDN 域名（七牛必填）'),
    )

    def _validate_config(self):
        super()._validate_config()

    def _build_client(self, qiniu):
        auth = qiniu.Auth(self._cfg('oss_qiniu_access_key'),
                         self._cfg('oss_qiniu_secret_key'))
        return {'auth': auth, 'bm': qiniu.BucketManager(auth), 'qiniu': qiniu}

    def _bucket(self):
        return self._cfg('oss_qiniu_bucket')

    def _public_base(self):
        domain = self._cfg('oss_qiniu_cdn_domain')
        if not domain:
            raise StorageConfigError('七牛云必须配置绑定的 CDN 域名')
        return self._normalize_domain(domain)

    def _put_object(self, local_path, key):
        qiniu = self.client['qiniu']
        token = self.client['auth'].upload_token(self._bucket(), key)
        ret, info = qiniu.put_file(token, key, local_path)
        if info.status_code != 200:
            raise RuntimeError('HTTP {0}：{1}'.format(info.status_code, info.text_body))

    def _object_exists(self, key):
        ret, info = self.client['bm'].stat(self._bucket(), key)
        return info.status_code == 200

    def _delete_object(self, key):
        self.client['bm'].delete(self._bucket(), key)

    def _health(self):
        ret, info = self.client['bm'].list(self._bucket(), limit=1)
        if info.status_code == 200:
            return True, '连接成功，空间：{0}'.format(self._bucket())
        return False, 'HTTP {0}：{1}'.format(info.status_code, info.text_body)
