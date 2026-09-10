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
from ..constants import Search as _S
from ..models.setting import Setting
from ..models.article import Article, ArticleTranslation, STATUS_PUBLISHED
from ..models.column import Column


# 内容类型标识（索引文档 uid 前缀）
TYPE_ARTICLE = 'article'


# ============================================================
# 插件搜索内容提供者协议
# ============================================================

class SearchProvider:
    """插件搜索内容提供者基类（插件按需子类化并经 get_search_provider 暴露）。

    用于把插件自有的前台公开内容（如产品）纳入全站搜索。约定：
      - type             内容类型标识，全局唯一（如 'product'），作为 uid 前缀
      - iter_docs(loc)   重建索引时产出该语言下全部可见文档 dict
      - get_doc(id, loc) 单条文档（保存时实时索引用）；不可见/不存在返回 None
      - sql_search(kw, loc, page, per_page)  SQL 兜底检索，返回 (items, total)
      - build_url(item)  请求上下文中为结果项生成详情 URL
    文档 dict 字段：id, title, summary, content(可含 HTML), column_id,
    column_name, column_slug, published_at(datetime)。
    结果 item 字段同 SqlLikeBackend 返回（需含 id/type/title/column_slug 等）。
    """

    type = ''

    def iter_docs(self, locale):
        return iter(())

    def get_doc(self, obj_id, locale):
        return None

    def sql_search(self, keyword, locale, page=1, per_page=20):
        return [], 0

    def build_url(self, item):
        return '#'


def get_search_providers():
    """收集启用插件的搜索提供者，返回 {type: provider}。

    每次调用遍历插件注册表（量小，开销可忽略）；单个插件异常静默跳过。
    """
    providers = {}
    try:
        from ..plugin_system import _registry, enabled_slugs
        enabled = set(enabled_slugs())
        for rec in _registry:
            if rec.slug not in enabled or rec.instance is None:
                continue
            try:
                prov = rec.instance.get_search_provider()
            except Exception:
                current_app.logger.exception(
                    '插件 %s 搜索提供者初始化失败', rec.slug)
                prov = None
            if prov is not None and getattr(prov, 'type', ''):
                providers[prov.type] = prov
    except Exception:
        pass
    return providers


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
    """构造文章写入索引的文档 dict。meili=True 时日期转 ISO 字符串。"""
    fields = _localized_text(article, col, locale)
    published = article.published_at or datetime.now()
    doc = {
        'id': article.id,
        'uid': f'{TYPE_ARTICLE}:{article.id}',
        'type': TYPE_ARTICLE,
        'title': fields['title'],
        'content': fields['content'],
        'summary': fields['summary'],
        'column_id': article.column_id,
        'column_name': fields['column_name'],
        'column_slug': fields['column_slug'],
        'published_at': published.isoformat() if meili else published,
        'status': article.status or STATUS_PUBLISHED,
    }
    if meili:
        doc['is_deleted'] = False
    return doc


def _provider_doc(prov, raw, meili=False):
    """归一化插件提供者产出的文档 dict 为索引文档。

    raw 至少含 id / title；content 可为 HTML（统一剥标签）；published_at 为
    datetime；提供者只需保证仅产出上架且未删除的内容。
    """
    published = raw.get('published_at') or datetime.now()
    doc = {
        'id': raw.get('id'),
        'uid': f'{prov.type}:{raw.get("id")}',
        'type': prov.type,
        'title': raw.get('title') or '',
        'content': _strip_html(raw.get('content') or ''),
        'summary': raw.get('summary') or '',
        'column_id': raw.get('column_id'),
        'column_name': raw.get('column_name') or '',
        'column_slug': raw.get('column_slug') or '',
        'published_at': published.isoformat() if meili else published,
        'status': STATUS_PUBLISHED,
    }
    if meili:
        doc['is_deleted'] = False
    return doc


