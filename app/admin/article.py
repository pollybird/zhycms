"""模块3：内容发布工作流优化。
文章管理（列表栏目下的内容）升级点：
  - 四状态管理：草稿(draft)、待审核(review)、已发布(published)、已归档(archived)
  - 审核流程：提交待审核 → 审核员通过/驳回（带原因）
  - 版本快照：每次修改自动保存 ArticleVersion，支持列表查看 + 一键回滚
  - 批量操作：批量移动栏目、批量发布、批量归档、批量删除
  - RBAC：栏目专属权限 / 全局权限双轨校验
  - 审计日志：每次关键动作写入 AuditLog
"""
from datetime import datetime

from flask import (
    render_template, redirect, url_for, request,
    flash, abort, jsonify, current_app
)
from flask_login import current_user

from ..extensions import db
from ..models.column import Column, ColumnField
from ..models.article import Article, ArticleFieldValue
from ..models.workflow import (
    STATUS_DRAFT, STATUS_REVIEW, STATUS_PUBLISHED, STATUS_ARCHIVED,
    STATUS_CHOICES, ArticleVersion,
)
from ..utils.helpers import (
    permission_required, audit_log, clear_content_cache,
)
from ..utils.uploads import save_upload_file
from ..utils.word_import import convert_docx_to_html
from ..models.audit import (
    OP_CREATE, OP_UPDATE, OP_DELETE, OP_PUBLISH, OP_ARCHIVE,
    OP_REVIEW_PASS, OP_REVIEW_REJECT, OP_BATCH, OP_ROLLBACK,
    MODULE_ARTICLE,
)
from . import admin_bp


# ============================================================
# 工具
# ============================================================

def _col_or_404(cid):
    col = Column.query.get_or_404(cid)
    if col.type != 'list':
        flash('该栏目不是列表栏目，无法管理文章', 'warning')
        abort(400) if False else None
    return col


def _build_tree_with_depth(columns, parent_id=None, depth=0):
    result = []
    for col in columns:
        if col.parent_id == parent_id:
            col._depth = depth
            result.append(col)
            result.extend(_build_tree_with_depth(columns, col.id, depth + 1))
    return result


# ============================================================
# 列表（支持 4 状态过滤 + 关键词）
# ============================================================

@admin_bp.route('/columns/<int:cid>/articles')
@permission_required('content:edit', column_id_arg='cid')
def article_index(cid):
    col = Column.query.get_or_404(cid)
    if col.type != 'list':
        flash('该栏目不是列表栏目，无法管理文章', 'warning')
        return redirect(url_for('admin.column_index'))

    page = max(int(request.args.get('page', 1)), 1)
    keyword = (request.args.get('keyword') or '').strip()
    status = request.args.get('status', '')

    query = Article.query.filter_by(column_id=cid, is_deleted=False)
    if keyword:
        query = query.filter(Article.title.like(f'%{keyword}%'))
    # 工作流状态过滤优先，兼容旧的 enabled/disabled 参数
    if status in (STATUS_DRAFT, STATUS_REVIEW, STATUS_PUBLISHED, STATUS_ARCHIVED):
        query = query.filter_by(status=status)
    elif status == 'enabled':
        query = query.filter_by(is_enabled=True)
    elif status == 'disabled':
        query = query.filter_by(is_enabled=False)

    pagination = query.order_by(
        Article.sort_order.desc(), Article.created_at.desc()
    ).paginate(page=page, per_page=15, error_out=False)

    # 批量移动目标栏目：当前用户可见的列表栏目（树形带缩进）
    cols = Column.query.filter_by(type='list', is_deleted=False).all()
    if not getattr(current_user, 'is_super', False):
        allowed = current_user.get_allowed_column_ids()
        if allowed is not None:
            cols = [c for c in cols if c.id in allowed]
    list_columns = _build_tree_with_depth(cols)

    return render_template(
        'admin/article/index.html',
        column=col, articles=pagination.items, pagination=pagination,
        keyword=keyword, status=status, status_choices=STATUS_CHOICES,
        list_columns=list_columns,
    )


