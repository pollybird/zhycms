"""ZhyCMS 内容 API Python SDK（v3.2.11，独立版本 0.1.0）。

用法::

    from zhycms_sdk import Client

    client = Client('https://example.com')
    client.login('admin', 'password')
    for article in client.content.articles('news').items:
        print(article['title'])

写端点默认关闭；需在后台「内容 API」中开启 ``api_write_enable``，
且只接受 JWT 登录获得的 Bearer Token。
"""
from .client import Client, Page
from .exceptions import ZhyCMSAPIError

__all__ = ['Client', 'Page', 'ZhyCMSAPIError']
__version__ = '0.1.0'
