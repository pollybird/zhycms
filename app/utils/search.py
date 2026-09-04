"""v2.4.0 全文搜索抽象层。

三后端回退链：Whoosh → Meilisearch → SQL LIKE。
通过 Setting 'search_engine' 选择引擎，运行时可切换。
索引策略：文章保存时同步索引（通过 clear_content_cache 钩子触发）。
"""
import os
import re
import html as html_lib
from datetime import datetime

from flask import current_app, g

from ..extensions import db
from ..models.setting import Setting
from ..models.article import Article, STATUS_PUBLISHED
from ..models.column import Column


# ============================================================
# 工具函数
# ============================================================

def _strip_html(text):
    """去除 HTML 标签并反转义实体。"""
    if not text:
        return ''
    # 先移除 script/style 内容
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # 再移除所有标签
    text = re.sub(r'<[^>]+>', '', text)
    # 反转义 HTML 实体
    text = html_lib.unescape(text)
    # 压缩空白
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _get_index_dir():
    """返回 Whoosh 索引目录路径。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    index_dir = os.path.join(base, 'instance', 'search_index')
    os.makedirs(index_dir, exist_ok=True)
    return index_dir


# ============================================================
# 后端基类
# ============================================================

class SearchBackend:
    """搜索后端抽象基类。"""

    def index_article(self, article):
        """索引/更新单篇文章。"""
        raise NotImplementedError

    def unindex_article(self, article_id):
        """从索引中移除文章。"""
        raise NotImplementedError

    def search(self, keyword, page=1, per_page=20):
        """搜索，返回 (items, total)。
        items: [{id, title, summary, column_id, column_name, published_at}]
        """
        raise NotImplementedError

    def rebuild_all(self):
        """重建全部索引。返回 (indexed_count, error_count)。"""
        raise NotImplementedError

    def health(self):
        """健康检查，返回 (ok: bool, message: str)。"""
        raise NotImplementedError


# ============================================================
# SQL LIKE 后端（回退/默认）
# ============================================================

class SqlLikeBackend(SearchBackend):
    """使用 SQL LIKE 的简单搜索后端。"""

    def index_article(self, article):
        pass  # SQL 后端无需索引

    def unindex_article(self, article_id):
        pass

    def search(self, keyword, page=1, per_page=20):
        """搜索标题、摘要和正文。"""
        like = f'%{keyword}%'
        pagination = Article.query.filter(
            Article.is_deleted == False,
            Article.status == STATUS_PUBLISHED,
            db.or_(
                Article.title.like(like),
                Article.summary.like(like),
                Article.content.like(like),
            )
        ).order_by(Article.published_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        items = []
        for a in pagination.items:
            col = Column.query.get(a.column_id)
            items.append({
                'id': a.id,
                'title': a.title,
                'summary': a.summary or '',
                'column_id': a.column_id,
                'column_name': col.name if col else '',
                'column_slug': col.slug if col else '',
                'published_at': a.published_at,
                'url': None,  # 由模板层生成
            })
        return items, pagination.total

    def rebuild_all(self):
        articles = Article.query.filter_by(is_deleted=False).all()
        return len(articles), 0

    def health(self):
        return True, 'SQL LIKE（无需外部服务）'


# ============================================================
# Whoosh 后端（主推荐）
# ============================================================

_whoosh_index = None  # 单例索引
_whoosh_analyzer = None


def _get_whoosh_schema():
    """返回 Whoosh 索引 schema。"""
    from whoosh.fields import Schema, TEXT, ID, NUMERIC, DATETIME, STORED
    # jieba 中文分词分析器（惰性加载）
    global _whoosh_analyzer
    if _whoosh_analyzer is None:
        from whoosh.analysis import RegexAnalyzer, LowercaseFilter
        from jieba.analyse import ChineseAnalyzer as _JiebaAnalyzer
        # 使用 jieba 分析器，支持中文分词
        _whoosh_analyzer = _JiebaAnalyzer()
    return Schema(
        id=NUMERIC(stored=True, unique=True),
        title=TEXT(analyzer=_whoosh_analyzer, stored=True),
        content=TEXT(analyzer=_whoosh_analyzer),
        summary=TEXT(analyzer=_whoosh_analyzer),
        column_id=NUMERIC(stored=True),
        column_name=TEXT(stored=True),
        column_slug=TEXT(stored=True),
        published_at=DATETIME(stored=True),
        status=ID(),
    )


def _get_whoosh_index():
    """获取或创建 Whoosh 索引（单例）。"""
    global _whoosh_index
    if _whoosh_index is not None:
        return _whoosh_index
    from whoosh.index import create_in, open_dir, exists_in
    index_dir = _get_index_dir()
    if exists_in(index_dir):
        _whoosh_index = open_dir(index_dir)
    else:
        _whoosh_index = create_in(index_dir, _get_whoosh_schema())
    return _whoosh_index


class WhooshBackend(SearchBackend):
    """Whoosh 全文搜索后端（纯 Python + jieba 中文分词）。"""

    def index_article(self, article):
        index = _get_whoosh_index()
        # 先删除旧索引
        self._delete_by_id(index, article.id)
        writer = index.writer()
        try:
            col = Column.query.get(article.column_id)
            content_text = _strip_html(article.content)
            writer.update_document(
                id=article.id,
                title=article.title or '',
                content=content_text,
                summary=article.summary or '',
                column_id=article.column_id,
                column_name=col.name if col else '',
                column_slug=col.slug if col else '',
                published_at=article.published_at or datetime.now(),
                status=article.status or STATUS_PUBLISHED,
            )
            writer.commit()
        except Exception:
            writer.cancel()
            raise

    def _delete_by_id(self, index, article_id):
        writer = index.writer()
        try:
            writer.delete_by_term('id', str(article_id))
            writer.commit()
        except Exception:
            writer.cancel()

    def unindex_article(self, article_id):
        index = _get_whoosh_index()
        self._delete_by_id(index, article_id)

    def search(self, keyword, page=1, per_page=20):
        from whoosh.qparser import MultifieldParser, OrGroup
        index = _get_whoosh_index()
        # 搜索标题 + 正文 + 摘要
        parser = MultifieldParser(
            ['title', 'content', 'summary'],
            schema=index.schema
        )
        # 支持中文分词后的搜索
        query = parser.parse(keyword)
        searcher = index.searcher()
        try:
            # Whoosh 的 page 参数从 1 开始
            results = searcher.search_page(query, page, pagelen=per_page)
            items = []
            for r in results:
                items.append({
                    'id': r.get('id'),
                    'title': r.get('title', ''),
                    'summary': r.get('summary', ''),
                    'column_id': r.get('column_id'),
                    'column_name': r.get('column_name', ''),
                    'column_slug': r.get('column_slug', ''),
                    'published_at': r.get('published_at'),
                    'url': None,
                })
            return items, results.total
        finally:
            searcher.close()

    def rebuild_all(self):
        from whoosh.index import create_in, exists_in
        index_dir = _get_index_dir()
        # 重建：先删除旧索引
        if exists_in(index_dir):
            import shutil
            shutil.rmtree(index_dir)
            os.makedirs(index_dir, exist_ok=True)
        # 重置单例
        global _whoosh_index
        _whoosh_index = create_in(index_dir, _get_whoosh_schema())
        articles = Article.query.filter_by(is_deleted=False).all()
        indexed = 0
        errors = 0
        index = _get_whoosh_index()
        writer = index.writer()
        try:
            for a in articles:
                try:
                    col = Column.query.get(a.column_id)
                    writer.add_document(
                        id=a.id,
                        title=a.title or '',
                        content=_strip_html(a.content),
                        summary=a.summary or '',
                        column_id=a.column_id,
                        column_name=col.name if col else '',
                        column_slug=col.slug if col else '',
                        published_at=a.published_at or datetime.now(),
                        status=a.status or STATUS_PUBLISHED,
                    )
                    indexed += 1
                except Exception:
                    errors += 1
            writer.commit()
        except Exception:
            writer.cancel()
            raise
        return indexed, errors

    def health(self):
        try:
            index = _get_whoosh_index()
            return True, f'Whoosh 索引正常（{index.doc_count()} 篇文档）'
        except Exception as e:
            return False, f'Whoosh 索引异常: {e}'


# ============================================================
# Meilisearch 后端（可选，大型站点）
# ============================================================

class MeilisearchBackend(SearchBackend):
    """Meilisearch 全文搜索后端（需运行 Meilisearch 服务）。"""

    INDEX_NAME = 'zhycms_articles'

    def _get_url(self):
        base = Setting.get('search_meili_url', '').rstrip('/')
        return base if base else 'http://127.0.0.1:7700'

    def _get_key(self):
        return Setting.get('search_meili_key', '')

    def _headers(self):
        key = self._get_key()
        return {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'} if key else {}

    def index_article(self, article):
        import requests
        col = Column.query.get(article.column_id)
        doc = {
            'id': article.id,
            'title': article.title or '',
            'content': _strip_html(article.content),
            'summary': article.summary or '',
            'column_id': article.column_id,
            'column_name': col.name if col else '',
            'column_slug': col.slug if col else '',
            'published_at': (article.published_at or datetime.now()).isoformat(),
            'status': article.status or STATUS_PUBLISHED,
            'is_deleted': False,
        }
        requests.put(
            f'{self._get_url()}/indexes/{self.INDEX_NAME}/documents',
            json=[doc], headers=self._headers(), timeout=10
        )

    def unindex_article(self, article_id):
        import requests
        requests.delete(
            f'{self._get_url()}/indexes/{self.INDEX_NAME}/documents/{article_id}',
            headers=self._headers(), timeout=10
        )

    def search(self, keyword, page=1, per_page=20):
        import requests
        resp = requests.post(
            f'{self._get_url()}/indexes/{self.INDEX_NAME}/search',
            json={
                'q': keyword,
                'page': page,
                'hitsPerPage': per_page,
                'filter': 'status = published AND is_deleted = false',
            },
            headers=self._headers(), timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get('hits', [])
        total = data.get('totalHits', len(hits))
        items = []
        for h in hits:
            items.append({
                'id': h.get('id'),
                'title': h.get('title', ''),
                'summary': h.get('summary', ''),
                'column_id': h.get('column_id'),
                'column_name': h.get('column_name', ''),
                'column_slug': h.get('column_slug', ''),
                'published_at': h.get('published_at'),
                'url': None,
            })
        return items, total

    def rebuild_all(self):
        import requests
        # 创建索引（如不存在）
        requests.patch(
            f'{self._get_url()}/indexes/{self.INDEX_NAME}',
            json={'primaryKey': 'id'}, headers=self._headers(), timeout=10
        )
        # 批量索引
        articles = Article.query.filter_by(is_deleted=False).all()
        docs = []
        for a in articles:
            col = Column.query.get(a.column_id)
            docs.append({
                'id': a.id,
                'title': a.title or '',
                'content': _strip_html(a.content),
                'summary': a.summary or '',
                'column_id': a.column_id,
                'column_name': col.name if col else '',
                'column_slug': col.slug if col else '',
                'published_at': (a.published_at or datetime.now()).isoformat(),
                'status': a.status or STATUS_PUBLISHED,
                'is_deleted': False,
            })
        # 分批发送（每批 1000）
        for i in range(0, len(docs), 1000):
            batch = docs[i:i + 1000]
            requests.put(
                f'{self._get_url()}/indexes/{self.INDEX_NAME}/documents',
                json=batch, headers=self._headers(), timeout=30
            )
        return len(docs), 0

    def health(self):
        try:
            import requests
            resp = requests.get(f'{self._get_url()}/health', timeout=5)
            return resp.status_code == 200, f'Meilisearch: {self._get_url()}'
        except Exception as e:
            return False, f'Meilisearch 不可达: {e}'


# ============================================================
# 后端工厂与公共 API
# ============================================================

def get_backend():
    """根据 Setting 返回当前搜索后端（每请求缓存）。"""
    if hasattr(g, '_search_backend'):
        return g._search_backend
    engine = Setting.get('search_engine', 'whoosh')
    if engine == 'whoosh':
        backend = WhooshBackend()
    elif engine == 'meilisearch':
        backend = MeilisearchBackend()
    else:
        backend = SqlLikeBackend()
    g._search_backend = backend
    return backend


def search_articles(keyword, page=1, per_page=20):
    """公共搜索 API：返回 (items, total)。
    后端故障时自动回退到 SQL LIKE。
    """
    if not keyword or not keyword.strip():
        return [], 0
    backend = get_backend()
    try:
        return backend.search(keyword.strip(), page=page, per_page=per_page)
    except Exception as e:
        current_app.logger.warning('搜索后端 %s 故障，回退到 SQL LIKE: %s',
                                   type(backend).__name__, e)
        return SqlLikeBackend().search(keyword.strip(), page=page, per_page=per_page)


def reindex_article(article_id):
    """文章保存/更新后重新索引。"""
    if Setting.get('search_index_on_save') != 'on':
        return
    article = Article.query.get(article_id)
    if article is None or article.is_deleted:
        unindex_article(article_id)
        return
    backend = get_backend()
    try:
        backend.index_article(article)
    except Exception as e:
        current_app.logger.warning('索引文章 %s 失败: %s', article_id, e)


def unindex_article(article_id):
    """文章删除后从索引中移除。"""
    if Setting.get('search_index_on_save') != 'on':
        return
    backend = get_backend()
    try:
        backend.unindex_article(article_id)
    except Exception as e:
        current_app.logger.warning('移除索引 %s 失败: %s', article_id, e)


def rebuild_all():
    """重建全部索引。返回 (indexed_count, error_count)。"""
    backend = get_backend()
    return backend.rebuild_all()


def health():
    """搜索后端健康检查。"""
    backend = get_backend()
    return backend.health()
