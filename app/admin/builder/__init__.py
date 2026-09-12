"""v3.0.0 可视化页面构建器后台：页面管理、编辑器 API、画布预览。"""
from flask import (
    render_template, redirect, url_for, request, jsonify, abort, flash,
)
from flask_babel import gettext as _gettext
from flask_login import current_user

from ...constants import Builder as _B
from ...extensions import db
from ...models.builder import BuilderPage, BuilderRevision
from ...models.column import Column, ColumnField
from ...models.article import Article
from ...models.workflow import STATUS_PUBLISHED
from ...models.audit import (
    MODULE_BUILDER, OP_CREATE, OP_UPDATE, OP_DELETE,
    OP_PUBLISH, OP_ROLLBACK,
)
from ...utils.helpers import permission_required, audit_log
from ...builder import service as svc
from ...builder import registry, schema
from .. import admin_bp

SCOPE_LABELS = {
    _B.SCOPE_HOME: '网站首页',
    _B.SCOPE_PAGE: '单页',
    _B.SCOPE_LIST: '列表页',
    _B.SCOPE_ARTICLE: '文章详情页',
}


def _json_error(message, code=400):
    return jsonify({'ok': False, 'error': message}), code


def _page_or_404(pid):
    page = BuilderPage.query.get(pid)
    if page is None:
        abort(404)
    return page


# ============================================================
# 页面管理
# ============================================================

@admin_bp.route('/builder')
@permission_required('builder:manage')
def builder_index():
    by_scope, available = svc.list_pages_grouped()
    return render_template(
        'admin/builder/index.html',
        by_scope=by_scope, available=available,
        scope_labels=SCOPE_LABELS,
        active_menu='builder',
    )


@admin_bp.route('/builder/pages/create', methods=['POST'])
@permission_required('builder:manage')
def builder_page_create():
    scope = (request.form.get('scope') or '').strip()
    column_id = request.form.get('column_id') or None
    if scope not in _B.SCOPES:
        flash(_gettext('非法页面类型'), 'danger')
        return redirect(url_for('admin.builder_index'))
    if scope == _B.SCOPE_HOME:
        column_id = None
    elif column_id:
        try:
            column_id = int(column_id)
        except (TypeError, ValueError):
            abort(404)
        if Column.query.filter_by(id=column_id, is_deleted=False).first() is None:
            abort(404)
    elif scope == _B.SCOPE_ARTICLE:
        column_id = None  # 全局默认详情布局
    else:
        flash(_gettext('请选择栏目'), 'danger')
        return redirect(url_for('admin.builder_index'))

    existing = svc.get_page(scope, column_id)
    if existing is not None:
        return redirect(url_for('admin.builder_editor', pid=existing.id))

    page, _created = svc.get_or_create_page(
        scope, column_id,
        name=SCOPE_LABELS.get(scope, scope),
    )
    audit_log(OP_CREATE, MODULE_BUILDER, target_id=page.id,
              target_name=page.name, detail={'scope': scope,
                                              'column_id': column_id})
    return redirect(url_for('admin.builder_editor', pid=page.id))


@admin_bp.route('/builder/pages/<int:pid>/init-default', methods=['POST'])
@permission_required('builder:manage')
def builder_page_init_default(pid):
    page = _page_or_404(pid)
    new_page, err = svc.init_default_layout(
        page.scope, page.column_id,
        author_id=current_user.id if current_user.is_authenticated else None,
    )
    if err:
        flash(_gettext('初始化失败：%s') % err, 'danger')
    else:
        flash(_gettext('已载入默认布局（尚未发布，可继续编辑）'), 'success')
    return redirect(url_for('admin.builder_editor', pid=pid))


@admin_bp.route('/builder/pages/<int:pid>/delete', methods=['POST'])
@permission_required('builder:publish')
def builder_page_delete(pid):
    page = _page_or_404(pid)
    if page.scope == _B.SCOPE_HOME:
        flash(_gettext('首页构建记录不可删除，可清空布局后发布'), 'danger')
        return redirect(url_for('admin.builder_index'))
    name = page.name
    db.session.delete(page)
    db.session.commit()
    svc._clear_cache()
    audit_log(OP_DELETE, MODULE_BUILDER, target_id=pid, target_name=name)
    flash(_gettext('页面构建记录已删除，前台已回退到手写模板'), 'success')
    return redirect(url_for('admin.builder_index'))


