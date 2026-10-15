"""v3.1.3 M7-M10 性能与并发健壮性测试（GitCode issue #3）。

M7  Setting.get() 请求级整表缓存 + set() 写后失效
M8  浏览量缓存累加 + 周期/阈值合并回 DB（含整页缓存命中路径）
M9  首页批量拉取去 N+1 + 栏目树请求级缓存
M10 用户名唯一性竞态（IntegrityError → 业务错误而非 500）

计数口径：仅统计 SELECT ... FROM <主表>（排除 i18n 翻译表惰性加载与 INSERT/UPDATE）。
"""
import re
from unittest.mock import patch

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import MultiDict

from app.extensions import db
from app.models.setting import Setting
from app.models.column import Column
from tests.factories import make_column, make_article

pytestmark = pytest.mark.performance


class _QueryCounter:
    """SQL 计数器：仅统计 SELECT 且 FROM 子句命中给定正则的语句。"""

    def __init__(self, engine, pattern):
        self.state = {'n': 0}
        self._re = re.compile(pattern, re.IGNORECASE)

        def _before_cursor_execute(conn, cursor, statement, parameters,
                                   context, executemany):
            s = statement.lstrip().lower()
            if s.startswith('select') and self._re.search(s):
                self.state['n'] += 1

        self._fn = _before_cursor_execute
        event.listen(engine, 'before_cursor_execute', self._fn)

    def remove(self, engine):
        try:
            event.remove(engine, 'before_cursor_execute', self._fn)
        except Exception:
            pass


def _seed_setting(app, key, value):
    """落库一个测试专用 Setting 并提交（计数基线自洽）。"""
    with app.app_context():
        Setting.set(key, value)
        db.session.commit()


# ============================================================
# M7：Setting.get() 请求级缓存
# ============================================================

@pytest.mark.performance
class TestM7SettingRequestCache:

    def test_existing_key_one_query_then_zero(self, app):
        """已落库键：请求内首查 1 条（整表映射），后续任意读零 SQL。"""
        _seed_setting(app, 'm7seed', 'x')
        with app.app_context():
            counter = _QueryCounter(db.engine, r'from settings\b')
            try:
                assert Setting.get('m7seed') == 'x'
                assert counter.state['n'] == 1
                # 同请求内再读任意键（含重复键 / 默认值键）：零新增 SQL
                Setting.get('m7seed')
                Setting.get_dict()
                assert counter.state['n'] == 1
            finally:
                counter.remove(db.engine)

    def test_missing_key_backfilled_once(self, app):
        _seed_setting(app, 'm7seed', 'x')
        with app.app_context():
            counter = _QueryCounter(db.engine, r'from settings\b')
            try:
                Setting.get('m7seed')  # 建整表映射：1 查询
                assert counter.state['n'] == 1
                # 键不在整表映射：首次落库查询并回填映射
                assert Setting.get('m7-no-such-key', 'fallback') == 'fallback'
                assert counter.state['n'] == 2
                # 回填后重复读取：零新增 SQL
                Setting.get('m7-no-such-key', 'fallback')
                assert counter.state['n'] == 2
            finally:
                counter.remove(db.engine)

    def test_set_invalidates_request_cache(self, app):
        _seed_setting(app, 'm7inv', 'old')
        with app.app_context():
            counter = _QueryCounter(db.engine, r'from settings\b')
            try:
                assert Setting.get('m7inv') == 'old'
                Setting.set('m7inv', 'new')          # set 内 1 次 first() + 失效
                # 同请求内写后立即可见（失效后重查重建映射）
                assert Setting.get('m7inv') == 'new'
                assert counter.state['n'] == 3       # 首查 + set + 重查
            finally:
                counter.remove(db.engine)
                db.session.rollback()

    def test_get_dict_reuses_map(self, app):
        _seed_setting(app, 'm7seed2', 'y')
        with app.app_context():
            counter = _QueryCounter(db.engine, r'from settings\b')
            try:
                Setting.get('m7seed2')  # 建映射：1 查询
                assert counter.state['n'] == 1
                d = Setting.get_dict()
                assert d['m7seed2'] == 'y'
                assert counter.state['n'] == 1  # 复用映射，不再查询
            finally:
                counter.remove(db.engine)


# ============================================================
# M8：浏览量缓存累加 + 合并回 DB
# ============================================================

