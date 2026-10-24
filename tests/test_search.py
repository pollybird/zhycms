"""搜索测试：Tantivy 索引、SQL 兜底、SearchProvider（v3.1.4 引擎切换后）。"""
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
            # 清掉进程内索引单例缓存，强制走"索引不存在"分支
            search_mod._tantivy_indexes = {}

        resp = client.get('/search?q=焊接')
        assert resp.status_code == 200
        assert '焊接'.encode() in resp.data

    def test_batch_ops_update_index(self, app, admin_client):
        """批量发布/删除操作逐篇更新搜索索引。

        此前批量路径只清栏目缓存、未触发单篇索引，导致 Tantivy 等
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


@pytest.mark.search
class TestTantivyBackend:
    """v3.1.4：Tantivy 引擎级行为（水合、uid 替换、删除、特殊字符）。"""

    def _make_indexed_article(self, app, title, slug):
        from app.extensions import db
        from app.models.workflow import STATUS_PUBLISHED
        from app.models.setting import Setting
        from app.utils.search import rebuild_all
        with app.app_context():
            Setting.set('search_engine', 'tantivy')
            col = make_column(name='Tantivy栏目', slug=slug)
            a = make_article(
                title=title, column_id=col.id,
                status=STATUS_PUBLISHED, content='Tantivy 测试正文内容')
            db.session.commit()
            rebuild_all()
            return a.id

    def test_hydrated_title_is_original(self, app):
        """结果标题为数据库原文（水合），非索引中的分词中间形态。"""
        aid = self._make_indexed_article(app, '精密焊接设备总览', 'tanti-col-1')
        from app.utils.search import TantivyBackend
        with app.app_context():
            items, total = TantivyBackend().search('焊接', locale='zh')
            assert total >= 1
            hit = next(i for i in items if i['id'] == aid)
            assert hit['title'] == '精密焊接设备总览'
            assert ' ' not in hit['title']  # 无分词空格

    def test_uid_replacement_no_duplicates(self, app):
        """同一文章重复索引不产生重复文档（写前删语义）。"""
        aid = self._make_indexed_article(app, '重复索引目标文章', 'tanti-col-2')
        from app.models.article import Article
        from app.utils.search import TantivyBackend
        with app.app_context():
            backend = TantivyBackend()
            article = Article.query.get(aid)
            backend.index_article(article)  # 重复索引
            items, total = backend.search('重复索引目标', locale='zh')
            same = [i for i in items if i['uid'] == f'article:{aid}']
            assert len(same) == 1

    def test_unindex_removes_document(self, app):
        """移除索引后不再命中。"""
        aid = self._make_indexed_article(app, '待移除索引的文章', 'tanti-col-3')
        from app.utils.search import TantivyBackend
        with app.app_context():
            backend = TantivyBackend()
            items, total = backend.search('待移除索引', locale='zh')
            assert any(i['uid'] == f'article:{aid}' for i in items)
            backend.unindex_article(aid)
            items, _ = backend.search('待移除索引', locale='zh')
            assert not any(i['uid'] == f'article:{aid}' for i in items)

    def test_special_chars_keyword_no_crash(self, app):
        """含查询语法字符/运算符的关键词不抛异常（tokenize 已剥离）。"""
        from app.utils.search import TantivyBackend
        with app.app_context():
            backend = TantivyBackend()
            for kw in ('企业:管理', '"系统"', 'AND OR NOT', '(())', 'CNC+加工'):
                items, total = backend.search(kw, locale='zh')
                assert isinstance(items, list) and isinstance(total, int)

    def test_unknown_engine_falls_back_to_sql(self, app):
        """残留未知引擎值（如旧 'whoosh'）回退 SQL LIKE 并告警，不抛异常。"""
        from app.extensions import db
        from app.models.setting import Setting
        from app.utils.search import get_backend, SqlLikeBackend
        with app.app_context():
            Setting.set('search_engine', 'whoosh')
            db.session.commit()
        try:
            # get_backend 按请求缓存于 g，需新请求上下文
            with app.test_request_context('/'):
                backend = get_backend()
                assert isinstance(backend, SqlLikeBackend)
        finally:
            with app.app_context():
                Setting.set('search_engine', 'tantivy')
                db.session.commit()