# ============================================================
# 编辑器页面
# ============================================================

@admin_bp.route('/builder/editor/<int:pid>')
@permission_required('builder:manage')
def builder_editor(pid):
    page = _page_or_404(pid)
    return render_template(
        'admin/builder/editor.html',
        page=page, scope_labels=SCOPE_LABELS,
        can_publish=bool(getattr(current_user, 'is_super', False)
                         or (current_user.is_authenticated
                             and current_user.has_permission('builder:publish'))),
        active_menu='builder',
    )


# ============================================================
# 编辑器 API
# ============================================================

@admin_bp.route('/builder/api/widgets')
@permission_required('builder:manage')
def builder_api_widgets():
    scope = (request.args.get('scope') or '').strip() or None
    return jsonify({'ok': True, 'categories': registry.widget_catalog(scope)})


@admin_bp.route('/builder/api/columns')
@permission_required('builder:manage')
def builder_api_columns():
    """栏目选择器数据：list 类型用于文章列表绑定。"""
    ctype = request.args.get('type', 'list')
    if ctype not in ('list', 'page'):
        ctype = 'list'
    cols = Column.query.filter_by(
        type=ctype, is_enabled=True, is_deleted=False
    ).order_by(Column.sort_order.desc(), Column.id.asc()).all()
    return jsonify({'ok': True, 'columns': [
        {'id': c.id, 'name': c.name, 'slug': c.slug} for c in cols
    ]})


@admin_bp.route('/builder/api/pages/<int:pid>')
@permission_required('builder:manage')
def builder_api_page_detail(pid):
    page = _page_or_404(pid)
    layout = svc.get_draft_layout(page)
    return jsonify({
        'ok': True,
        'page': {
            'id': page.id, 'scope': page.scope,
            'column_id': page.column_id, 'name': page.name,
            'status': page.status,
            'has_published': bool(page.published_json),
            'has_draft': bool(page.draft_json),
            'published_at': page.published_at.strftime('%Y-%m-%d %H:%M:%S')
            if page.published_at else '',
            'preview_url': url_for('admin.builder_preview', pid=page.id),
            'front_url': _front_url(page),
        },
        'layout': layout,
    })


@admin_bp.route('/builder/api/pages/<int:pid>/draft', methods=['POST'])
@permission_required('builder:manage')
def builder_api_save_draft(pid):
    page = _page_or_404(pid)
    payload = request.get_json(silent=True) or {}
    layout = payload.get('layout')
    _page, err = svc.save_draft(
        page, layout,
        author_id=current_user.id if current_user.is_authenticated else None,
    )
    if err:
        return _json_error(err)
    return jsonify({'ok': True, 'saved_at': page.updated_at.strftime('%H:%M:%S')})


@admin_bp.route('/builder/api/pages/<int:pid>/publish', methods=['POST'])
@permission_required('builder:publish')
def builder_api_publish(pid):
    page = _page_or_404(pid)
    payload = request.get_json(silent=True) or {}
    note = (payload.get('note') or '')[:255]
    revision, err = svc.publish_page(
        page, payload.get('layout'),
        author_id=current_user.id if current_user.is_authenticated else None,
        note=note,
    )
    if err:
        return _json_error(err)
    audit_log(OP_PUBLISH, MODULE_BUILDER, target_id=page.id,
              target_name=page.name,
              detail={'revision_id': revision.id, 'note': note})
    return jsonify({'ok': True, 'revision_id': revision.id,
                    'published_at': page.published_at.strftime('%Y-%m-%d %H:%M:%S')})


@admin_bp.route('/builder/api/pages/<int:pid>/rollback', methods=['POST'])
@permission_required('builder:publish')
def builder_api_rollback(pid):
    page = _page_or_404(pid)
    payload = request.get_json(silent=True) or {}
    try:
        revision_id = int(payload.get('revision_id'))
    except (TypeError, ValueError):
        return _json_error('缺少修订版本号')
    new_rev, err = svc.rollback_revision(
        page, revision_id,
        author_id=current_user.id if current_user.is_authenticated else None,
    )
    if err:
        return _json_error(err)
    audit_log(OP_ROLLBACK, MODULE_BUILDER, target_id=page.id,
              target_name=page.name, detail={'to_revision': revision_id})
    return jsonify({'ok': True, 'revision_id': new_rev.id,
                    'layout': svc.get_draft_layout(page)})


