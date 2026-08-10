"""前台路由：首页、栏目、文章、表单提交。"""
import os
import time
from datetime import datetime

from flask import (
    render_template, redirect, url_for, request,
    flash, abort, session, current_app, jsonify, send_from_directory
)

from ..extensions import db
from ..models.column import Column, ColumnField
from ..models.article import Article, ArticleFieldValue
from ..models.fragment import Fragment
from ..models.friend_link import FriendLink
from ..models.form import Form, FormField, FormSubmission, FormSubmissionValue
from ..models.setting import Setting
from ..utils.uploads import save_upload_file
from ..utils.themes import theme_template, get_column_template
from ..utils.captcha import generate_captcha
from . import frontend_bp


def _build_nav():
    """构建导航树。"""
    columns = Column.get_tree(enabled_only=True)
    return Column.build_nested(columns)


def _seo(column=None, article=None):
    """获取页面 SEO 信息。"""
    s = Setting.get_dict()
    if article:
        return {
            'title': article.seo_title or article.title or s.get('seo_title', ''),
            'keywords': article.seo_keywords or s.get('seo_keywords', ''),
            'description': article.seo_description or article.summary or s.get('seo_description', ''),
        }
    if column:
        return {
            'title': column.seo_title or column.name or s.get('seo_title', ''),
            'keywords': column.seo_keywords or s.get('seo_keywords', ''),
            'description': column.seo_description or column.summary or s.get('seo_description', ''),
        }
    return {
        'title': s.get('seo_title', ''),
        'keywords': s.get('seo_keywords', ''),
        'description': s.get('seo_description', ''),
    }


@frontend_bp.before_request
def check_site_status():
    """站点维护模式拦截（除首页提示外，所有前台路由都跳到关闭页）。"""
    if Setting.get('site_status') == 'closed':
        # 允许访问 admin 蓝本（已在另一个蓝本注册，这里不影响）
        if request.path.startswith('/admin'):
            return
        # 站点根文件（favicon/robots/sitemap）不受维护模式影响，保证收录与图标正常
        if request.endpoint in ('frontend.favicon', 'frontend.robots', 'frontend.sitemap'):
            return
        return render_template(theme_template('closed')), 503


def _home_column_articles(slug, limit=8):
    """按 slug 查找栏目，收集其（含子栏目）下的文章，用于首页展示。

    返回 (column, [articles])；栏目不存在返回 (None, [])。
    """
    col = Column.query.filter_by(
        slug=slug, is_enabled=True, is_deleted=False
    ).first()
    if col is None:
        return None, []

    # 收集本栏目及其直接子栏目下的文章
    col_ids = [col.id]
    for child in col.children.filter_by(is_deleted=False, is_enabled=True).all():
        col_ids.append(child.id)

    articles = Article.query.filter(
        Article.column_id.in_(col_ids),
        Article.is_deleted == False,
        Article.is_enabled == True,
    ).order_by(
        Article.sort_order.desc(), Article.published_at.desc()
    ).limit(limit).all()
    return col, articles


@frontend_bp.route('/')
def index():
    # 首页默认取第一个单页栏目或自定义首页
    nav = _build_nav()
    # 取第一个单页栏目作为首页内容（或显示一个聚合首页）
    top_pages = Column.query.filter_by(
        parent_id=None, type='page', is_enabled=True, is_deleted=False
    ).order_by(Column.sort_order.desc()).first()

    friend_links = FriendLink.query.filter_by(
        is_enabled=True, is_deleted=False
    ).order_by(FriendLink.sort_order.desc()).all()

    # 最新动态：取列表栏目下的最新文章
    list_columns = Column.query.filter_by(
        type='list', is_enabled=True, is_deleted=False
    ).all()
    latest_articles = []
    for col in list_columns[:3]:
        for a in col.articles.filter_by(
            is_enabled=True, is_deleted=False
        ).order_by(Article.published_at.desc()).limit(5).all():
            latest_articles.append((col, a))

    # ===== 行业主题首页所需数据（对通用主题无副作用）=====
    # 关于我们单页
    about_col = Column.query.filter_by(
        slug='about', is_enabled=True, is_deleted=False
    ).first()
    # 产品中心 / 服务项目（制造业=products，服务业=services）
    products_col, products = _home_column_articles('products', limit=8)
    services_col, services = _home_column_articles('services', limit=6)
    # 新闻中心 / 新闻动态
    news_col, news = _home_column_articles('news', limit=6)
    # 客户案例（服务业）
    cases_col, cases = _home_column_articles('cases', limit=4)

    return render_template(
        theme_template('index'),
        nav=nav, friend_links=friend_links,
        first_page=top_pages, latest_articles=latest_articles,
        about_col=about_col,
        products_col=products_col, products=products,
        services_col=services_col, services=services,
        news_col=news_col, news=news,
        cases_col=cases_col, cases=cases,
        seo=_seo()
    )


