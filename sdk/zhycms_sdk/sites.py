"""站点客户端：站点信息、站点列表与资源计量。"""


class SiteClient:
    """站点相关只读接口。"""

    def __init__(self, client):
        self._client = client

    def info(self):
        """当前站点信息与导航（支持静态 Token 或 JWT）。"""
        return self._client.get('/api/v1/site').get('data')

    def list(self):
        """全部站点列表（仅超级管理员）。"""
        return self._client.get('/api/v1/sites').get('data') or []

    def metrics(self, site_id):
        """指定站点最近 30 天资源计量（仅超级管理员）。"""
        return self._client.get(
            f'/api/v1/sites/{int(site_id)}/metrics').get('data') or []