# ============================================================
# 创建 / 编辑（加权限 + 版本快照 + 工作流字段）
# ============================================================

@admin_bp.route('/columns/<int:cid>/articles/create', methods=['GET', 'POST'])
@permission_required('content:create', column_id_arg='cid')
def article_create(cid):
    col = Column.query.get_or_404(cid)
    if col.type != 'list':
        flash('该栏目不是列表栏目', 'warning')
        return redirect(url_for('admin.column_index'))
    if col.is_parent:
        flash('父栏目不能添加文章，请先选择或创建子栏目', 'warning')
        return redirect(url_for('admin.column_index'))

    fields = col.fields.filter_by(is_deleted=False).order_by(ColumnField.sort_order.desc()).all()

    if request.method == 'POST':
        article = _save_article(None, col, fields)
        if article is None:
            return redirect(url_for('admin.article_create', cid=cid))
        return redirect(url_for('admin.article_index', cid=cid))

    return render_template(
        'admin/article/form.html',
        column=col, article=None, fields=fields,
        status_choices=STATUS_CHOICES, default_status=STATUS_DRAFT,
    )


@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/edit', methods=['GET', 'POST'])
@permission_required('content:edit', column_id_arg='cid')
def article_edit(cid, aid):
    col = Column.query.get_or_404(cid)
    article = Article.query.get_or_404(aid)
    if article.column_id != col.id or article.is_deleted:
        abort(404)

    fields = col.fields.filter_by(is_deleted=False).order_by(ColumnField.sort_order.desc()).all()

    if request.method == 'POST':
        updated = _save_article(article, col, fields)
        if updated is None:
            return redirect(url_for('admin.article_edit', cid=cid, aid=aid))
        return redirect(url_for('admin.article_index', cid=cid))

    # 读取历史版本列表
    versions = ArticleVersion.query.filter_by(article_id=aid).order_by(
        ArticleVersion.version_no.desc()
    ).limit(50).all()

    return render_template(
        'admin/article/form.html',
        column=col, article=article, fields=fields,
        status_choices=STATUS_CHOICES, versions=versions,
        default_status=article.status,
    )