@frontend_bp.route('/column/<slug>')
def column_detail(slug):
    col = Column.query.filter_by(slug=slug, is_deleted=False).first_or_404()
    if not col.is_enabled:
        abort(404)

    nav = _build_nav()

    # 链接栏目：直接跳转
    if col.type == 'link':
        return redirect(col.link_url or '/')

    # 父栏目：根据模式处理
    if col.is_parent:
        children = col.children.filter_by(is_deleted=False, is_enabled=True).order_by(
            Column.sort_order.desc(), Column.created_at.desc()
        ).all()
        if not children:
            abort(404)
        if col.parent_mode == 'first_child':
            return redirect(url_for('frontend.column_detail', slug=children[0].slug))
        # 展示子栏目列表
        return render_template(
            theme_template('column_children'),
            column=col, children=children, nav=nav, seo=_seo(column=col)
        )

    # 叶子栏目
    if col.type == 'page':
        # 单页栏目（使用栏目指定的 page 模板，默认 page）
        # 传入前台可见的自定义字段，模板可用 column.get_field_value(field.id) 取值
        fields = col.fields.filter_by(
            is_deleted=False, is_frontend_visible=True
        ).order_by(ColumnField.sort_order.desc()).all()
        tpl = get_column_template(col, 'page')
        return render_template(
            theme_template(tpl),
            column=col, fields=fields, nav=nav, seo=_seo(column=col)
        )
    elif col.type == 'list':
        # 列表栏目分页（使用栏目指定的 list 模板，默认 list）
        page = max(int(request.args.get('page', 1)), 1)
        per_page = col.page_size or 10
        pagination = Article.query.filter_by(
            column_id=col.id, is_deleted=False, is_enabled=True
        ).order_by(
            Article.sort_order.desc(), Article.published_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        tpl = get_column_template(col, 'list')
        return render_template(
            theme_template(tpl),
            column=col, articles=pagination.items, pagination=pagination,
            nav=nav, seo=_seo(column=col)
        )

    abort(404)


@frontend_bp.route('/column/<slug>/article/<int:aid>')
def article_detail(slug, aid):
    # 兼容旧链接格式
    col = Column.query.filter_by(slug=slug, is_deleted=False).first_or_404()
    article = Article.query.get_or_404(aid)
    if article.column_id != col.id or article.is_deleted or not article.is_enabled:
        abort(404)

    # 浏览量 +1（写入失败不影响页面渲染）
    try:
        article.viewed = (article.viewed or 0) + 1
        db.session.commit()
    except Exception:
        db.session.rollback()

    nav = _build_nav()
    fields = col.fields.filter_by(is_deleted=False, is_frontend_visible=True).order_by(
        ColumnField.sort_order.desc()
    ).all()

    # 侧边栏最新文章
    latest_articles = col.articles.filter_by(
        is_enabled=True, is_deleted=False
    ).order_by(Article.published_at.desc()).limit(8).all()

    # 上一篇/下一篇
    prev_article = Article.query.filter(
        Article.column_id == col.id,
        Article.is_deleted == False,
        Article.is_enabled == True,
        Article.id < article.id
    ).order_by(Article.id.desc()).first()
    next_article = Article.query.filter(
        Article.column_id == col.id,
        Article.is_deleted == False,
        Article.is_enabled == True,
        Article.id > article.id
    ).order_by(Article.id.asc()).first()

    # 使用栏目指定的 detail 模板，默认 article
    tpl = get_column_template(col, 'detail')
    return render_template(
        theme_template(tpl),
        column=col, article=article, fields=fields,
        latest_articles=latest_articles,
        prev_article=prev_article, next_article=next_article,
        nav=nav, seo=_seo(article=article)
    )


# 兼容更短的 URL：/article/<aid>
@frontend_bp.route('/article/<int:aid>')
def article_short(aid):
    article = Article.query.get_or_404(aid)
    return redirect(url_for('frontend.article_detail',
                            slug=article.column.slug, aid=article.id))


@frontend_bp.route('/form/<slug>', methods=['GET', 'POST'])
def form_submit(slug):
    form = Form.query.filter_by(slug=slug, is_deleted=False).first_or_404()
    if not form.is_open:
        return render_template(theme_template('form_closed'), form=form,
                               nav=_build_nav(), seo=_seo()), 403

    nav = _build_nav()
    fields = form.fields.filter_by(is_deleted=False).order_by(FormField.sort_order.asc()).all()

    if request.method == 'POST':
        # 防重复提交：基于 IP + form_id
        if form.submit_interval > 0:
            cache_key = f'form_submit_{form.id}_{request.remote_addr}'
            last = session.get(cache_key, 0)
            now = int(time.time())
            if now - last < form.submit_interval:
                flash(f'提交过于频繁，请 {form.submit_interval - (now - last)} 秒后再试', 'danger')
                return redirect(url_for('frontend.form_submit', slug=slug))

        # 图形验证码校验：防止脚本恶意反复提交
        captcha = (request.form.get('captcha') or '').strip().lower()
        session_captcha = (session.get('form_captcha') or '').lower()
        # 验证码为一次性，无论成败都作废，避免重放
        session.pop('form_captcha', None)
        if not session_captcha or captcha != session_captcha:
            flash('验证码错误，请重新输入', 'danger')
            return redirect(url_for('frontend.form_submit', slug=slug))

        # 校验必填
        errors = []
        for f in fields:
            val = request.form.get(f'field_{f.id}') or ''
            file_obj = request.files.get(f'field_{f.id}')
            if f.is_required and not val and not (file_obj and file_obj.filename):
                errors.append(f'{f.label} 为必填项')

        # 邮箱/手机号格式校验
        for f in fields:
            val = (request.form.get(f'field_{f.id}') or '').strip()
            if not val:
                continue
            if f.field_type == 'email' and '@' not in val:
                errors.append(f'{f.label} 格式不正确')
            elif f.field_type == 'phone' and not val.isdigit():
                errors.append(f'{f.label} 必须为数字')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return redirect(url_for('frontend.form_submit', slug=slug))

        # 保存提交
        sub = FormSubmission(
            form_id=form.id,
            ip=request.remote_addr or '',
            user_agent=request.user_agent.string[:255] if request.user_agent else '',
        )
        db.session.add(sub)
        db.session.flush()

        for f in fields:
            value = None
            if f.field_type == 'file':
                file_obj = request.files.get(f'field_{f.id}')
                if file_obj and file_obj.filename:
                    allowed = f.allowed_exts.split(',') if f.allowed_exts else None
                    rel, url, err = save_upload_file(
                        file_obj, sub_dir=f'form/{form.slug}',
                        allowed_exts=allowed, max_size=f.max_size
                    )
                    if err:
                        flash(f'字段 {f.label} 上传失败：{err}', 'danger')
                        db.session.rollback()
                        return redirect(url_for('frontend.form_submit', slug=slug))
                    value = url
            elif f.field_type == 'checkbox':
                values = request.form.getlist(f'field_{f.id}')
                value = '|||'.join(values)
            else:
                value = request.form.get(f'field_{f.id}') or ''

            if value is not None:
                v = FormSubmissionValue(submission_id=sub.id, field_id=f.id, value=value)
                db.session.add(v)

        db.session.commit()
        if form.submit_interval > 0:
            session[cache_key] = int(time.time())

        flash(form.success_message, 'success')
        return redirect(url_for('frontend.form_submit', slug=slug))

    return render_template(
        theme_template('form'), form=form, fields=fields,
        nav=nav, seo=_seo()
    )


@frontend_bp.route('/captcha')
def captcha():
    """前台图形验证码：用于自定义表单提交防刷。

    与后台登录验证码分开存储（session 键为 form_captcha），互不干扰。
    """
    code, image_data = generate_captcha()
    session['form_captcha'] = code
    resp = current_app.response_class(image_data, mimetype='image/png')
    # 禁止缓存，保证每次刷新都拿到新验证码
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@frontend_bp.route('/search')
def search():
    """全站简单搜索（仅文章标题）。"""
    keyword = (request.args.get('q') or '').strip()
    results = []
    if keyword:
        results = Article.query.filter(
            Article.is_deleted == False,
            Article.is_enabled == True,
            Article.title.like(f'%{keyword}%')
        ).order_by(Article.published_at.desc()).limit(50).all()
    return render_template(
        theme_template('search'), keyword=keyword, results=results,
        nav=_build_nav(), seo=_seo()
    )


@frontend_bp.route('/favicon.ico')
def favicon():
    """站点图标：浏览器默认请求 /favicon.ico。

    图标来源为 https://www.tzzhy.cn/ 的站点图标，已复制到 static/img/favicon.ico。
    """
    return send_from_directory(
        os.path.join(current_app.static_folder, 'img'),
        'favicon.ico', mimetype='image/vnd.microsoft.icon'
    )


@frontend_bp.route('/robots.txt')
def robots():
    """爬虫协议：允许收录前台内容，禁止收录后台与上传目录，声明站点地图。"""
    from ..utils.admin_prefix import load_admin_prefix

    admin_prefix = load_admin_prefix()
    site_url = request.url_root.rstrip('/')
    lines = [
        'User-agent: *',
        f'Disallow: /{admin_prefix}/',
        'Disallow: /form/',
        'Disallow: /search',
        'Allow: /',
        '',
        f'Sitemap: {site_url}/sitemap.xml',
        '',
    ]
    return current_app.response_class(
        '\n'.join(lines), mimetype='text/plain'
    )


@frontend_bp.route('/sitemap.xml')
def sitemap():
    """站点地图：列出首页、栏目页与文章页，供搜索引擎收录。

    仅收录启用且未删除的内容；链接栏目（跳转外链）不纳入。
    lastmod 取内容的更新时间（文章优先用发布时间）。
    """
    from xml.sax.saxutils import escape

    def _lastmod(dt):
        return dt.strftime('%Y-%m-%d') if dt else ''

    urls = []

    # 首页
    urls.append({
        'loc': url_for('frontend.index', _external=True),
        'lastmod': '',
        'changefreq': 'daily',
        'priority': '1.0',
    })

    # 栏目页（排除链接栏目）
    columns = Column.query.filter(
        Column.is_enabled == True,
        Column.is_deleted == False,
        Column.type != 'link',
    ).order_by(Column.sort_order.desc()).all()
    for col in columns:
        urls.append({
            'loc': url_for('frontend.column_detail', slug=col.slug, _external=True),
            'lastmod': _lastmod(col.updated_at),
            'changefreq': 'weekly',
            'priority': '0.8',
        })

    # 文章页
    articles = Article.query.filter(
        Article.is_enabled == True,
        Article.is_deleted == False,
    ).order_by(Article.published_at.desc()).all()
    for a in articles:
        urls.append({
            'loc': url_for('frontend.article_detail', slug=a.column.slug,
                           aid=a.id, _external=True),
            'lastmod': _lastmod(a.updated_at or a.published_at),
            'changefreq': 'monthly',
            'priority': '0.6',
        })

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        parts.append('  <url>')
        parts.append(f'    <loc>{escape(u["loc"])}</loc>')
        if u['lastmod']:
            parts.append(f'    <lastmod>{u["lastmod"]}</lastmod>')
        parts.append(f'    <changefreq>{u["changefreq"]}</changefreq>')
        parts.append(f'    <priority>{u["priority"]}</priority>')
        parts.append('  </url>')
    parts.append('</urlset>')
    parts.append('')

    return current_app.response_class(
        '\n'.join(parts), mimetype='application/xml'
    )


@frontend_bp.app_errorhandler(404)
def page_not_found(e):
    return render_template(theme_template('404'), nav=_build_nav(),
                           seo=_seo()), 404


@frontend_bp.app_errorhandler(500)
def server_error(e):
    return render_template(theme_template('500'), nav=_build_nav(),
                           seo=_seo()), 500