@admin_bp.route('/builder/api/pages/<int:pid>/revisions')
@permission_required('builder:manage')
def builder_api_revisions(pid):
    page = _page_or_404(pid)
    revs = page.revisions.limit(50).all()
    return jsonify({'ok': True, 'revisions': [
        {'id': r.id, 'note': r.note,
         'created_at': r.created_at.strftime('%Y-%m-%d %H:%M:%S')}
        for r in revs
    ]})


# ============================================================
# 画布预览（渲染草稿，仅后台登录可见）
# ============================================================

@admin_bp.route('/builder/preview/<int:pid>')
@permission_required('builder:manage')
def builder_preview(pid):
    page = _page_or_404(pid)
    layout = svc.get_draft_layout(page)
    page_ctx = _build_preview_ctx(page)
    page_ctx['preview'] = True
    # 预览不读草稿缓存，直接用构建器渲染
    from ...builder.renderer import render_builder_page
    return render_builder_page(layout, page_ctx)


def _front_url(page):
    """页面对应的前台线上地址（用于「查看前台」按钮）。"""
    try:
        if page.scope == _B.SCOPE_HOME:
            return url_for('frontend.index')
        col = Column.query.get(page.column_id) if page.column_id else None
        if col is not None and page.scope in (_B.SCOPE_PAGE, _B.SCOPE_LIST):
            return url_for('frontend.column_detail', slug=col.slug)
        if page.scope == _B.SCOPE_ARTICLE and col is not None:
            return url_for('frontend.column_detail', slug=col.slug)
    except Exception:
        return '/'
    return '/'


def _build_preview_ctx(page):
    """为预览构造与前台视图等价的上下文（示例数据取最新内容）。"""
    from ...frontend.views import _build_nav, _seo
    ctx = {
        'scope': page.scope,
        'nav': _build_nav(),
        'seo': _seo(),
    }
    col = None
    if page.column_id:
        col = Column.query.filter_by(
            id=page.column_id, is_deleted=False).first()
    if col is not None:
        ctx['column'] = col
        ctx['seo'] = _seo(column=col)
        fields = col.fields.filter_by(
            is_deleted=False, is_frontend_visible=True
        ).order_by(ColumnField.sort_order.desc()).all()
        ctx['fields'] = fields
        if col.type == 'list':
            per_page = col.page_size or 10
            pagination = Article.query.filter_by(
                column_id=col.id, is_deleted=False, status=STATUS_PUBLISHED
            ).order_by(
                Article.sort_order.desc(), Article.published_at.desc()
            ).paginate(page=1, per_page=per_page, error_out=False)
            ctx['articles'] = pagination.items
            ctx['pagination'] = pagination

    if page.scope == _B.SCOPE_ARTICLE:
        article = None
        if col is not None:
            article = Article.query.filter_by(
                column_id=col.id, is_deleted=False, status=STATUS_PUBLISHED
            ).order_by(Article.published_at.desc()).first()
        if article is None:
            article = Article.query.filter_by(
                is_deleted=False, status=STATUS_PUBLISHED
            ).order_by(Article.published_at.desc()).first()
        if article is not None:
            art_col = col or Column.query.get(article.column_id)
            ctx['article'] = article
            ctx['column'] = art_col
            ctx['seo'] = _seo(article=article)
            prev_article = Article.query.filter(
                Article.column_id == art_col.id,
                Article.is_deleted == False,  # noqa: E712
                Article.status == STATUS_PUBLISHED,
                Article.id < article.id
            ).order_by(Article.id.desc()).first()
            next_article = Article.query.filter(
                Article.column_id == art_col.id,
                Article.is_deleted == False,  # noqa: E712
                Article.status == STATUS_PUBLISHED,
                Article.id > article.id
            ).order_by(Article.id.asc()).first()
            ctx['prev_article'] = prev_article
            ctx['next_article'] = next_article
    return ctx
