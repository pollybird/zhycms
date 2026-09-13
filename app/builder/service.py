"""构建器业务服务：页面、草稿、发布、修订、默认布局初始化。"""
import json
import os
from datetime import datetime

from ..constants import Builder as _B
from ..extensions import db
from ..models.builder import BuilderPage, BuilderRevision
from ..utils.themes import THEMES_DIR, get_active_theme
from .schema import (
    validate_layout, loads_layout, dumps_layout, LayoutError,
)

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

_FIXTURE_FILES = {
    _B.SCOPE_HOME: 'home.json',
    _B.SCOPE_PAGE: 'page.json',
    _B.SCOPE_LIST: 'list.json',
    _B.SCOPE_ARTICLE: 'article.json',
}


# ============================================================
# 查询
# ============================================================

def get_page(scope, column_id=None):
    if scope not in _B.SCOPES:
        return None
    q = BuilderPage.query.filter_by(scope=scope)
    if column_id is None:
        q = q.filter(BuilderPage.column_id.is_(None))
    else:
        q = q.filter_by(column_id=column_id)
    return q.first()


def get_or_create_page(scope, column_id=None, name='', commit=True):
    """取页面记录，不存在则创建（空草稿）。"""
    page = get_page(scope, column_id)
    if page is not None:
        return page, False
    if scope not in _B.SCOPES:
        raise LayoutError(f'非法作用域：{scope}')
    if scope == _B.SCOPE_HOME and column_id is not None:
        raise LayoutError('首页不能绑定栏目')
    page = BuilderPage(
        scope=scope, column_id=column_id, name=name or _default_name(scope, column_id),
        status=_B.STATUS_DRAFT,
    )
    db.session.add(page)
    if commit:
        db.session.commit()
    return page, True


def get_published_layout(scope, column_id=None):
    """前台渲染入口：返回已发布布局 dict，无则 None。

    article 作用域：栏目级布局不存在时回退全局默认（column_id=None）。
    """
    page = get_page(scope, column_id)
    if page and page.published_json:
        try:
            return loads_layout(page.published_json)
        except LayoutError:
            return None
    if scope == _B.SCOPE_ARTICLE and column_id is not None:
        default_page = get_page(_B.SCOPE_ARTICLE, None)
        if default_page and default_page.published_json:
            try:
                return loads_layout(default_page.published_json)
            except LayoutError:
                return None
    return None


def get_draft_layout(page):
    """编辑器入口：优先草稿，否则已发布，否则空布局。"""
    raw = page.draft_json or page.published_json
    if raw:
        return loads_layout(raw)
    return {'version': _B.SCHEMA_VERSION, 'root': []}


def list_pages_grouped():
    """页面管理列表：已构建页面 + 可初始化的栏目。"""
    from ..models.column import Column

    pages = BuilderPage.query.order_by(BuilderPage.scope, BuilderPage.id).all()
    by_scope = {s: [] for s in _B.SCOPES}
    for p in pages:
        by_scope[p.scope].append(p)

    # 未创建构建记录的栏目（page/list 类型），供「新建」入口使用
    existing = {
        (p.scope, p.column_id) for p in pages
    }
    available_columns = {'page': [], 'list': []}
    for col in Column.query.filter_by(is_deleted=False).order_by(
            Column.sort_order.desc(), Column.id.asc()).all():
        if col.type in ('page', 'list') and not col.is_parent:
            scopes = {'page': _B.SCOPE_PAGE, 'list': _B.SCOPE_LIST}
            sc = scopes[col.type]
            if (sc, col.id) not in existing:
                available_columns[sc].append(col)

    return by_scope, available_columns


# ============================================================
# 写入：草稿 / 发布 / 回滚
# ============================================================

def save_draft(page, layout, author_id=None, commit=True):
    """校验并保存草稿，返回 (page, error)。"""
    try:
        validate_layout(layout)
    except LayoutError as e:
        return None, str(e)
    page.draft_json = dumps_layout(layout)
    if page.status == _B.STATUS_PUBLISHED:
        # 保留 published 状态语义：published_json 仍是线上版本，
        # 有草稿时编辑器显示「未发布改动」
        pass
    elif page.status != _B.STATUS_DRAFT:
        page.status = _B.STATUS_DRAFT
    page.author_id = author_id
    if commit:
        db.session.commit()
    return page, None


