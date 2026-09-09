"""前台路由：首页、栏目、文章、根文件（favicon/robots/sitemap）。
升级点：
  - 模块8：缓存装饰器（基于 Flask-Caching）作用在首页/栏目/文章页面，Setting TTL 控制
  - 模块8：伪静态 URL（seo_rewrite_enable=on 时生效 /<slug>.html /article-<aid>.html）
  - 模块8：sitemap.xml 读取 Setting 的 changefreq/priority 配置（栏目/文章分别）
  - 模块8：robots.txt 追加 Setting.seo_robots_custom 自定义文本
  - 模块8：图片缺省时注入默认 ALT（Setting.seo_image_alt_default）
  - 工作流：所有前台公开 Article 查询强制 status=STATUS_PUBLISHED（防御式，和 is_enabled 等价）
"""
import os
import re
import time
from datetime import datetime
from functools import wraps

from flask import (
    render_template, redirect, url_for, request,
    flash, abort, session, current_app, jsonify, send_from_directory
)

from ..extensions import db
from ..models.column import Column, ColumnField
from ..models.article import Article, ArticleFieldValue
from ..models.fragment import Fragment
# 自定义表单 v2.3.0 起转为内置插件 plugins/form，前台 /form/<slug> 路由由插件蓝本提供
from ..models.setting import Setting
from ..models.workflow import STATUS_PUBLISHED
from ..utils.themes import (
    theme_template, get_column_template, THEMES_DIR, THEME_SLUG_RE,
)
from ..utils.captcha import generate_captcha
from . import frontend_bp


def frontend_pager_url(column, page):
    """前台列表分页 URL 生成（模块8 伪静态适配）。

    - seo_rewrite_enable=on：第一页 /{slug}.html，第 N 页 /{slug}-{N}.html
    - 关闭：/column/{slug}?page=N（动态查询参数，原有行为）
    供 Jinja 全局使用（8 个主题列表模板的分页链接统一走这里）。
    """
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1
    if Setting.get('seo_rewrite_enable') == 'on':
        if page <= 1:
            return f'/{column.slug}.html'
        return f'/{column.slug}-{page}.html'
    return url_for('frontend.column_detail', slug=column.slug, page=page)


# ============================================================
# 模块8：缓存 / 伪静态 / 图片ALT 工具
# ============================================================

def _cache_enabled():
    return Setting.get('cache_enable') == 'on'


def _try_cache(key, ttl_setting_key, default_ttl=600):
    """页面缓存装饰器（简易）：根据 Setting.cache_enable 开关决定是否走缓存。"""
    from ..extensions import cache

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if not _cache_enabled():
                return view_func(*args, **kwargs)
            try:
                ttl = int(Setting.get(ttl_setting_key, default_ttl))
            except (TypeError, ValueError):
                ttl = default_ttl
            cache_key = f'frontend/{key}/' + '/'.join(
                [str(v) for v in args] + [f'{k}={v}' for k, v in sorted(kwargs.items())]
            ) + request.query_string.decode('utf-8', errors='ignore')
            # v2.5.0：缓存键包含当前 locale，避免不同语言命中同一缓存
            try:
                from ..i18n import select_locale
                cache_key += '|loc=' + select_locale()
            except Exception:
                pass
            try:
                cached = cache.get(cache_key)
                if cached is not None:
                    return cached
            except Exception:
                pass
            resp = view_func(*args, **kwargs)
            try:
                cache.set(cache_key, resp, timeout=ttl)
            except Exception:
                pass
            return resp
        return wrapper
    return decorator