def _save_article(article, column, fields):
    """创建或更新文章，自动同步 enabled ↔ status，创建版本快照。"""
    title = (request.form.get('title') or '').strip()
    if not title:
        flash('文章标题必填', 'danger')
        return None

    is_new = article is None
    if is_new:
        article = Article(column_id=column.id)
    else:
        # 清理旧的自定义字段值，重建
        ArticleFieldValue.query.filter_by(article_id=article.id).delete()

    article.title = title
    article.summary = (request.form.get('summary') or '').strip()
    article.content = request.form.get('content') or ''
    article.author = (request.form.get('author') or '').strip()
    article.source = (request.form.get('source') or '').strip()
    article.sort_order = int(request.form.get('sort_order') or 0)

    # 工作流状态（优先新的 status，兼容旧的 is_enabled）
    status = request.form.get('status') or ''
    if status in (STATUS_DRAFT, STATUS_REVIEW, STATUS_PUBLISHED, STATUS_ARCHIVED):
        # 无发布权限者不允许直接把内容置为「已发布」，自动改为待审核走流程
        if status == STATUS_PUBLISHED and not (
            current_user.is_super or current_user.has_permission('content:publish')):
            status = STATUS_REVIEW
            flash('您无「发布」权限，状态已自动改为「待审核」', 'warning')
        article.status = status
    elif not is_new:
        # 编辑时保持原状态
        pass
    else:
        # 新建默认草稿
        article.status = STATUS_DRAFT
    # 同步 is_enabled 字段
    article.sync_enabled_from_status()

    # SEO
    article.seo_title = (request.form.get('seo_title') or '').strip()
    article.seo_keywords = (request.form.get('seo_keywords') or '').strip()
    article.seo_description = (request.form.get('seo_description') or '').strip()

    # 发布时间
    published_str = request.form.get('published_at') or ''
    if published_str:
        try:
            article.published_at = datetime.strptime(published_str, '%Y-%m-%d %H:%M')
        except ValueError:
            article.published_at = datetime.now()
    elif is_new:
        article.published_at = datetime.now()

    # 封面图
    cover_file = request.files.get('cover')
    if cover_file and cover_file.filename:
        rel, url, err = save_upload_file(cover_file, sub_dir='article',
                                         allowed_exts=['jpg', 'jpeg', 'png', 'gif', 'webp'],
                                         max_size=10 * 1024 * 1024)
        if err:
            flash(f'封面图上传失败：{err}', 'danger')
            return None
        article.cover = url
    elif request.form.get('cover_remove') == 'on':
        article.cover = None

    # created_by / updated_by
    now = datetime.now()
    uid = getattr(current_user, 'id', None)
    if is_new:
        article.created_by = uid
        db.session.add(article)
        db.session.flush()
    else:
        # 若编辑把待审核文章改回草稿，清除驳回原因
        if article.status == STATUS_DRAFT:
            article.reject_reason = None
    article.updated_by = uid
    article.updated_at = now

    # 自定义字段值
    for f in fields:
        value = None
        if f.field_type in ('image', 'file'):
            file_obj = request.files.get(f'field_{f.id}')
            if file_obj and file_obj.filename:
                allowed = None
                maxsize = None
                if f.field_type == 'file':
                    allowed = f.allowed_exts.split(',') if f.allowed_exts else None
                    maxsize = f.max_size
                else:
                    allowed = ['jpg', 'jpeg', 'png', 'gif', 'webp']
                rel, url, err = save_upload_file(file_obj, sub_dir='article',
                                                 allowed_exts=allowed, max_size=maxsize)
                if err:
                    flash(f'字段 {f.label} 上传失败：{err}', 'danger')
                    return None
                value = url
            elif request.form.get(f'field_{f.id}_remove') == 'on':
                value = ''
            else:
                value = (request.form.get(f'field_{f.id}_existing') or '')
        else:
            value = request.form.get(f'field_{f.id}') or ''

        if f.is_required and not value:
            flash(f'字段 {f.label} 为必填', 'danger')
            return None

        if value is not None:
            v = ArticleFieldValue(article_id=article.id, field_id=f.id, value=value)
            db.session.add(v)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('文章保存失败（数据库错误）', 'danger')
        current_app.logger.exception('article save DB error')
        return None

    # 保存版本快照（必须在 commit 后 article.id 已存在且字段值已写库）
    note = '新建' if is_new else '编辑修改'
    try:
        ArticleVersion.snapshot(article, status_snapshot=article.status,
                                note=note, created_by=uid)
        db.session.commit()
    except Exception:
        current_app.logger.exception('article snapshot failed')
        # 快照失败不影响主事务
        try:
            db.session.rollback()
        except Exception:
            pass

    # 清缓存 + 审计日志
    clear_content_cache(column_id=column.id, article_id=article.id)
    if is_new:
        flash('文章创建成功', 'success')
        audit_log(OP_CREATE, MODULE_ARTICLE, article.id, article.title,
                  {'column_id': column.id, 'status': article.status})
    else:
        flash('文章保存成功', 'success')
        audit_log(OP_UPDATE, MODULE_ARTICLE, article.id, article.title,
                  {'column_id': column.id, 'status': article.status})
    return article


# ============================================================
# 工作流动作：提交审核 / 审核通过 / 审核驳回 / 发布 / 归档
# ============================================================