def publish_page(page, layout=None, author_id=None, note='', commit=True):
    """发布布局：写 published_json + 修订快照 + 清整页缓存。"""
    if layout is None:
        layout = loads_layout(page.draft_json) if page.draft_json else None
    if layout is None:
        return None, '没有可发布的布局内容'
    try:
        validate_layout(layout)
    except LayoutError as e:
        return None, str(e)

    data = dumps_layout(layout)
    page.draft_json = data
    page.published_json = data
    page.status = _B.STATUS_PUBLISHED
    page.published_at = datetime.now()
    page.author_id = author_id

    revision = BuilderRevision(
        page_id=page.id, data_json=data,
        note=(note or '')[:255], author_id=author_id,
    )
    db.session.add(revision)
    if commit:
        db.session.commit()
    _clear_cache()
    return revision, None


def rollback_revision(page, revision_id, author_id=None, commit=True):
    """回滚到指定修订：该修订成为新的发布版本（并再记一条快照，保留审计链）。"""
    rev = BuilderRevision.query.filter_by(
        id=revision_id, page_id=page.id).first()
    if rev is None:
        return None, '修订版本不存在'
    layout = loads_layout(rev.data_json)
    try:
        validate_layout(layout)
    except LayoutError as e:
        return None, str(e)
    data = dumps_layout(layout)
    page.draft_json = data
    page.published_json = data
    page.status = _B.STATUS_PUBLISHED
    page.published_at = datetime.now()
    page.author_id = author_id
    new_rev = BuilderRevision(
        page_id=page.id, data_json=data,
        note=f'回滚至修订 #{rev.id}', author_id=author_id,
    )
    db.session.add(new_rev)
    if commit:
        db.session.commit()
    _clear_cache()
    return new_rev, None


def resolve_fixture_path(scope, theme=None):
    """解析某作用域的默认布局文件路径。

    优先当前启用主题自带的 themes/<theme>/builder/<scope>.json（与该主题
    手写模板等价）；主题未覆写时回退核心 fixture（等价 default 主题）。
    返回 None 表示作用域非法或文件缺失。
    """
    fname = _FIXTURE_FILES.get(scope)
    if not fname:
        return None
    theme = (theme or '').strip() or get_active_theme()
    if theme:
        theme_path = os.path.join(THEMES_DIR, theme, 'builder', fname)
        if os.path.isfile(theme_path):
            return theme_path
    core_path = os.path.join(FIXTURES_DIR, fname)
    return core_path if os.path.isfile(core_path) else None


def init_default_layout(scope, column_id=None, author_id=None, commit=True,
                        theme=None):
    """按当前启用主题的手写模板结构初始化草稿。返回 (page, error)。

    主题可在 themes/<theme>/builder/ 下提供自己的 fixture 覆写核心默认值。
    """
    path = resolve_fixture_path(scope, theme)
    if path is None:
        if scope not in _FIXTURE_FILES:
            return None, f'非法作用域：{scope}'
        return None, '默认布局文件缺失'
    with open(path, 'r', encoding='utf-8') as f:
        layout = json.load(f)
    try:
        validate_layout(layout)
    except LayoutError as e:
        return None, f'默认布局非法：{e}'
    page, _created = get_or_create_page(
        scope, column_id, commit=False)
    page.author_id = author_id
    page.draft_json = dumps_layout(layout)
    if not page.name:
        page.name = _default_name(scope, column_id)
    if commit:
        db.session.commit()
    return page, None


# ============================================================
# 辅助
# ============================================================

def pages_referencing_widget_types(widget_types):
    """扫描全部草稿/已发布布局，返回引用了给定组件类型的 BuilderPage 列表。

    用于插件卸载前的安全检查（插件组件会随卸载注销，引用会导致布局校验失败）。
    """
    types = set(widget_types or [])
    if not types:
        return []
    hits = []
    for page in BuilderPage.query.all():
        referenced = False
        for raw in (page.draft_json, page.published_json):
            if not raw or referenced:
                continue
            try:
                layout = loads_layout(raw)
            except LayoutError:
                continue
            for node in iter_layout_nodes(layout):
                if node.get('type') in types:
                    referenced = True
                    break
        if referenced:
            hits.append(page)
    return hits


def iter_layout_nodes(layout):
    """遍历布局全部节点（service 内部便捷封装，避免调用方依赖 schema 模块）。"""
    from .schema import iter_nodes
    return iter_nodes(layout.get('root') or [])


def _default_name(scope, column_id):
    labels = {
        _B.SCOPE_HOME: '网站首页',
        _B.SCOPE_PAGE: '单页',
        _B.SCOPE_LIST: '列表页',
        _B.SCOPE_ARTICLE: '文章详情页',
    }
    return labels.get(scope, scope)


def _clear_cache():
    """布局发布/回滚后清整页缓存（与主题切换同一模式）。"""
    try:
        from ..extensions import cache
        cache.clear()
    except Exception:
        pass