def _inject_default_alt(html):
    """模块8：把 HTML 中 <img ... alt="" 或缺失 alt> 的 alt 补充为 Setting 默认值。"""
    if not html:
        return html
    default_alt = Setting.get('seo_image_alt_default') or ''
    if not default_alt:
        return html
    default_alt = default_alt.replace('"', '&quot;')

    def _rep(match):
        tag = match.group(0)
        if re.search(r'alt\s*=\s*"[^"]+"', tag) or re.search(r"alt\s*=\s*'[^']+'", tag):
            # 已有 alt 属性且非空
            m2 = re.search(r'alt\s*=\s*"([^"]*)"', tag) or re.search(r"alt\s*=\s*'([^']*)'", tag)
            if m2 and m2.group(1).strip():
                return tag
        # 补 alt
        if 'alt=' in tag.lower():
            # 有 alt 但为空字符串：替换其值
            tag_new = re.sub(r'alt\s*=\s*""', f'alt="{default_alt}"', tag)
            tag_new = re.sub(r"alt\s*=\s*''", f"alt='{default_alt}'", tag_new)
            return tag_new
        # 完全缺失：在 <img 后插入
        return re.sub(r'(<img\b)', r'\1 alt="' + default_alt + r'"', tag, count=1, flags=re.IGNORECASE)

    return re.sub(r'<img\b[^>]*>', _rep, html, flags=re.IGNORECASE)


# ============================================================
# 通用辅助
# ============================================================

def _build_nav():
    """构建导航树：启用栏目 + 启用插件贡献的菜单项（追加在树尾）。

    插件菜单项构造为 type='link' 的虚拟外链栏目节点，主题导航宏的
    外链分支（col.name / col.link_url / col.link_target）可直接渲染，
    各主题无需为插件单独改造。
    """
    columns = Column.get_tree(enabled_only=True)
    tree = Column.build_nested(columns)
    try:
        from ..plugin_system import plugin_frontend_menus
        from types import SimpleNamespace
        for m in plugin_frontend_menus():
            fake_col = SimpleNamespace(
                type='link', name=m['label'],
                link_url=m['url'], link_target=m['target'],
            )
            tree.append({'node': fake_col, 'children': []})
    except Exception:
        pass
    return tree


def _seo(column=None, article=None):
    """获取页面 SEO 信息（v2.5.0：按当前 locale 取翻译，无翻译回退主表字段）。"""
    from ..utils.i18n_content import t_field
    s = Setting.get_dict()
    if article:
        return {
            'title': t_field(article, 'seo_title') or t_field(article, 'title') or s.get('seo_title', ''),
            'keywords': t_field(article, 'seo_keywords') or s.get('seo_keywords', ''),
            'description': t_field(article, 'seo_description') or t_field(article, 'summary') or s.get('seo_description', ''),
        }
    if column:
        return {
            'title': t_field(column, 'seo_title') or t_field(column, 'name') or s.get('seo_title', ''),
            'keywords': t_field(column, 'seo_keywords') or s.get('seo_keywords', ''),
            'description': t_field(column, 'seo_description') or t_field(column, 'summary') or s.get('seo_description', ''),
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
        from ..utils.admin_prefix import load_admin_prefix
        admin_prefix = load_admin_prefix()
        if request.path.startswith('/' + admin_prefix):
            return
        # 站点根文件（favicon/robots/sitemap）不受维护模式影响，保证收录与图标正常
        if request.endpoint in ('frontend.favicon', 'frontend.robots', 'frontend.sitemap'):
            return
        return render_template(theme_template('closed'), seo=_seo()), 503


def _home_column_articles(slug, limit=8):
    """按 slug 查找栏目，收集其（含子栏目）下的文章，用于首页展示。"""
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
        Article.status == STATUS_PUBLISHED,  # 工作流：只显示已发布
    ).order_by(
        Article.sort_order.desc(), Article.published_at.desc()
    ).limit(limit).all()
    return col, articles


# ============================================================
# 首页（模块8缓存：cache_ttl_index）
# ============================================================