@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/submit-review', methods=['POST'])
@permission_required('content:submit_review', column_id_arg='cid')
def article_submit_review(cid, aid):
    col = Column.query.get_or_404(cid)
    article = Article.query.get_or_404(aid)
    if article.column_id != col.id or article.is_deleted:
        abort(404)
    if article.status not in (STATUS_DRAFT, STATUS_ARCHIVED):
        flash('只有草稿或已归档的内容可以提交审核', 'warning')
        return redirect(url_for('admin.article_index', cid=cid))
    article.status = STATUS_REVIEW
    article.reject_reason = None
    article.sync_enabled_from_status()
    article.updated_by = getattr(current_user, 'id', None)
    try:
        db.session.commit()
        clear_content_cache(column_id=cid, article_id=aid)
        flash('已提交待审核，请等待审核员处理', 'success')
        audit_log(OP_UPDATE, MODULE_ARTICLE, article.id, article.title,
                  {'action': 'submit_review', 'from_status': 'draft/archived'})
        ArticleVersion.snapshot(article, article.status, note='提交审核',
                                created_by=getattr(current_user, 'id', None))
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('提交失败', 'danger')
    return redirect(url_for('admin.article_index', cid=cid))


@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/review-pass', methods=['POST'])
@permission_required('content:review', column_id_arg='cid')
def article_review_pass(cid, aid):
    col = Column.query.get_or_404(cid)
    article = Article.query.get_or_404(aid)
    if article.column_id != col.id or article.is_deleted:
        abort(404)
    if not current_user.column_flag('can_review', cid):
        flash('您在该栏目没有「审核」权限', 'warning')
        return redirect(url_for('admin.article_index', cid=cid))
    if article.status != STATUS_REVIEW:
        flash('只有「待审核」状态才能审核通过', 'warning')
        return redirect(url_for('admin.article_index', cid=cid))
    article.status = STATUS_PUBLISHED
    article.reject_reason = None
    article.reviewed_by = getattr(current_user, 'id', None)
    article.reviewed_at = datetime.now()
    article.sync_enabled_from_status()
    article.updated_by = getattr(current_user, 'id', None)
    try:
        db.session.commit()
        clear_content_cache(column_id=cid, article_id=aid)
        flash('审核通过，内容已正式发布', 'success')
        audit_log(OP_REVIEW_PASS, MODULE_ARTICLE, article.id, article.title,
                  {'column_id': cid})
        ArticleVersion.snapshot(article, article.status, note='审核通过',
                                created_by=getattr(current_user, 'id', None))
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('审核失败', 'danger')
    return redirect(url_for('admin.article_index', cid=cid))


@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/review-reject', methods=['POST'])
@permission_required('content:review', column_id_arg='cid')
def article_review_reject(cid, aid):
    col = Column.query.get_or_404(cid)
    article = Article.query.get_or_404(aid)
    if article.column_id != col.id or article.is_deleted:
        abort(404)
    if not current_user.column_flag('can_review', cid):
        flash('您在该栏目没有「审核」权限', 'warning')
        return redirect(url_for('admin.article_index', cid=cid))
    if article.status != STATUS_REVIEW:
        flash('只有「待审核」状态才能驳回', 'warning')
        return redirect(url_for('admin.article_index', cid=cid))
    reason = (request.form.get('reject_reason') or '').strip()[:500]
    if not reason:
        flash('驳回原因必填', 'danger')
        return redirect(url_for('admin.article_edit', cid=cid, aid=aid))
    article.status = STATUS_DRAFT
    article.reject_reason = reason
    article.reviewed_by = getattr(current_user, 'id', None)
    article.reviewed_at = datetime.now()
    article.sync_enabled_from_status()
    article.updated_by = getattr(current_user, 'id', None)
    try:
        db.session.commit()
        clear_content_cache(column_id=cid, article_id=aid)
        flash(f'已驳回，原因已写入供编辑修改（{reason[:30]}…）', 'success')
        audit_log(OP_REVIEW_REJECT, MODULE_ARTICLE, article.id, article.title,
                  {'column_id': cid, 'reason': reason})
        ArticleVersion.snapshot(article, article.status,
                                note=f'审核驳回：{reason[:50]}',
                                created_by=getattr(current_user, 'id', None))
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('驳回失败', 'danger')
    return redirect(url_for('admin.article_index', cid=cid))