def _result_item(doc):
    """从索引文档统一构造搜索结果 dict。"""
    return {
        'id': doc.get('id'),
        'uid': doc.get('uid') or f"{doc.get('type', TYPE_ARTICLE)}:{doc.get('id')}",
        'type': doc.get('type') or TYPE_ARTICLE,
        'title': doc.get('title', ''),
        'summary': doc.get('summary', ''),
        'column_id': doc.get('column_id'),
        'column_name': doc.get('column_name', ''),
        'column_slug': doc.get('column_slug', ''),
        'published_at': doc.get('published_at'),
        'url': None,  # 由视图层生成
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

    def index_object(self, type_, obj_id):
        """索引/更新插件内容单条记录（默认空实现，索引型后端覆写）。"""
        pass

    def unindex_object(self, type_, obj_id):
        """从全部语言索引中移除插件内容单条记录。"""
        pass

    def search(self, keyword, page=1, per_page=20, locale=None):
        """搜索，返回 (items, total)。
        items: [{id, uid, type, title, summary, column_id, column_name, published_at}]
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
    """使用 SQL LIKE 的简单搜索后端（文章 + 启用插件内容，支持翻译表匹配）。"""

    def index_article(self, article):
        pass  # SQL 后端无需索引

    def unindex_article(self, article_id):
        pass

    def _search_articles(self, like, loc, page, per_page):
        """文章 LIKE 检索（非默认语言同时匹配翻译表）。返回 (items, total)。"""
        from .i18n_content import t_field, get_default_locale
        q = Article.query.filter(
            Article.is_deleted == False,  # noqa: E712
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
                'uid': f'{TYPE_ARTICLE}:{a.id}',
                'type': TYPE_ARTICLE,
                'title': t_field(a, 'title', loc) or a.title or '',
                'summary': t_field(a, 'summary', loc) or '',
                'column_id': a.column_id,
                'column_name': (t_field(col, 'name', loc) or col.name or '') if col else '',
                'column_slug': col.slug if col else '',
                'published_at': a.published_at,
                'url': None,
            })
        return items, pagination.total

    def search(self, keyword, page=1, per_page=20, locale=None):
        """合并检索文章与启用插件内容（各来源取当前页窗口后按时间归并排序）。"""
        like = f'%{keyword}%'
        loc = _search_locale(locale)
        # 各来源取前 page*per_page 条，保证归并后当前页数据完整
        window = page * per_page
        items, total = self._search_articles(like, loc, 1, window)
        for prov in get_search_providers().values():
            try:
                p_items, p_total = prov.sql_search(keyword, loc,
                                                   page=1, per_page=window)
                items.extend(p_items or [])
                total += (p_total or 0)
            except Exception:
                current_app.logger.exception(
                    '插件 %s SQL 兜底搜索失败', prov.type)
        items.sort(key=lambda x: x.get('published_at') or datetime.min,
                   reverse=True)
        start = (page - 1) * per_page
        return items[start:start + per_page], total

    def rebuild_all(self):
        count = Article.query.filter_by(is_deleted=False).count()
        for prov in get_search_providers().values():
            try:
                for loc in _index_locales():
                    count += sum(1 for _ in prov.iter_docs(loc))
            except Exception:
                current_app.logger.exception(
                    '插件 %s 重建计数失败', prov.type)
        return count, 0

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
        uid=ID(stored=True, unique=True),
        type=ID(stored=True),
        id=NUMERIC(stored=True),
        title=TEXT(analyzer=_whoosh_analyzer, stored=True),
        content=TEXT(analyzer=_whoosh_analyzer),
        summary=TEXT(analyzer=_whoosh_analyzer, stored=True),
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

    def _ensure_current_schema(self):
        """旧版索引（v2.5.2 前无 uid/type 字段）一次性重建自愈。

        升级后未手动「重建索引」时，旧 schema 索引无法写入多类型文档；
        检测到任一语言索引 schema 过旧即全量重建（仅触发一次）。
        """
        for loc in _index_locales():
            index = _get_whoosh_index(loc)
            if index is not None and 'uid' not in index.schema:
                current_app.logger.info(
                    '检测到旧版搜索索引 schema，自动重建（%s）', loc)
                self.rebuild_all()
                return

    def index_article(self, article):
        self._ensure_current_schema()
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
                writer.delete_by_term('uid', f'{TYPE_ARTICLE}:{article_id}')
                writer.commit()
            except Exception:
                writer.cancel()

    def index_object(self, type_, obj_id):
        """索引/更新插件内容单条记录（写入全部语言索引）。"""
        prov = get_search_providers().get(type_)
        if prov is None:
            return
        self._ensure_current_schema()
        for loc in _index_locales():
            raw = prov.get_doc(obj_id, loc)
            index = _get_whoosh_index(loc, create=True)
            writer = index.writer()
            try:
                if raw is None:
                    # 下架/删除：从索引移除
                    writer.delete_by_term('uid', f'{type_}:{obj_id}')
                else:
                    writer.update_document(**_provider_doc(prov, raw))
                writer.commit()
            except Exception:
                writer.cancel()
                raise

    def unindex_object(self, type_, obj_id):
        for loc in _index_locales():
            index = _get_whoosh_index(loc)
            if index is None:
                continue
            writer = index.writer()
            try:
                writer.delete_by_term('uid', f'{type_}:{obj_id}')
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
        # 只召回已发布内容（索引可能包含草稿/归档）
        if 'status' in index.schema:
            from whoosh.query import Term
            query = query & Term('status', STATUS_PUBLISHED)
        searcher = index.searcher()
        try:
            results = searcher.search_page(query, page, pagelen=per_page)
            items = [_result_item({
                'id': r.get('id'),
                'uid': r.get('uid'),
                'type': r.get('type'),
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
        providers = get_search_providers()
        errors = 0
        indexed = 0
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
                        indexed += 1
                    except Exception:
                        errors += 1
                for prov in providers.values():
                    try:
                        for raw in prov.iter_docs(loc):
                            try:
                                writer.add_document(**_provider_doc(prov, raw))
                                indexed += 1
                            except Exception:
                                errors += 1
                    except Exception:
                        errors += 1
                        current_app.logger.exception(
                            '插件 %s 索引文档产出失败', prov.type)
                writer.commit()
            except Exception:
                writer.cancel()
                raise
        return indexed, errors

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
        self.unindex_object(TYPE_ARTICLE, article_id)

    def index_object(self, type_, obj_id):
        """索引/更新插件内容单条记录（写入全部语言索引）。"""
        import requests
        prov = get_search_providers().get(type_)
        if prov is None:
            return
        for loc in _index_locales():
            raw = prov.get_doc(obj_id, loc)
            if raw is None:
                self.unindex_object(type_, obj_id)
                continue
            doc = _provider_doc(prov, raw, meili=True)
            try:
                requests.put(
                    f'{self._get_url()}/indexes/{self.INDEX_NAME}_{loc}/documents',
                    json=[doc], headers=self._headers(), timeout=10
                )
            except Exception:
                current_app.logger.exception(
                    'Meili 索引 %s#%s 失败', type_, obj_id)

    def unindex_object(self, type_, obj_id):
        import requests
        from urllib.parse import quote
        uid = quote(f'{type_}:{obj_id}', safe='')
        for loc in _index_locales():
            try:
                requests.delete(
                    f'{self._get_url()}/indexes/{self.INDEX_NAME}_{loc}/documents/{uid}',
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
        providers = get_search_providers()
        indexed = 0
        for loc in _index_locales():
            index_name = f'{self.INDEX_NAME}_{loc}'
            # 创建索引（如不存在）；主键用 uid（文章/产品跨类型唯一）。
            # 注意：已存在且含文档的旧索引主键无法在线变更，需在 Meili 侧
            # 删除索引后重建，否则跨类型同 id 会互相覆盖（搜索仍可用）。
            try:
                requests.patch(
                    f'{self._get_url()}/indexes/{index_name}',
                    json={'primaryKey': 'uid'}, headers=self._headers(), timeout=10
                )
            except Exception:
                pass
            docs = []
            for a in articles:
                col = Column.query.get(a.column_id)
                docs.append(_build_doc(a, col, loc, meili=True))
            for prov in providers.values():
                try:
                    for raw in prov.iter_docs(loc):
                        docs.append(_provider_doc(prov, raw, meili=True))
                except Exception:
                    current_app.logger.exception(
                        'Meili 插件 %s 文档产出失败', prov.type)
            indexed += len(docs)
            # 分批发送（每批 1000）
            for i in range(0, len(docs), 1000):
                requests.put(
                    f'{self._get_url()}/indexes/{index_name}/documents',
                    json=docs[i:i + 1000], headers=self._headers(), timeout=30
                )
        return indexed, 0

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
    engine = Setting.get('search_engine', _S.DEFAULT_ENGINE)
    if engine == _S.ENGINE_WHOOSH:
        backend = WhooshBackend()
    elif engine == _S.ENGINE_MEILI:
        backend = MeilisearchBackend()
    else:
        backend = SqlLikeBackend()
    g._search_backend = backend
    return backend


def search_articles(keyword, page=1, per_page=20, locale=None):
    """公共搜索 API：返回 (items, total)。
    后端故障时自动回退到 SQL LIKE。locale 为当前语言代码。

    兜底策略：索引后端（Whoosh/Meilisearch）零命中时，再用实时 SQL 查一次。
    索引可能未建立或陈旧（如升级到多语言版本后未点「重建索引」），导致
    按外文关键词检索时漏召回；SQL 直接查翻译表，始终为最新数据。
    """
    if not keyword or not keyword.strip():
        return [], 0
    backend = get_backend()
    kw = keyword.strip()
    sql_backend = SqlLikeBackend()
    if not isinstance(backend, SqlLikeBackend):
        try:
            items, total = backend.search(kw, page=page, per_page=per_page, locale=locale)
            if total > 0:
                return items, total
        except Exception as e:
            current_app.logger.warning('搜索后端 %s 故障，回退到 SQL LIKE: %s',
                                       type(backend).__name__, e)
            return sql_backend.search(kw, page=page, per_page=per_page, locale=locale)
        # 索引零命中：用实时 SQL 兜底（索引未建/陈旧场景）
        try:
            sql_items, sql_total = sql_backend.search(
                kw, page=page, per_page=per_page, locale=locale)
            if sql_total > 0:
                current_app.logger.info(
                    '索引后端零命中，SQL 兜底召回 %d 条（关键词 %s，locale=%s）',
                    sql_total, kw, locale)
                return sql_items, sql_total
        except Exception:
            current_app.logger.exception('SQL 兜底搜索失败')
        return items, total
    try:
        return sql_backend.search(kw, page=page, per_page=per_page, locale=locale)
    except Exception as e:
        current_app.logger.warning('SQL LIKE 搜索失败: %s', e)
        return [], 0


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


def reindex_object(type_, obj_id):
    """插件内容保存/更新后重新索引（写入全部语言索引）。

    提供者 get_doc 返回 None（下架/不可见）时自动从索引移除。
    """
    if Setting.get('search_index_on_save') != 'on':
        return
    backend = get_backend()
    try:
        backend.index_object(type_, obj_id)
    except Exception as e:
        current_app.logger.warning('索引 %s#%s 失败: %s', type_, obj_id, e)


def unindex_object(type_, obj_id):
    """插件内容删除/下架后从全部语言索引中移除。"""
    if Setting.get('search_index_on_save') != 'on':
        return
    backend = get_backend()
    try:
        backend.unindex_object(type_, obj_id)
    except Exception as e:
        current_app.logger.warning('移除索引 %s#%s 失败: %s', type_, obj_id, e)


def build_result_url(item):
    """请求上下文中为搜索结果项生成详情 URL（按内容类型分发）。"""
    from flask import url_for
    type_ = item.get('type') or TYPE_ARTICLE
    if type_ != TYPE_ARTICLE:
        prov = get_search_providers().get(type_)
        if prov is not None:
            try:
                url = prov.build_url(item)
                if url:
                    return url
            except Exception:
                current_app.logger.exception(
                    '插件 %s 结果 URL 生成失败', type_)
    if item.get('column_slug') and item.get('id'):
        return url_for('frontend.article_detail',
                       slug=item['column_slug'], aid=item['id'])
    return '#'


def rebuild_all():
    """重建全部索引（全部语言）。返回 (indexed_count, error_count)。"""
    backend = get_backend()
    return backend.rebuild_all()


def health():
    """搜索后端健康检查。"""
    backend = get_backend()
    return backend.health()