@frontend_bp.route('/')
@_try_cache('index', 'cache_ttl_index', 600)
def index():
    nav = _build_nav()
    top_pages = Column.query.filter_by(
        parent_id=None, type='page', is_enabled=True, is_deleted=False
    ).order_by(Column.sort_order.desc()).first()

    # 友情链接改由 friend_link 插件提供（模板全局函数 friend_links()，禁用时返回 []）

    list_columns = Column.query.filter_by(
        type='list', is_enabled=True, is_deleted=False
    ).all()
    latest_articles = []
    for col in list_columns[:3]:
        for a in col.articles.filter_by(
            is_deleted=False, status=STATUS_PUBLISHED
        ).order_by(Article.published_at.desc()).limit(5).all():
            latest_articles.append((col, a))

    # 行业主题首页数据
    about_col = Column.query.filter_by(
        slug='about', is_enabled=True, is_deleted=False
    ).first()
    products_col, products = _home_column_articles('products', limit=8)
    services_col, services = _home_column_articles('services', limit=6)
    news_col, news = _home_column_articles('news', limit=6)
    cases_col, cases = _home_column_articles('cases', limit=4)

    # 图片默认 ALT 注入（对内容型单页的 page_content，留空由单页渲染处处理）
    return render_template(
        theme_template('index'),
        nav=nav,
        first_page=top_pages, latest_articles=latest_articles,
        about_col=about_col,
        products_col=products_col, products=products,
        services_col=services_col, services=services,
        news_col=news_col, news=news,
        cases_col=cases_col, cases=cases,
        seo=_seo()
    )


# ============================================================
# 模块8：伪静态 URL（仅 seo_rewrite_enable=on 时启用）
# ============================================================

@frontend_bp.route('/<slug>.html')
def rewrite_column(slug):
    """伪静态：/about.html → /column/about；仅 seo_rewrite_enable=on 生效，否则 404。"""
    if Setting.get('seo_rewrite_enable') != 'on':
        abort(404)
    return column_detail(slug)


@frontend_bp.route('/<slug>-<int:page>.html')
def rewrite_column_page(slug, page):
    """伪静态列表分页：/about-2.html → /column/about?page=2。

    Werkzeug 对静态段更多的规则优先匹配（已实测）：
    - /about.html          → rewrite_column
    - /about-2.html        → 本视图（slug='about', page=2）
    - /news-2024-2.html    → 本视图（slug='news-2024', page=2），含 -数字 的 slug 不会误切
    """
    if Setting.get('seo_rewrite_enable') != 'on':
        abort(404)
    if page <= 1:
        # /about-1.html 与 /about.html 等价，规范到不带分页后缀的 URL
        return redirect(f'/{slug}.html')
    return column_detail(slug, page=page)


@frontend_bp.route('/article-<int:aid>.html')
def rewrite_article(aid):
    """伪静态：/article-123.html。"""
    if Setting.get('seo_rewrite_enable') != 'on':
        abort(404)
    article = Article.query.get_or_404(aid)
    if article.is_deleted or article.status != STATUS_PUBLISHED:
        abort(404)
    col = Column.query.get(article.column_id)
    if col is None or col.is_deleted or not col.is_enabled:
        abort(404)
    # 直接按栏目详情渲染，避免跳回动态参数 URL（伪静态的意义就在于此）
    return article_detail(col.slug, aid)


# ============================================================
# 栏目详情
# ============================================================

