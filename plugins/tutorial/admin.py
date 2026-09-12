"""教程插件：后台管理。

路由挂核心 admin_bp（endpoint 归入 admin.*）：
  /tutorials                    教程列表
  /tutorials/create             新建教程
  /tutorials/<id>/edit          编辑教程
  /tutorials/<id>/delete        删除教程
  /tutorials/categories         分类列表
  /tutorials/categories/create  新建分类
  /tutorials/categories/<id>/edit    编辑分类
  /tutorials/categories/<id>/delete  删除分类

未启用插件时所有路由 404。
"""
from functools import wraps

from flask import render_template, redirect, url_for, request, flash, abort
from flask_babel import gettext as _gettext

from app.extensions import db
from app.admin import admin_bp
from app.models.audit import OP_CREATE, OP_UPDATE, OP_DELETE
from app.utils.helpers import permission_required, audit_log
from app.utils.uploads import save_upload_file
from app.constants import Upload as _Upload
from app.plugin_system import plugin_enabled

from .models import TutorialCategory, Tutorial

MODULE_TUTORIAL = 'tutorial'
MODULE_TUTORIAL_CATEGORY = 'tutorial_category'

DIFFICULTY_CHOICES = [
    ('beginner', '入门'),
    ('intermediate', '进阶'),
    ('advanced', '高级'),
]