@pytest.mark.performance
class TestM8ViewCounter:

    def test_incr_batch_and_flush(self, app):
        from app.models.article import Article
        from app.frontend.views import _incr_view, _flush_view_counts
        with app.app_context():
            col = make_column(slug='m8-flush-col')
            article = make_article(column_id=col.id)
            db.session.commit()

            for _ in range(100):
                _incr_view(article.id)
            # 合并前 DB 未增长（写放大收口）
            db.session.expire_all()
            assert Article.query.get(article.id).viewed in (None, 0)

            _flush_view_counts()
            db.session.expire_all()
            assert Article.query.get(article.id).viewed == 100

    def test_flush_without_pending_noop(self, app):
        from app.frontend.views import _flush_view_counts
        with app.app_context():
            _flush_view_counts()  # 无待合并数据，不应抛异常

    def test_cached_article_page_still_counts(self, app, client):
        """整页缓存命中时浏览量仍增长（原缺陷：命中路径不执行视图体）。"""
        from app.extensions import cache
        from app.models.article import Article
        from app.frontend.views import _flush_view_counts
        with app.app_context():
            col = make_column(slug='m8-cache-col')
            article = make_article(column_id=col.id)
            db.session.commit()
            Setting.set('cache_enable', 'on')
            Setting.set('cache_ttl_article', '300')
            db.session.commit()
            url = f'/column/{col.slug}/article/{article.id}'
            try:
                assert client.get(url).status_code == 200   # 未命中，视图体计数
                assert client.get(url).status_code == 200   # 命中，装饰器计数
                _flush_view_counts()
                db.session.expire_all()
                assert Article.query.get(article.id).viewed == 2
            finally:
                Setting.set('cache_enable', '')
                db.session.commit()
                try:
                    cache.clear()
                except Exception:
                    pass


# ============================================================
# M9：首页批量拉取 + 栏目树请求级缓存
# ============================================================

@pytest.mark.performance
class TestM9TreeAndHomeBatch:

    def test_get_tree_cached_query_count(self, app):
        with app.app_context():
            counter = _QueryCounter(db.engine, r'from columns\b')
            try:
                Column.get_tree_cached(enabled_only=True)
                assert counter.state['n'] == 1
                Column.get_tree_cached(enabled_only=True)  # 同请求第二次：零 SQL
                assert counter.state['n'] == 1
                Column.invalidate_tree_cache()
                Column.get_tree_cached(enabled_only=True)  # 失效后重查
                assert counter.state['n'] == 2
            finally:
                counter.remove(db.engine)

    def test_tree_cache_invalidated_on_content_change(self, app):
        from app.utils.helpers import clear_content_cache
        with app.app_context():
            counter = _QueryCounter(db.engine, r'from columns\b')
            try:
                Column.get_tree_cached(enabled_only=True)
                assert counter.state['n'] == 1
                col = make_column(slug='m9-invalidate-col')
                db.session.flush()
                clear_content_cache(column_id=col.id)  # 内容变更钩子
                cols = Column.get_tree_cached(enabled_only=True)
                assert counter.state['n'] == 2  # 失效后重建
                assert any(c.id == col.id for c in cols)
            finally:
                counter.remove(db.engine)
                db.session.rollback()

    def test_home_section_data_three_queries(self, app):
        from app.frontend.views import _home_section_data
        with app.app_context():
            col = make_column(slug='products', col_type='list')
            article = make_article(column_id=col.id)
            db.session.commit()

            # 主表口径：栏目 + 子栏目 + 文章 各 1 条（翻译表惰性加载不计）
            counter = _QueryCounter(db.engine, r'from (columns|articles)\b')
            try:
                sections = _home_section_data()
                assert counter.state['n'] == 3
            finally:
                counter.remove(db.engine)
            assert sections['products'] == (col, [article])

    def test_home_page_renders(self, client):
        assert client.get('/').status_code == 200


# ============================================================
# M10：用户名唯一性竞态
# ============================================================

@pytest.mark.performance
class TestM10UserUniqueRace:

    def test_duplicate_username_business_error(self, app):
        from app.services.user_service import create_user
        # 请求上下文：create_user 内 _gettext→select_locale 需 request
        with app.test_request_context('/'):
            form = MultiDict({
                'username': 'm10dupuser',
                'password': 'pass123456',
                'confirm_password': 'pass123456',
            })
            user, _ = create_user(form_data=form)
            assert user is not None
            db.session.commit()

            user2, msgs2 = create_user(form_data=form)
            assert user2 is None
            assert any('用户名已存在' in m for _, m in msgs2)

    def test_integrity_error_race_returns_business_error(self, app):
        """并发竞态：预检查通过但 DB 唯一索引拒绝 → 业务错误而非 500。"""
        from app.services.user_service import create_user
        with app.test_request_context('/'):
            form = MultiDict({
                'username': 'm10raceuser',
                'password': 'pass123456',
                'confirm_password': 'pass123456',
            })
            err = IntegrityError('INSERT INTO users...', {}, Exception('UNIQUE'))
            with patch.object(db.session, 'commit', side_effect=err):
                user, msgs = create_user(form_data=form)
            assert user is None
            assert any('用户名已存在' in m for _, m in msgs)

    def test_create_user_via_endpoint_no_500(self, admin_client):
        """后台创建重复用户名：返回表单页 + flash 错误，无 500。"""
        form = {
            'username': 'm10endpoint',
            'password': 'pass123456',
            'confirm_password': 'pass123456',
            'nickname': '端点用户',
        }
        resp1 = admin_client.post('/admin/users/create', data=form)
        assert resp1.status_code in (200, 302)
        resp2 = admin_client.post('/admin/users/create', data=form)
        assert resp2.status_code == 200
        assert '用户名已存在'.encode('utf-8') in resp2.data or \
            '用户名已存在' in resp2.get_data(as_text=True)
