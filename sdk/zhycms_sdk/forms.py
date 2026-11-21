"""表单客户端：提交记录只读分页。"""
from .client import Page


class FormClient:
    """表单提交记录（需 JWT 且具备 form:view 权限）。"""

    def __init__(self, client):
        self._client = client

    def submissions(self, slug, page=1, per_page=20):
        payload = self._client.get(
            f'/api/v1/forms/{slug}/submissions',
            params={'page': page, 'per_page': per_page})
        return Page.from_payload(payload)