def _gate(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('tutorial'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


# ============ 教程管理 ============

@admin_bp.route('/tutorials')
@_gate
@permission_required('tutorial:view')
def tutorial_index():
    page = max(int(request.args.get('page', 1)), 1)
    category_id = request.args.get('category', '')
    keyword = (request.args.get('keyword') or '').strip()

    query = Tutorial.query.filter_by(is_deleted=False)
    if category_id and category_id.isdigit():
        query = query.filter_by(category_id=int(category_id))
    if keyword:
        query = query.filter(Tutorial.title.contains(keyword))

    pagination = query.order_by(
        Tutorial.sort_order.desc(), Tutorial.created_at.desc()
    ).paginate(page=page, per_page=15, error_out=False)

    categories = TutorialCategory.query.filter_by(is_deleted=False).order_by(
        TutorialCategory.sort_order.desc()).all()

    return render_template(
        'admin/tutorial/index.html',
        tutorials=pagination.items, pagination=pagination,
        categories=categories, current_category=category_id, keyword=keyword,
    )


@admin_bp.route('/tutorials/create', methods=['GET', 'POST'])
@_gate
@permission_required('tutorial:manage')
def tutorial_create():
    if request.method == 'POST':
        tutorial = _save_tutorial(None)
        if tutorial is None:
            return redirect(url_for('admin.tutorial_create'))
        return redirect(url_for('admin.tutorial_edit', tid=tutorial.id))
    categories = TutorialCategory.query.filter_by(is_deleted=False).order_by(
        TutorialCategory.sort_order.desc()).all()
    return render_template(
        'admin/tutorial/form.html', tutorial=None,
        categories=categories, difficulties=DIFFICULTY_CHOICES,
    )


@admin_bp.route('/tutorials/<int:tid>/edit', methods=['GET', 'POST'])
@_gate
@permission_required('tutorial:manage')
def tutorial_edit(tid):
    tutorial = Tutorial.query.get_or_404(tid)
    if tutorial.is_deleted:
        abort(404)
    if request.method == 'POST':
        _save_tutorial(tutorial)
        return redirect(url_for('admin.tutorial_edit', tid=tid))
    categories = TutorialCategory.query.filter_by(is_deleted=False).order_by(
        TutorialCategory.sort_order.desc()).all()
    return render_template(
        'admin/tutorial/form.html', tutorial=tutorial,
        categories=categories, difficulties=DIFFICULTY_CHOICES,
    )


def _save_tutorial(tutorial):
    title = (request.form.get('title') or '').strip()
    slug = (request.form.get('slug') or '').strip().lower()
    category_id = request.form.get('category_id', type=int)
    content = (request.form.get('content') or '').strip()
    if not title or not slug or not category_id:
        flash(_gettext('标题、标识、分类必填'), 'danger')
        return None
    if not content:
        flash(_gettext('正文内容必填'), 'danger')
        return None

    existing = Tutorial.query.filter_by(slug=slug, is_deleted=False).first()
    if existing and (tutorial is None or existing.id != tutorial.id):
        flash(_gettext('教程标识已存在'), 'danger')
        return None

    is_new = tutorial is None
    if is_new:
        tutorial = Tutorial(slug=slug)
        db.session.add(tutorial)

    tutorial.title = title
    tutorial.slug = slug
    tutorial.category_id = category_id
    tutorial.summary = (request.form.get('summary') or '').strip()
    tutorial.content = content
    tutorial.difficulty = request.form.get('difficulty') or 'beginner'
    try:
        tutorial.duration = max(int(request.form.get('duration') or 0), 0)
    except ValueError:
        tutorial.duration = 0
    try:
        tutorial.sort_order = int(request.form.get('sort_order') or 0)
    except ValueError:
        tutorial.sort_order = 0
    tutorial.is_enabled = (request.form.get('is_enabled') == 'on')

    # 封面图上传
    cover_file = request.files.get('cover')
    if cover_file and cover_file.filename:
        rel, url, err = save_upload_file(
            cover_file, sub_dir='tutorial',
            allowed_exts=list(_Upload.IMAGE_EXTS))
        if err:
            flash(_gettext('封面上传失败：{0}').format(err), 'danger')
        else:
            tutorial.cover = url
    elif request.form.get('cover_remove') == 'on':
        tutorial.cover = ''

    db.session.commit()
    flash(_gettext('教程已保存'), 'success')
    audit_log(OP_CREATE if is_new else OP_UPDATE, MODULE_TUTORIAL,
              tutorial.id, tutorial.title, {'slug': tutorial.slug})
    return tutorial


@admin_bp.route('/tutorials/<int:tid>/delete', methods=['POST'])
@_gate
@permission_required('tutorial:manage')
def tutorial_delete(tid):
    tutorial = Tutorial.query.get_or_404(tid)
    tutorial.is_deleted = True
    db.session.commit()
    flash(_gettext('教程已删除'), 'success')
    audit_log(OP_DELETE, MODULE_TUTORIAL, tutorial.id, tutorial.title, {})
    return redirect(url_for('admin.tutorial_index'))


# ============ 分类管理 ============

@admin_bp.route('/tutorials/categories')
@_gate
@permission_required('tutorial:view')
def tutorial_categories():
    categories = TutorialCategory.query.filter_by(is_deleted=False).order_by(
        TutorialCategory.sort_order.desc()).all()
    return render_template('admin/tutorial/categories.html', categories=categories)


@admin_bp.route('/tutorials/categories/create', methods=['GET', 'POST'])
@_gate
@permission_required('tutorial:manage')
def tutorial_category_create():
    if request.method == 'POST':
        cat = _save_category(None)
        if cat is None:
            return redirect(url_for('admin.tutorial_category_create'))
        return redirect(url_for('admin.tutorial_categories'))
    return render_template('admin/tutorial/category_form.html', category=None)


@admin_bp.route('/tutorials/categories/<int:cid>/edit', methods=['GET', 'POST'])
@_gate
@permission_required('tutorial:manage')
def tutorial_category_edit(cid):
    category = TutorialCategory.query.get_or_404(cid)
    if category.is_deleted:
        abort(404)
    if request.method == 'POST':
        _save_category(category)
        return redirect(url_for('admin.tutorial_categories'))
    return render_template('admin/tutorial/category_form.html', category=category)


def _save_category(category):
    name = (request.form.get('name') or '').strip()
    slug = (request.form.get('slug') or '').strip().lower()
    if not name or not slug:
        flash(_gettext('名称和标识必填'), 'danger')
        return None

    existing = TutorialCategory.query.filter_by(slug=slug, is_deleted=False).first()
    if existing and (category is None or existing.id != category.id):
        flash(_gettext('分类标识已存在'), 'danger')
        return None

    is_new = category is None
    if is_new:
        category = TutorialCategory(slug=slug)
        db.session.add(category)

    category.name = name
    category.slug = slug
    category.description = (request.form.get('description') or '').strip()
    try:
        category.sort_order = int(request.form.get('sort_order') or 0)
    except ValueError:
        category.sort_order = 0
    category.is_enabled = (request.form.get('is_enabled') == 'on')

    db.session.commit()
    flash(_gettext('分类已保存'), 'success')
    audit_log(OP_CREATE if is_new else OP_UPDATE, MODULE_TUTORIAL_CATEGORY,
              category.id, category.name, {'slug': category.slug})
    return category


@admin_bp.route('/tutorials/categories/<int:cid>/delete', methods=['POST'])
@_gate
@permission_required('tutorial:manage')
def tutorial_category_delete(cid):
    category = TutorialCategory.query.get_or_404(cid)
    # 若分类下有未删除的教程，禁止删除
    has_tutorials = Tutorial.query.filter_by(
        category_id=cid, is_deleted=False).count() > 0
    if has_tutorials:
        flash(_gettext('该分类下仍有教程，无法删除'), 'danger')
        return redirect(url_for('admin.tutorial_categories'))
    category.is_deleted = True
    db.session.commit()
    flash(_gettext('分类已删除'), 'success')
    audit_log(OP_DELETE, MODULE_TUTORIAL_CATEGORY, category.id, category.name, {})
    return redirect(url_for('admin.tutorial_categories'))