@frontend_bp.route('/column/<slug>')
@_try_cache('column', 'cache_ttl_column', 600)
def column_detail(slug, page=None):
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
        return render_template(
            theme_template('column_children'),
            column=col, children=children, nav=nav, seo=_seo(column=col)
        )

    # 叶子栏目
    if col.type == 'page':
        fields = col.fields.filter_by(
            is_deleted=False, is_frontend_visible=True
        ).order_by(ColumnField.sort_order.desc()).all()
        # 模块8：对单页 HTML 注入默认 ALT（在临时副本上改，避免污染 ORM identity_map 中的真实对象）
        render_col = col
        if col.page_content:
            from copy import copy as _shallow_copy
            render_col = _shallow_copy(col)
            render_col.page_content = _inject_default_alt(col.page_content)
        tpl = get_column_template(col, 'page')
        return render_template(
            theme_template(tpl),
            column=render_col, fields=fields, nav=nav, seo=_seo(column=col)
        )
    elif col.type == 'list':
        # 分页来源：伪静态路由直接传参（/about-2.html）或查询参数（/column/about?page=2）
        if page is None:
            page = request.args.get('page', 1)
        try:
            page = max(int(page), 1)
        except (TypeError, ValueError):
            page = 1
        per_page = col.page_size or 10
        pagination = Article.query.filter_by(
            column_id=col.id, is_deleted=False, status=STATUS_PUBLISHED
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


# ============================================================
# 文章详情
# ============================================================

@frontend_bp.route('/column/<slug>/article/<int:aid>')
@_try_cache('article', 'cache_ttl_article', 900)
def article_detail(slug, aid):
    col = Column.query.filter_by(slug=slug, is_deleted=False).first_or_404()
    article = Article.query.get_or_404(aid)
    if article.column_id != col.id or article.is_deleted or article.status != STATUS_PUBLISHED:
        abort(404)

    # 浏览量 +1（写库时暂时绕过缓存副作用）
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
        is_deleted=False, status=STATUS_PUBLISHED
    ).order_by(Article.published_at.desc()).limit(8).all()

    # 上一篇/下一篇
    prev_article = Article.query.filter(
        Article.column_id == col.id,
        Article.is_deleted == False,
        Article.status == STATUS_PUBLISHED,
        Article.id < article.id
    ).order_by(Article.id.desc()).first()
    next_article = Article.query.filter(
        Article.column_id == col.id,
        Article.is_deleted == False,
        Article.status == STATUS_PUBLISHED,
        Article.id > article.id
    ).order_by(Article.id.asc()).first()

    # 模块8：对正文内容、摘要注入默认图片ALT（临时副本，不污染 ORM 对象）
    from copy import copy as _shallow_copy
    render_article = _shallow_copy(article)
    if render_article.content:
        render_article.content = _inject_default_alt(article.content)
    if render_article.summary:
        render_article.summary = _inject_default_alt(article.summary)
    # v2.5.0：浅拷贝不复制 ORM 关系，需手动带上 translations 供 t() 多语言取值
    render_article.translations = article.translations

    tpl = get_column_template(col, 'detail')
    return render_template(
        theme_template(tpl),
        column=col, article=render_article, fields=fields,
        latest_articles=latest_articles,
        prev_article=prev_article, next_article=next_article,
        nav=nav, seo=_seo(article=article)
    )


# 兼容更短的 URL：/article/<aid>
@frontend_bp.route('/article/<int:aid>')
def article_short(aid):
    article = Article.query.get_or_404(aid)
    if article.is_deleted or article.status != STATUS_PUBLISHED:
        abort(404)
    return redirect(url_for('frontend.article_detail',
                            slug=article.column.slug, aid=article.id))


# ============================================================
# 验证码 / 主题静态资源 / 搜索 / 根文件
# ============================================================

@frontend_bp.route('/captcha')
def captcha():
    code, image_data = generate_captcha()
    session['form_captcha'] = code
    resp = current_app.response_class(image_data, mimetype='image/png')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@frontend_bp.route('/themes/<slug>/<path:filename>')
def theme_asset(slug, filename):
    """主题静态资源：/themes/<主题>/css、js、images、fonts 下的文件。

    主题静态资源随主题目录分发（base.html 通过 current_theme 引用）。
    安全：slug 正则校验 + 仅允许四个资源子目录 + 拒绝 .. 与反斜杠，
    send_from_directory 本身再做一层路径穿越防护。
    """
    if not THEME_SLUG_RE.match(slug or ''):
        abort(404)
    fn = (filename or '').replace('\\', '/')
    if not fn.startswith(('css/', 'js/', 'images/', 'fonts/')):
        abort(404)
    parts = [p for p in fn.split('/') if p not in ('', '.')]
    if not parts or any(p == '..' for p in parts):
        abort(404)
    theme_dir = os.path.join(THEMES_DIR, slug)
    if not os.path.isdir(theme_dir):
        abort(404)
    resp = send_from_directory(theme_dir, '/'.join(parts))
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


