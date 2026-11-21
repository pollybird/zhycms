"""内容客户端：栏目、文章、碎片。"""
from .client import Page


class ContentClient:
    """栏目 / 文章 / 碎片读写。

    写方法要求后台已开启 ``api_write_enable`` 并使用 JWT 登录，
    同时账号需具备对应 RBAC 权限与栏目授权。
    """

    def __init__(self, client):
        self._client = client

    # ---------- 栏目 ----------

    def columns(self, tree=False):
        payload = self._client.get('/api/v1/columns',
                                   params={'tree': '1'} if tree else None)
        return payload.get('data') or []

    def column(self, slug):
        return self._client.get(f'/api/v1/columns/{slug}').get('data')

    def articles(self, slug, page=1, per_page=10, keyword=None):
        params = {'page': page, 'per_page': per_page}
        if keyword:
            params['keyword'] = keyword
        payload = self._client.get(f'/api/v1/columns/{slug}/articles',
                                   params=params)
        return Page.from_payload(payload)

    def article(self, article_id):
        return self._client.get(f'/api/v1/articles/{int(article_id)}').get('data')

    # ---------- 文章写 ----------

    def create_article(self, column_id, title, **fields):
        body = {'column_id': int(column_id), 'title': title}
        body.update(fields)
        return self._client.post('/api/v1/articles', json=body).get('data')

    def update_article(self, article_id, title, **fields):
        body = {'title': title}
        body.update(fields)
        return self._client.put(f'/api/v1/articles/{int(article_id)}',
                                json=body).get('data')

    def delete_article(self, article_id):
        return self._client.delete(
            f'/api/v1/articles/{int(article_id)}').get('data')

    # ---------- 栏目写 ----------

    def create_column(self, name, slug, **fields):
        body = {'name': name, 'slug': slug}
        body.update(fields)
        return self._client.post('/api/v1/columns', json=body).get('data')

    def update_column(self, column_id, **fields):
        return self._client.put(f'/api/v1/columns/{int(column_id)}',
                                json=fields).get('data')

    def delete_column(self, column_id):
        return self._client.delete(
            f'/api/v1/columns/{int(column_id)}').get('data')

    # ---------- 碎片 ----------

    def create_fragment(self, name, slug, **fields):
        body = {'name': name, 'slug': slug}
        body.update(fields)
        return self._client.post('/api/v1/fragments', json=body).get('data')

    def update_fragment(self, fragment_id, **fields):
        return self._client.put(f'/api/v1/fragments/{int(fragment_id)}',
                                json=fields).get('data')

    def delete_fragment(self, fragment_id):
        return self._client.delete(
            f'/api/v1/fragments/{int(fragment_id)}').get('data')
