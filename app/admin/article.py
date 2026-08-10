"""文章管理（列表栏目下的内容）。"""
from datetime import datetime

from flask import (
    render_template, redirect, url_for, request,
    flash, abort, jsonify
)
from flask_login import current_user

from ..extensions import db
from ..models.column import Column, ColumnField
from ..models.article import Article, ArticleFieldValue
from ..utils.helpers import admin_required
from ..utils.uploads import save_upload_file
from . import admin_bp


@admin_bp.route('/columns/<int:cid>/articles')
@admin_required
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
    if status == 'enabled':
        query = query.filter_by(is_enabled=True)
    elif status == 'disabled':
        query = query.filter_by(is_enabled=False)

    pagination = query.order_by(
        Article.sort_order.desc(), Article.created_at.desc()
    ).paginate(page=page, per_page=15, error_out=False)

    return render_template(
        'admin/article/index.html',
        column=col, articles=pagination.items, pagination=pagination,
        keyword=keyword, status=status
    )


@admin_bp.route('/columns/<int:cid>/articles/create', methods=['GET', 'POST'])
@admin_required
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
        column=col, article=None, fields=fields
    )


@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/edit', methods=['GET', 'POST'])
@admin_required
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

    return render_template(
        'admin/article/form.html',
        column=col, article=article, fields=fields
    )


def _save_article(article, column, fields):
    title = (request.form.get('title') or '').strip()
    if not title:
        flash('文章标题必填', 'danger')
        return None

    is_new = article is None
    if is_new:
        article = Article(column_id=column.id)
    else:
        # 清理旧的自定义字段值
        ArticleFieldValue.query.filter_by(article_id=article.id).delete()

    article.title = title
    article.summary = (request.form.get('summary') or '').strip()
    article.content = request.form.get('content') or ''
    article.author = (request.form.get('author') or '').strip()
    article.source = (request.form.get('source') or '').strip()
    article.sort_order = int(request.form.get('sort_order') or 0)
    article.is_enabled = (request.form.get('is_enabled') == 'on')

    article.seo_title = (request.form.get('seo_title') or '').strip()
    article.seo_keywords = (request.form.get('seo_keywords') or '').strip()
    article.seo_description = (request.form.get('seo_description') or '').strip()

    published_str = request.form.get('published_at') or ''
    if published_str:
        try:
            article.published_at = datetime.strptime(published_str, '%Y-%m-%d %H:%M')
        except ValueError:
            article.published_at = datetime.now()
    else:
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

    if is_new:
        db.session.add(article)
        db.session.flush()

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

    db.session.commit()
    flash('文章保存成功', 'success')
    return article


@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/delete', methods=['POST'])
@admin_required
def article_delete(cid, aid):
    article = Article.query.get_or_404(aid)
    article.is_deleted = True
    db.session.commit()
    flash('文章已删除', 'success')
    return redirect(url_for('admin.article_index', cid=cid))


@admin_bp.route('/columns/<int:cid>/articles/<int:aid>/toggle', methods=['POST'])
@admin_required
def article_toggle(cid, aid):
    article = Article.query.get_or_404(aid)
    article.is_enabled = not article.is_enabled
    db.session.commit()
    return redirect(url_for('admin.article_index', cid=cid))


@admin_bp.route('/columns/<int:cid>/articles/batch', methods=['POST'])
@admin_required
def article_batch(cid):
    action = request.form.get('action')
    ids = [int(i) for i in request.form.getlist('ids[]') if i.isdigit()]
    if not ids:
        flash('未选择文章', 'warning')
        return redirect(url_for('admin.article_index', cid=cid))

    articles = Article.query.filter(Article.id.in_(ids), Article.column_id == cid).all()
    if action == 'enable':
        for a in articles: a.is_enabled = True
    elif action == 'disable':
        for a in articles: a.is_enabled = False
    elif action == 'delete':
        for a in articles: a.is_deleted = True
    db.session.commit()
    flash('批量操作完成', 'success')
    return redirect(url_for('admin.article_index', cid=cid))
