"""教程插件：前台路由蓝本。

路由：
  /tutorials                    教程列表（支持分类筛选、分页）
  /tutorials/category/<slug>    分类下教程列表
  /tutorials/<slug>             教程详情（浏览量 +1）

模板解析（两级）：
  1. 当前主题提供 themes/<主题>/tutorial_list.html 时优先使用
     （如教育行业主题有专属课程页面）；
  2. 否则回退插件内置模板 frontend/tutorial_list.html（随插件分发，
     不向其他主题目录写入模板文件）。
由核心 theme_template() 解析；插件蓝本 template_folder 同时把后台
管理页模板（admin/tutorial/*）与内置前台模板接入 Jinja 搜索路径。

守卫：未启用插件时所有路由 404。
"""
import os
from functools import wraps

from flask import (
    Blueprint, render_template, request, abort,
)

from app.extensions import db
from app.plugin_system import plugin_enabled
from app.utils.themes import theme_template, get_active_theme, THEMES_DIR

from .models import TutorialCategory, Tutorial

tutorial_frontend = Blueprint('tutorial_frontend', __name__,
                              template_folder='templates')

# 插件内置兜底模板（位于 plugins/tutorial/templates/frontend/）
_BUILTIN_TEMPLATES = {
    'tutorial_list': 'frontend/tutorial_list.html',
    'tutorial_detail': 'frontend/tutorial_detail.html',
}


def _resolve_template(name):
    """主题目录存在专属模板时用主题模板，否则回退插件内置模板。"""
    theme = get_active_theme()
    theme_path = os.path.join(THEMES_DIR, theme, f'{name}.html')
    if os.path.isfile(theme_path):
        return theme_template(name)
    return _BUILTIN_TEMPLATES[name]


def _gate(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('tutorial'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def _build_nav():
    from app.frontend.views import _build_nav as _nav
    return _nav()


def _seo(**kwargs):
    from app.frontend.views import _seo as _s
    return _s(**kwargs)


@tutorial_frontend.route('/tutorials')
@_gate
def tutorial_list():
    """教程列表：支持 category / keyword / difficulty 筛选，分页。"""
    page = max(int(request.args.get('page', 1)), 1)
    per_page = int(request.args.get('per_page', 12))
    category_slug = (request.args.get('category') or '').strip()
    keyword = (request.args.get('keyword') or '').strip()
    difficulty = (request.args.get('difficulty') or '').strip()

    query = Tutorial.query.filter_by(is_deleted=False, is_enabled=True)

    category = None
    if category_slug:
        category = TutorialCategory.query.filter_by(
            slug=category_slug, is_deleted=False, is_enabled=True).first()
        if category is not None:
            query = query.filter_by(category_id=category.id)

    if keyword:
        query = query.filter(Tutorial.title.contains(keyword))
    if difficulty in Tutorial.DIFFICULTY_LABELS:
        query = query.filter_by(difficulty=difficulty)

    pagination = query.order_by(
        Tutorial.sort_order.desc(), Tutorial.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    categories = TutorialCategory.query.filter_by(
        is_deleted=False, is_enabled=True
    ).order_by(TutorialCategory.sort_order.desc()).all()

    return render_template(
        _resolve_template('tutorial_list'),
        tutorials=pagination.items,
        pagination=pagination,
        categories=categories,
        current_category=category,
        keyword=keyword,
        difficulty=difficulty,
        nav=_build_nav(),
        seo=_seo(),
    )


@tutorial_frontend.route('/tutorials/category/<slug>')
@_gate
def tutorial_category(slug):
    """分类下教程列表（复用 list 模板）。"""
    category = TutorialCategory.query.filter_by(
        slug=slug, is_deleted=False, is_enabled=True).first_or_404()

    page = max(int(request.args.get('page', 1)), 1)
    pagination = Tutorial.query.filter_by(
        category_id=category.id, is_deleted=False, is_enabled=True
    ).order_by(
        Tutorial.sort_order.desc(), Tutorial.created_at.desc()
    ).paginate(page=page, per_page=12, error_out=False)

    categories = TutorialCategory.query.filter_by(
        is_deleted=False, is_enabled=True
    ).order_by(TutorialCategory.sort_order.desc()).all()

    return render_template(
        _resolve_template('tutorial_list'),
        tutorials=pagination.items,
        pagination=pagination,
        categories=categories,
        current_category=category,
        keyword='',
        difficulty='',
        nav=_build_nav(),
        seo=_seo(column=category),
    )


@tutorial_frontend.route('/tutorials/<slug>')
@_gate
def tutorial_detail(slug):
    """教程详情：浏览量 +1，相邻教程导航。"""
    tutorial = Tutorial.query.filter_by(
        slug=slug, is_deleted=False, is_enabled=True).first_or_404()

    # 浏览量自增
    tutorial.view_count = (tutorial.view_count or 0) + 1
    db.session.commit()

    # 相邻教程（同分类）
    prev = Tutorial.query.filter(
        Tutorial.category_id == tutorial.category_id,
        Tutorial.id < tutorial.id,
        Tutorial.is_deleted == False,
        Tutorial.is_enabled == True,
    ).order_by(Tutorial.id.desc()).first()

    next_t = Tutorial.query.filter(
        Tutorial.category_id == tutorial.category_id,
        Tutorial.id > tutorial.id,
        Tutorial.is_deleted == False,
        Tutorial.is_enabled == True,
    ).order_by(Tutorial.id.asc()).first()

    # 相关推荐（同分类，排除自身，取 4 条）
    related = Tutorial.query.filter(
        Tutorial.category_id == tutorial.category_id,
        Tutorial.id != tutorial.id,
        Tutorial.is_deleted == False,
        Tutorial.is_enabled == True,
    ).order_by(Tutorial.sort_order.desc()).limit(4).all()

    return render_template(
        _resolve_template('tutorial_detail'),
        tutorial=tutorial,
        prev_tutorial=prev,
        next_tutorial=next_t,
        related=related,
        nav=_build_nav(),
        seo=_seo(article=tutorial),
    )