@frontend_bp.route('/search')
def search():
    """全站搜索（全文搜索 + 中文分词，v2.5.1 起按当前语言检索）。"""
    keyword = (request.args.get('q') or '').strip()
    page = max(int(request.args.get('page', 1)), 1)
    per_page = int(Setting.get('search_results_per_page', '20'))
    results = []
    total = 0
    if keyword:
        from ..utils.search import search_articles, build_result_url
        from ..i18n import select_locale
        results, total = search_articles(
            keyword, page=page, per_page=per_page, locale=select_locale()
        )
    # 为每个结果生成 URL（文章 → 文章详情；产品等插件内容 → 插件路由）
    for r in results:
        r['url'] = build_result_url(r)
    return render_template(
        theme_template('search'), keyword=keyword, results=results,
        total=total, page=page, per_page=per_page,
        nav=_build_nav(), seo=_seo()
    )


@frontend_bp.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(current_app.static_folder, 'img'),
        'favicon.ico', mimetype='image/vnd.microsoft.icon'
    )


@frontend_bp.route('/robots.txt')
def robots():
    """爬虫协议：默认规则 + Setting.seo_robots_custom 追加自定义规则。"""
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
    # 模块8：追加后台自定义的 robots 规则
    extra = Setting.get('seo_robots_custom') or ''
    if extra:
        lines.append('# 自定义规则（来自网站设置→SEO高级）')
        lines.append(extra.rstrip('\n'))
        lines.append('')
    return current_app.response_class(
        '\n'.join(lines), mimetype='text/plain'
    )


@frontend_bp.route('/sitemap.xml')
def sitemap():
    """站点地图：使用 Setting 配置的更新频率与优先级（栏目/文章分开）。
    只收录：首页 + 启用未删除的非外链栏目 + 启用未删除且已发布文章。
    """
    from xml.sax.saxutils import escape

    def _lastmod(dt):
        return dt.strftime('%Y-%m-%d') if dt else ''

    # 模块8：读取 Setting 自定义频率/优先级
    cfg_col_cf = Setting.get('seo_sitemap_changefreq_column') or 'weekly'
    cfg_art_cf = Setting.get('seo_sitemap_changefreq_article') or 'monthly'
    cfg_col_pri = Setting.get('seo_sitemap_priority_column') or '0.8'
    cfg_art_pri = Setting.get('seo_sitemap_priority_article') or '0.6'

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
        loc = url_for('frontend.column_detail', slug=col.slug, _external=True)
        # 模块8：伪静态开启时使用伪静态链接（可选）
        if Setting.get('seo_rewrite_enable') == 'on':
            root = request.url_root.rstrip('/')
            loc = f'{root}/{col.slug}.html'
        urls.append({
            'loc': loc,
            'lastmod': _lastmod(col.updated_at),
            'changefreq': cfg_col_cf,
            'priority': cfg_col_pri,
        })

    # 文章页
    articles = Article.query.filter(
        Article.status == STATUS_PUBLISHED,
        Article.is_deleted == False,
    ).order_by(Article.published_at.desc()).all()
    for a in articles:
        if Setting.get('seo_rewrite_enable') == 'on':
            root = request.url_root.rstrip('/')
            loc = f'{root}/article-{a.id}.html'
        else:
            loc = url_for('frontend.article_detail', slug=a.column.slug,
                          aid=a.id, _external=True)
        urls.append({
            'loc': loc,
            'lastmod': _lastmod(a.updated_at or a.published_at),
            'changefreq': cfg_art_cf,
            'priority': cfg_art_pri,
        })

    # v2.2.0：聚合启用插件贡献的 URL（轮播图无详情页、产品详情页等）
    try:
        from ..plugin_system import collect_sitemap_urls
        urls.extend(collect_sitemap_urls())
    except Exception:
        pass

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


# v2.4.0：Docker 健康检查端点（豁免初始化拦截）
@frontend_bp.route('/healthz')
def healthz():
    from sqlalchemy import text
    try:
        db.session.execute(text('SELECT 1'))
        return '{"status":"ok"}', 200, {'Content-Type': 'application/json'}
    except Exception:
        return '{"status":"error"}', 503, {'Content-Type': 'application/json'}