@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/publish', methods=['POST'])
@permission_required('content:publish', column_id_arg='cid')
def article_publish(cid, aid):
    col = Column.query.get_or_404(cid)
    article = Article.query.get_or_404(aid)
    if article.column_id != col.id or article.is_deleted:
        abort(404)
    if not current_user.column_flag('can_publish', cid):
        flash('您在该栏目没有「发布」权限', 'warning')
        return redirect(url_for('admin.article_index', cid=cid))
    article.status = STATUS_PUBLISHED
    article.reject_reason = None
    article.sync_enabled_from_status()
    article.updated_by = getattr(current_user, 'id', None)
    try:
        db.session.commit()
        clear_content_cache(column_id=cid, article_id=aid)
        flash('已直接发布', 'success')
        audit_log(OP_PUBLISH, MODULE_ARTICLE, article.id, article.title,
                  {'column_id': cid, 'from': 'direct_publish'})
        ArticleVersion.snapshot(article, article.status, note='直接发布',
                                created_by=getattr(current_user, 'id', None))
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('发布失败', 'danger')
    return redirect(url_for('admin.article_index', cid=cid))


@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/archive', methods=['POST'])
@permission_required('content:archive', column_id_arg='cid')
def article_archive(cid, aid):
    col = Column.query.get_or_404(cid)
    article = Article.query.get_or_404(aid)
    if article.column_id != col.id or article.is_deleted:
        abort(404)
    article.status = STATUS_ARCHIVED
    article.sync_enabled_from_status()
    article.updated_by = getattr(current_user, 'id', None)
    try:
        db.session.commit()
        clear_content_cache(column_id=cid, article_id=aid)
        flash('已归档（前台不再展示）', 'success')
        audit_log(OP_ARCHIVE, MODULE_ARTICLE, article.id, article.title,
                  {'column_id': cid})
        ArticleVersion.snapshot(article, article.status, note='归档',
                                created_by=getattr(current_user, 'id', None))
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('归档失败', 'danger')
    return redirect(url_for('admin.article_index', cid=cid))


# ============================================================
# 版本列表 + 回滚
# ============================================================

@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/versions')
@permission_required('content:rollback', column_id_arg='cid')
def article_versions(cid, aid):
    col = Column.query.get_or_404(cid)
    article = Article.query.get_or_404(aid)
    if article.column_id != col.id or article.is_deleted:
        abort(404)
    page = max(int(request.args.get('page', 1)), 1)
    versions = ArticleVersion.query.filter_by(article_id=aid).order_by(
        ArticleVersion.version_no.desc()
    ).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/article/versions.html',
                           column=col, article=article, versions=versions)


@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/versions/<int:vid>/rollback',
                methods=['POST'])
@permission_required('content:rollback', column_id_arg='cid')
def article_rollback(cid, aid, vid):
    col = Column.query.get_or_404(cid)
    article = Article.query.get_or_404(aid)
    v = ArticleVersion.query.get_or_404(vid)
    if article.column_id != col.id or article.is_deleted or v.article_id != article.id:
        abort(404)
    try:
        v.restore_to(article)
        article.updated_by = getattr(current_user, 'id', None)
        article.sync_enabled_from_status()
        # 回滚后自动切换为草稿，避免误直接覆盖线上
        if article.status == STATUS_PUBLISHED:
            article.status = STATUS_DRAFT
            article.sync_enabled_from_status()
        db.session.commit()
        clear_content_cache(column_id=cid, article_id=aid)
        # 写入一个版本快照记录「回滚来源」
        ArticleVersion.snapshot(article, article.status,
                                note=f'回滚到版本 v{v.version_no}',
                                created_by=getattr(current_user, 'id', None))
        db.session.commit()
        flash(f'已回滚到版本 v{v.version_no}，当前状态为草稿，请检查后重新提交', 'success')
        audit_log(OP_ROLLBACK, MODULE_ARTICLE, article.id, article.title,
                  {'to_version_no': v.version_no, 'title_snapshot': v.title})
    except Exception:
        db.session.rollback()
        current_app.logger.exception('rollback failed')
        flash('回滚失败，请查看日志', 'danger')
    return redirect(url_for('admin.article_edit', cid=cid, aid=aid))


