"""v2.4.0 全文搜索抽象层（v2.5.1 起支持内容级多语言）。

三后端回退链：Whoosh → Meilisearch → SQL LIKE。
通过 Setting 'search_engine' 选择引擎，运行时可切换。
索引策略：文章保存时同步索引（通过 clear_content_cache 钩子触发）。

v2.5.1 多语言：
- Whoosh 按语言分索引目录 instance/search_index/<locale>/
- Meilisearch 按语言分索引 zhycms_articles_<locale>
- 每种语言的文档内容经 t_field 解析（翻译表 → 无翻译回退主表，与前台一致）
- 搜索按当前 locale 选索引；locale 索引不存在时回退默认语言索引
- i18n 未开启时仅维护/检索默认语言索引，行为与 v2.5.0 完全一致
"""
import os
import re
import html as html_lib
from datetime import datetime

from flask import current_app, g

from ..extensions import db
from ..models.setting import Setting
from ..models.article import Article, ArticleTranslation, STATUS_PUBLISHED
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


def _get_index_root():
    """返回 Whoosh 索引根目录 instance/search_index/。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    root = os.path.join(base, 'instance', 'search_index')
    os.makedirs(root, exist_ok=True)
    return root


def _get_index_dir(locale):
    """返回某语言的 Whoosh 索引目录 instance/search_index/<locale>/。"""
    d = os.path.join(_get_index_root(), locale)
    os.makedirs(d, exist_ok=True)
    return d


# ---------- 多语言辅助 ----------

def _index_locales():
    """返回需要维护索引的语言代码列表。

    i18n 开启：默认语言 + 全部可用语种；关闭：仅默认语言。
    """
    try:
        from .i18n_content import i18n_enabled, get_available_locales, get_default_locale
        default = get_default_locale()
        if i18n_enabled():
            locs = list(get_available_locales())
            if default not in locs:
                locs.insert(0, default)
            return locs
        return [default]
    except Exception:
        return ['zh']


def _search_locale(locale):
    """归一化搜索语言：i18n 关闭或 locale 无效时回退默认语言。"""
    try:
        from .i18n_content import i18n_enabled, get_available_locales, get_default_locale
        default = get_default_locale()
        if not i18n_enabled():
            return default
        if locale and locale in get_available_locales():
            return locale
        return default
    except Exception:
        return 'zh'


def _localized_text(article, col, locale):
    """解析文章在指定语言下的检索字段（翻译 → 回退主表）。"""
    from .i18n_content import t_field
    title = t_field(article, 'title', locale) or article.title or ''
    content = _strip_html(t_field(article, 'content', locale) or article.content or '')
    summary = t_field(article, 'summary', locale) or article.summary or ''
    column_name = ''
    if col is not None:
        column_name = t_field(col, 'name', locale) or col.name or ''
    return {
        'title': title,
        'content': content,
        'summary': summary or '',
        'column_name': column_name,
        'column_slug': col.slug if col else '',
    }


def _build_doc(article, col, locale, meili=False):
    """构造写入索引的文档 dict。meili=True 时日期转 ISO 字符串。"""
    fields = _localized_text(article, col, locale)
    published = article.published_at or datetime.now()
    return {
        'id': article.id,
        'title': fields['title'],
        'content': fields['content'],
        'summary': fields['summary'],
        'column_id': article.column_id,
        'column_name': fields['column_name'],
        'column_slug': fields['column_slug'],
        'published_at': published.isoformat() if meili else published,
        'status': article.status or STATUS_PUBLISHED,
        **({'is_deleted': False} if meili else {}),
    }


def _result_item(doc):
    """从索引文档统一构造搜索结果 dict。"""
    return {
        'id': doc.get('id'),
        'title': doc.get('title', ''),
        'summary': doc.get('summary', ''),
        'column_id': doc.get('column_id'),
        'column_name': doc.get('column_name', ''),
        'column_slug': doc.get('column_slug', ''),
        'published_at': doc.get('published_at'),
        'url': None,  # 由模板层生成
    }


# ============================================================
# 后端基类
# ============================================================

class SearchBackend:
    """搜索后端抽象基类。"""

    def index_article(self, article):
        """索引/更新单篇文章（写入全部语言索引）。"""
        raise NotImplementedError

    def unindex_article(self, article_id):
        """从全部语言索引中移除文章。"""
        raise NotImplementedError

    def search(self, keyword, page=1, per_page=20, locale=None):
        """搜索，返回 (items, total)。
        items: [{id, title, summary, column_id, column_name, published_at}]
        """
        raise NotImplementedError

    def rebuild_all(self):
        """重建全部索引（全部语言）。返回 (indexed_count, error_count)。"""
        raise NotImplementedError

    def health(self):
        """健康检查，返回 (ok: bool, message: str)。"""
        raise NotImplementedError


# ============================================================
# SQL LIKE 后端（回退/默认）
# ============================================================

class SqlLikeBackend(SearchBackend):
    """使用 SQL LIKE 的简单搜索后端（支持翻译表匹配）。"""

    def index_article(self, article):
        pass  # SQL 后端无需索引

    def unindex_article(self, article_id):
        pass

    def search(self, keyword, page=1, per_page=20, locale=None):
        """搜索标题、摘要和正文（非默认语言同时匹配翻译表）。"""
        from .i18n_content import t_field, get_default_locale
        like = f'%{keyword}%'
        loc = _search_locale(locale)
        q = Article.query.filter(
            Article.is_deleted == False,
            Article.status == STATUS_PUBLISHED,
        )
        main_match = db.or_(
            Article.title.like(like),
            Article.summary.like(like),
            Article.content.like(like),
        )
        if loc != get_default_locale():
            # 非默认语言：命中翻译表，或命中主表（未翻译文章回退）
            trans_ids = db.session.query(ArticleTranslation.article_id).filter(
                ArticleTranslation.locale == loc,
                db.or_(
                    ArticleTranslation.title.like(like),
                    ArticleTranslation.summary.like(like),
                    ArticleTranslation.content.like(like),
                )
            )
            q = q.filter(db.or_(Article.id.in_(trans_ids), main_match))
        else:
            q = q.filter(main_match)
        pagination = q.order_by(Article.published_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        items = []
        for a in pagination.items:
            col = Column.query.get(a.column_id)
            items.append({
                'id': a.id,
                'title': t_field(a, 'title', loc) or a.title or '',
                'summary': t_field(a, 'summary', loc) or '',
                'column_id': a.column_id,
                'column_name': (t_field(col, 'name', loc) or col.name or '') if col else '',
                'column_slug': col.slug if col else '',
                'published_at': a.published_at,
                'url': None,
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

_whoosh_indexes = {}  # {locale: index} 单例缓存
_whoosh_analyzer = None


def _get_whoosh_schema():
    """返回 Whoosh 索引 schema。"""
    from whoosh.fields import Schema, TEXT, ID, NUMERIC, DATETIME
    # jieba 中文分词分析器（惰性加载）；对中英文混排均有效
    global _whoosh_analyzer
    if _whoosh_analyzer is None:
        from jieba.analyse import ChineseAnalyzer as _JiebaAnalyzer
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


def _get_whoosh_index(locale, create=False):
    """获取指定语言的 Whoosh 索引（单例）。

    create=False 且索引不存在时返回 None（供搜索回退判断）。
    """
    if locale in _whoosh_indexes:
        return _whoosh_indexes[locale]
    from whoosh.index import create_in, open_dir, exists_in
    index_dir = _get_index_dir(locale)
    if exists_in(index_dir):
        idx = open_dir(index_dir)
    elif create:
        idx = create_in(index_dir, _get_whoosh_schema())
    else:
        return None
    _whoosh_indexes[locale] = idx
    return idx


class WhooshBackend(SearchBackend):
    """Whoosh 全文搜索后端（纯 Python + jieba 中文分词，按语言分索引）。"""

    def index_article(self, article):
        col = Column.query.get(article.column_id)
        for loc in _index_locales():
            index = _get_whoosh_index(loc, create=True)
            writer = index.writer()
            try:
                writer.update_document(**_build_doc(article, col, loc))
                writer.commit()
            except Exception:
                writer.cancel()
                raise

    def unindex_article(self, article_id):
        for loc in _index_locales():
            index = _get_whoosh_index(loc)
            if index is None:
                continue
            writer = index.writer()
            try:
                writer.delete_by_term('id', article_id)
                writer.commit()
            except Exception:
                writer.cancel()

    def search(self, keyword, page=1, per_page=20, locale=None):
        from whoosh.qparser import MultifieldParser
        loc = _search_locale(locale)
        index = _get_whoosh_index(loc)
        if index is None:
            # 该语言索引尚未建立（如刚开启 i18n 未重建），回退默认语言索引
            default = _search_locale(None)
            if default != loc:
                index = _get_whoosh_index(default)
        if index is None:
            return [], 0
        parser = MultifieldParser(
            ['title', 'content', 'summary'],
            schema=index.schema
        )
        query = parser.parse(keyword)
        searcher = index.searcher()
        try:
            results = searcher.search_page(query, page, pagelen=per_page)
            items = [_result_item({
                'id': r.get('id'),
                'title': r.get('title', ''),
                'summary': r.get('summary', ''),
                'column_id': r.get('column_id'),
                'column_name': r.get('column_name', ''),
                'column_slug': r.get('column_slug', ''),
                'published_at': r.get('published_at'),
            }) for r in results]
            return items, results.total
        finally:
            searcher.close()

    def rebuild_all(self):
        from whoosh.index import create_in
        import shutil
        # 重建：清空整个索引根目录（含旧的单层结构与各语言子目录）
        root = _get_index_root()
        if os.path.isdir(root):
            shutil.rmtree(root)
        os.makedirs(root, exist_ok=True)
        global _whoosh_indexes
        _whoosh_indexes = {}

        articles = Article.query.filter_by(is_deleted=False).all()
        errors = 0
        locales = _index_locales()
        for loc in locales:
            index_dir = _get_index_dir(loc)
            index = create_in(index_dir, _get_whoosh_schema())
            _whoosh_indexes[loc] = index
            writer = index.writer()
            try:
                for a in articles:
                    try:
                        col = Column.query.get(a.column_id)
                        writer.add_document(**_build_doc(a, col, loc))
                    except Exception:
                        errors += 1
                writer.commit()
            except Exception:
                writer.cancel()
                raise
        return len(articles), errors

    def health(self):
        try:
            parts = []
            for loc in _index_locales():
                index = _get_whoosh_index(loc)
                count = index.doc_count() if index is not None else 0
                parts.append(f'{loc}:{count}')
            return True, f'Whoosh 索引正常（{len(_index_locales())} 种语言，文档数 {", ".join(parts)}）'
        except Exception as e:
            return False, f'Whoosh 索引异常: {e}'


# ============================================================
# Meilisearch 后端（可选，大型站点）
# ============================================================

class MeilisearchBackend(SearchBackend):
    """Meilisearch 全文搜索后端（需运行 Meilisearch 服务，按语言分索引）。"""

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
        for loc in _index_locales():
            doc = _build_doc(article, col, loc, meili=True)
            requests.put(
                f'{self._get_url()}/indexes/{self.INDEX_NAME}_{loc}/documents',
                json=[doc], headers=self._headers(), timeout=10
            )

    def unindex_article(self, article_id):
        import requests
        for loc in _index_locales():
            try:
                requests.delete(
                    f'{self._get_url()}/indexes/{self.INDEX_NAME}_{loc}/documents/{article_id}',
                    headers=self._headers(), timeout=10
                )
            except Exception:
                pass

    def search(self, keyword, page=1, per_page=20, locale=None):
        import requests
        loc = _search_locale(locale)
        resp = requests.post(
            f'{self._get_url()}/indexes/{self.INDEX_NAME}_{loc}/search',
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
        items = [_result_item(h) for h in hits]
        return items, total

    def rebuild_all(self):
        import requests
        articles = Article.query.filter_by(is_deleted=False).all()
        for loc in _index_locales():
            index_name = f'{self.INDEX_NAME}_{loc}'
            # 创建索引（如不存在）
            requests.patch(
                f'{self._get_url()}/indexes/{index_name}',
                json={'primaryKey': 'id'}, headers=self._headers(), timeout=10
            )
            docs = []
            for a in articles:
                col = Column.query.get(a.column_id)
                docs.append(_build_doc(a, col, loc, meili=True))
            # 分批发送（每批 1000）
            for i in range(0, len(docs), 1000):
                requests.put(
                    f'{self._get_url()}/indexes/{index_name}/documents',
                    json=docs[i:i + 1000], headers=self._headers(), timeout=30
                )
        return len(articles), 0

    def health(self):
        try:
            import requests
            resp = requests.get(f'{self._get_url()}/health', timeout=5)
            locs = ', '.join(_index_locales())
            return resp.status_code == 200, f'Meilisearch: {self._get_url()}（索引语言: {locs}）'
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


def search_articles(keyword, page=1, per_page=20, locale=None):
    """公共搜索 API：返回 (items, total)。
    后端故障时自动回退到 SQL LIKE。locale 为当前语言代码。
    """
    if not keyword or not keyword.strip():
        return [], 0
    backend = get_backend()
    kw = keyword.strip()
    try:
        return backend.search(kw, page=page, per_page=per_page, locale=locale)
    except Exception as e:
        current_app.logger.warning('搜索后端 %s 故障，回退到 SQL LIKE: %s',
                                   type(backend).__name__, e)
        return SqlLikeBackend().search(kw, page=page, per_page=per_page, locale=locale)


def reindex_article(article_id):
    """文章保存/更新后重新索引（写入全部语言索引）。"""
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
    """文章删除后从全部语言索引中移除。"""
    if Setting.get('search_index_on_save') != 'on':
        return
    backend = get_backend()
    try:
        backend.unindex_article(article_id)
    except Exception as e:
        current_app.logger.warning('移除索引 %s 失败: %s', article_id, e)


def rebuild_all():
    """重建全部索引（全部语言）。返回 (indexed_count, error_count)。"""
    backend = get_backend()
    return backend.rebuild_all()


def health():
    """搜索后端健康检查。"""
    backend = get_backend()
    return backend.health()
