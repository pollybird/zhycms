"""腾讯云 COS 驱动（cos-python-sdk-v5，import qcloud_cos）。"""
from .base import CloudStorageDriver


class TencentCOSDriver(CloudStorageDriver):
    name = 'tencent'
    pip_package = 'cos-python-sdk-v5'
    sdk_import_name = 'qcloud_cos'
    required_config = (
        ('oss_tencent_secret_id', 'SecretId'),
        ('oss_tencent_secret_key', 'SecretKey'),
        ('oss_tencent_region', '地域 Region'),
        ('oss_tencent_bucket', 'Bucket 名称（含 APPID 后缀）'),
    )

    def _build_client(self, qcloud_cos):
        config = qcloud_cos.CosConfig(
            Region=self._cfg('oss_tencent_region'),
            SecretId=self._cfg('oss_tencent_secret_id'),
            SecretKey=self._cfg('oss_tencent_secret_key'),
            Scheme='https',
        )
        return qcloud_cos.CosS3Client(config)

    def _bucket(self):
        return self._cfg('oss_tencent_bucket')

    def _public_base(self):
        cdn = self._cfg('oss_tencent_cdn_domain')
        if cdn:
            return self._normalize_domain(cdn)
        return 'https://{0}.cos.{1}.myqcloud.com'.format(
            self._bucket(), self._cfg('oss_tencent_region'))

    def _put_object(self, local_path, key):
        self.client.upload_file(
            Bucket=self._bucket(), Key=key, LocalFilePath=local_path)

    def _object_exists(self, key):
        return self.client.object_exists(Bucket=self._bucket(), Key=key)

    def _delete_object(self, key):
        self.client.delete_object(Bucket=self._bucket(), Key=key)

    def _health(self):
        resp = self.client.head_bucket(Bucket=self._bucket())
        return True, '连接成功，Bucket：{0}（HTTP {1}）'.format(
            self._bucket(), getattr(resp, 'status_code', 200))
