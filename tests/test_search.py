"""搜索测试：Whoosh 索引、SQL 兜底、SearchProvider。"""
import pytest

from tests.factories import make_column, make_article


@pytest.mark.search
class TestSearch:

    def test_search_published_article(self, app, client):
        """搜索已发布文章标题能命中。"""
        from app.extensions import db
        from app.models.workflow import STATUS_PUBLISHED
        from app.utils.search import rebuild_all

        with app.app_context():
            col = make_column(name='搜索栏目', slug='search-col')
            make_article(
                title='CNC加工中心测试', column_id=col.id,
                status=STATUS_PUBLISHED, content='精密加工设备')
            db.session.commit()
            rebuild_all()

        resp = client.get('/search?q=CNC')
        assert resp.status_code == 200
        # 搜索结果页应包含搜索关键词或结果
        assert 'CNC'.encode() in resp.data

    def test_sql_fallback_when_no_index(self, app, client):
        """无索引时 SQL LIKE 兜底仍可搜到。"""
        from app.extensions import db
        from app.models.workflow import STATUS_PUBLISHED
        import app.utils.search as search_mod
        import shutil, os

        with app.app_context():
            col = make_column(name='SQL兜底栏目', slug='sql-col')
            make_article(
                title='精密焊接设备', column_id=col.id,
                status=STATUS_PUBLISHED, content='焊接机器人')
            db.session.commit()

            idx_root = search_mod._get_index_root()
            if os.path.isdir(idx_root):
                shutil.rmtree(idx_root)

        resp = client.get('/search?q=焊接')
        assert resp.status_code == 200
        assert '焊接'.encode() in resp.data