# ============================================================
# 删除 / 开关 / 批量（新：批量移动、批量发布、批量归档、批量删除）
# ============================================================

@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/delete', methods=['POST'])
@permission_required('content:delete', column_id_arg='cid')
def article_delete(cid, aid):
    article = Article.query.get_or_404(aid)
    article.is_deleted = True
    article.updated_by = getattr(current_user, 'id', None)
    db.session.commit()
    clear_content_cache(column_id=cid, article_id=aid)
    flash('文章已删除', 'success')
    audit_log(OP_DELETE, MODULE_ARTICLE, article.id, article.title, {'column_id': cid})
    return redirect(url_for('admin.article_index', cid=cid))


@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/toggle', methods=['POST'])
@permission_required('content:publish', column_id_arg='cid')
def article_toggle(cid, aid):
    article = Article.query.get_or_404(aid)
    article.is_enabled = not article.is_enabled
    # 同步回 status：启用即视为已发布
    if article.is_enabled:
        article.status = STATUS_PUBLISHED
    else:
        article.status = STATUS_DRAFT
    article.updated_by = getattr(current_user, 'id', None)
    db.session.commit()
    clear_content_cache(column_id=cid, article_id=aid)
    audit_log(OP_UPDATE, MODULE_ARTICLE, article.id, article.title,
              {'action': 'toggle', 'is_enabled': article.is_enabled})
    return redirect(url_for('admin.article_index', cid=cid))


