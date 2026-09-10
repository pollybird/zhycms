"""工作流测试：草稿 → 待审核 → 发布/驳回 → 归档。"""
import pytest

from tests.factories import make_column, make_article


@pytest.mark.workflow
class TestArticleWorkflow:

    def test_published_article_visible_on_frontend(self, app, client, admin_client):
        """已发布文章在前台可见。"""
        from app.extensions import db
        from app.models.workflow import STATUS_PUBLISHED
        from app.models.setting import Setting

        with app.app_context():
            Setting.set('seo_rewrite_enable', 'on')
            col = make_column(name='新闻', slug='news')
            make_article(
                title='发布测试', column_id=col.id,
                status=STATUS_PUBLISHED, content='已发布内容')
            db.session.commit()
            col_slug = col.slug

        resp = client.get(f'/{col_slug}.html')
        assert resp.status_code == 200
        assert '发布测试'.encode() in resp.data

    def test_draft_article_not_on_frontend(self, app, client):
        """草稿文章不出现在前台。"""
        from app.extensions import db
        from app.models.workflow import STATUS_DRAFT
        from app.models.setting import Setting

        with app.app_context():
            Setting.set('seo_rewrite_enable', 'on')
            col = make_column(name='草稿栏', slug='draft-col')
            make_article(
                title='草稿文章', column_id=col.id,
                status=STATUS_DRAFT, content='草稿内容')
            db.session.commit()
            col_slug = col.slug

        resp = client.get(f'/{col_slug}.html')
        assert resp.status_code == 200
        # 草稿文章不应出现在列表页
        assert '草稿文章'.encode() not in resp.data
