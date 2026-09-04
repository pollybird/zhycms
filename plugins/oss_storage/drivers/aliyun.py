"""阿里云 OSS 驱动（oss2）。"""
from .base import CloudStorageDriver


class AliyunOSSDriver(CloudStorageDriver):
    name = 'aliyun'
    pip_package = 'oss2'
    sdk_import_name = 'oss2'
    required_config = (
        ('oss_aliyun_access_key_id', 'AccessKey ID'),
        ('oss_aliyun_access_key_secret', 'AccessKey Secret'),
        ('oss_aliyun_endpoint', 'Endpoint（地域节点）'),
        ('oss_aliyun_bucket', 'Bucket 名称'),
    )

    def _build_client(self, oss2):
        endpoint = self._normalize_domain(self._cfg('oss_aliyun_endpoint'))
        auth = oss2.Auth(self._cfg('oss_aliyun_access_key_id'),
                         self._cfg('oss_aliyun_access_key_secret'))
        return oss2.Bucket(auth, endpoint, self._cfg('oss_aliyun_bucket'))

    def _endpoint_host(self):
        ep = self._cfg('oss_aliyun_endpoint').replace('https://', '').replace('http://', '').rstrip('/')
        return ep

    def _public_base(self):
        cdn = self._cfg('oss_aliyun_cdn_domain')
        if cdn:
            return self._normalize_domain(cdn)
        return 'https://{0}.{1}'.format(self._cfg('oss_aliyun_bucket'), self._endpoint_host())

    def _put_object(self, local_path, key):
        self.client.put_object_from_file(key, local_path)

    def _object_exists(self, key):
        return self.client.object_exists(key)

    def _delete_object(self, key):
        self.client.delete_object(key)

    def _health(self):
        info = self.client.get_bucket_info()
        name = getattr(info, 'name', None) or self._cfg('oss_aliyun_bucket')
        return True, '连接成功，Bucket：{0}'.format(name)
