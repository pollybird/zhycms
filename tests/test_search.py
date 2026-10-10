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

    def test_batch_ops_update_index(self, app, admin_client):
        """批量发布/删除操作逐篇更新搜索索引。

        此前批量路径只清栏目缓存、未触发单篇索引，导致 Whoosh 等
        索引型后端与数据库状态不一致（v3.0.1 修复）。
        """
        from app.extensions import db
        from app.models.workflow import STATUS_DRAFT
        from app.utils.search import search_articles

        with app.app_context():
            col = make_column(name='批量索引栏目', slug='batch-idx-col')
            ids = []
            for i in range(3):
                a = make_article(
                    title=f'批量索引目标{i}', column_id=col.id,
                    status=STATUS_DRAFT, content='批量索引正文')
                ids.append(a.id)
            db.session.commit()
            cid = col.id

        want = {f'article:{i}' for i in ids}

        # 批量发布 → 三篇均应进入索引且可被搜出
        resp = admin_client.post(
            f'/admin/columns/{cid}/articles/batch',
            data={'action': 'publish', 'ids[]': ids}, follow_redirects=False)
        assert resp.status_code == 302

        with app.app_context():
            items, total = search_articles('批量索引目标')
            got = {it['uid'] for it in items}
            assert want <= got

        # 批量删除 → 三篇均应从索引移除
        resp = admin_client.post(
            f'/admin/columns/{cid}/articles/batch',
            data={'action': 'delete', 'ids[]': ids}, follow_redirects=False)
        assert resp.status_code == 302

        with app.app_context():
            items, _ = search_articles('批量索引目标')
            got = {it['uid'] for it in items}
            assert not (want & got)