@admin_bp.route('/columns/<int:cid>/articles/batch', methods=['POST'])
@permission_required('content:batch', column_id_arg='cid')
def article_batch(cid):
    action = request.form.get('action')
    ids = [int(i) for i in request.form.getlist('ids[]') if i.isdigit()]
    if not ids:
        flash('未选择文章', 'warning')
        return redirect(url_for('admin.article_index', cid=cid))

    articles = Article.query.filter(Article.id.in_(ids), Article.column_id == cid).all()
    count = len(articles)

    # 栏目权限：确保操作者拥有该 cid 栏目权限（permission_required 已做）
    uid = getattr(current_user, 'id', None)
    # 发布类批量动作受栏目级「可发布」标志约束
    if action in ('publish', 'enable') and not current_user.column_flag('can_publish', cid):
        flash('您在该栏目没有「发布」权限', 'warning')
        return redirect(url_for('admin.article_index', cid=cid))

    if action == 'enable':
        for a in articles:
            a.is_enabled = True
            a.status = STATUS_PUBLISHED
            a.sync_enabled_from_status()
        msg = f'已发布 {count} 篇文章'
        audit_op = OP_PUBLISH
    elif action == 'disable':
        for a in articles:
            a.is_enabled = False
            a.status = STATUS_DRAFT
            a.sync_enabled_from_status()
        msg = f'已撤回 {count} 篇文章'
        audit_op = OP_UPDATE
    elif action == 'delete':
        for a in articles:
            a.is_deleted = True
            a.updated_by = uid
        msg = f'已删除 {count} 篇文章'
        audit_op = OP_DELETE
    elif action == 'publish':
        for a in articles:
            a.status = STATUS_PUBLISHED
            a.reject_reason = None
            a.sync_enabled_from_status()
            a.updated_by = uid
        msg = f'已批量发布 {count} 篇文章'
        audit_op = OP_PUBLISH
    elif action == 'archive':
        for a in articles:
            a.status = STATUS_ARCHIVED
            a.sync_enabled_from_status()
            a.updated_by = uid
        msg = f'已批量归档 {count} 篇文章'
        audit_op = OP_ARCHIVE
    elif action == 'submit_review':
        for a in articles:
            if a.status in (STATUS_DRAFT, STATUS_ARCHIVED):
                a.status = STATUS_REVIEW
                a.reject_reason = None
                a.sync_enabled_from_status()
                a.updated_by = uid
        msg = f'已批量提交审核（仅草稿/归档状态有效）：{count} 篇'
        audit_op = OP_UPDATE
    elif action == 'move':
        target_cid = request.form.get('target_column_id')
        try:
            target_cid = int(target_cid)
        except (TypeError, ValueError):
            flash('目标栏目无效', 'danger')
            return redirect(url_for('admin.article_index', cid=cid))
        # 目标栏目必须是 list 类型且操作者有权限
        target_col = Column.query.filter_by(id=target_cid, is_deleted=False).first()
        if target_col is None or target_col.type != 'list':
            flash('目标栏目不存在或不是列表栏目', 'danger')
            return redirect(url_for('admin.article_index', cid=cid))
        # RBAC 目标栏目权限检查
        if not (getattr(current_user, 'is_super', False) or
                current_user.can_access_column(target_cid)):
            flash('您对目标栏目没有操作权限', 'danger')
            return redirect(url_for('admin.article_index', cid=cid))
        for a in articles:
            a.column_id = target_cid
            a.updated_by = uid
        msg = f'已移动 {count} 篇到栏目「{target_col.name}」'
        audit_op = OP_BATCH
    else:
        flash(f'未知动作 {action}', 'warning')
        return redirect(url_for('admin.article_index', cid=cid))

    db.session.commit()
    clear_content_cache(column_id=cid)
    flash(msg, 'success')
    audit_log(audit_op if audit_op else OP_BATCH, MODULE_ARTICLE,
              None, None,
              {'action': action, 'count': count, 'ids': ids, 'from_column_id': cid,
               'target_column_id': (request.form.get('target_column_id')
                                    if action == 'move' else None)})
    return redirect(url_for('admin.article_index', cid=cid))


# ============================================================
# 其它：获取所有列表栏目（用于批量移动的目标选择下拉）
# ============================================================

@admin_bp.route('/api/list-columns')
@permission_required('column:manage')
def api_list_columns():
    """给批量移动、用户权限分配等场景返回可选列表栏目（含层级）。"""
    cols = Column.query.filter_by(type='list', is_deleted=False).all()
    # 过滤当前用户可见的栏目
    u = current_user
    if not getattr(u, 'is_super', False):
        allowed = u.get_allowed_column_ids()
        if allowed is not None:
            cols = [c for c in cols if c.id in allowed]
    tree = _build_tree_with_depth(cols)
    return jsonify({'columns': [
        {'id': c.id, 'name': ('— ' * c._depth) + c.name} for c in tree
    ]})


# ============================================================
# Word 导入（保留，加权限）
# ============================================================

@admin_bp.route('/columns/<int:cid>/articles/import-word', methods=['POST'])
@permission_required('content:create', column_id_arg='cid')
def article_import_word(cid):
    Column.query.get_or_404(cid)
    file_storage = request.files.get('docx')
    if not file_storage or not file_storage.filename:
        return jsonify({'error': '未选择文件'}), 400
    name = file_storage.filename
    if '.' not in name or name.rsplit('.', 1)[1].lower() != 'docx':
        return jsonify({'error': '仅支持 .docx 格式'}), 400
    try:
        html, messages = convert_docx_to_html(file_storage)
    except Exception as e:
        current_app.logger.exception('Word 导入失败')
        return jsonify({'error': f'解析文档失败：{e}'}), 500
    return jsonify({'html': html, 'messages': messages})
