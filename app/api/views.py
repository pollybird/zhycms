"""内容 API 核心端点（只读）：站点信息、栏目、文章。

约定（DESIGN-v2.2.0.md §五）：
  - 响应包：{"code":0,"message":"ok","data":...,"meta":...}
  - api_enable=off → 所有端点 404；api_token 非空 → 校验 X-API-Token（恒时比较）
  - 接口缓存 api_cache_ttl 秒（0=不缓存）；CORS 由 api_cors_origins 控制
  - 只输出前台可见数据（启用/未删除/文章已发布），不输出敏感字段
"""
import hmac
from functools import wraps

from flask import request, jsonify, current_app

from ..extensions import db
from ..models.column import Column, ColumnField
from ..models.article import Article
from ..models.setting import Setting
from ..models.workflow import STATUS_PUBLISHED
from . import api_bp


# ============================================================
# 响应与缓存工具
# ============================================================

def api_ok(data=None, meta=None):
    return jsonify({'code': 0, 'message': 'ok', 'data': data, 'meta': meta})


def api_err(code, message, http=None):
    return jsonify({'code': code, 'message': message, 'data': None, 'meta': None}), http or (
        404 if code == 404 else (401 if code == 401 else 400))


def api_cache(key_prefix):
    """接口缓存装饰器：api_cache_ttl 秒（0=关闭），key 含全参数。"""
    from ..extensions import cache

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            ttl = _int_setting('api_cache_ttl', 60)
            if ttl <= 0 or request.method != 'GET':
                return view_func(*args, **kwargs)
            cache_key = f'api/{key_prefix}/' + '/'.join(
                [str(v) for v in args] + [f'{k}={v}' for k, v in sorted(kwargs.items())]
            ) + request.query_string.decode('utf-8', errors='ignore')
            # v2.5.0：缓存键包含当前 locale，多语言内容互不串扰
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


def _int_setting(key, default):
    try:
        return int(Setting.get(key, default))
    except (TypeError, ValueError):
        return default


# ============================================================
# 全局门控（api_enable / api_token）与 CORS
# ============================================================

@api_bp.before_request
def _api_gate():
    if Setting.get('api_enable') == 'off':
        return api_err(404, '资源不存在')
    token = Setting.get('api_token') or ''
    if token:
        provided = request.headers.get('X-API-Token', '')
        if not provided or not hmac.compare_digest(token, provided):
            return api_err(401, 'API Token 无效或缺失')
    return None


def _register_cors(app):
    """按 api_cors_origins 为 /api/v1/* 追加跨域响应头（app 级 after_request）。"""

    @app.after_request
    def _add_cors(resp):
        if not request.path.startswith('/api/v1/'):
            return resp
        origins = (Setting.get('api_cors_origins') or '').strip()
        if not origins:
            return resp
        allow = origins
        origin = request.headers.get('Origin', '')
        if origins != '*' and origin:
            whitelist = [o.strip() for o in origins.split(',') if o.strip()]
            if origin in whitelist:
                allow = origin
            else:
                return resp
        resp.headers['Access-Control-Allow-Origin'] = allow
        resp.headers['Access-Control-Allow-Headers'] = 'X-API-Token, Content-Type'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        if request.method == 'OPTIONS':
            return current_app.response_class('', 204, resp.headers)
        return resp


# ============================================================
# 序列化
# ============================================================

def _abs_url(url):
    """相对路径转绝对 URL（图片等资源，便于小程序端直接使用）。"""
    if not url:
        return ''
    if url.startswith(('http://', 'https://')):
        return url
    root = request.url_root.rstrip('/')
    return f'{root}{url if url.startswith("/") else "/" + url}'


def _column_brief(col, with_children=False):
    data = {
        'id': col.id, 'name': col.name, 'slug': col.slug, 'type': col.type,
        'summary': col.summary or '',
        'sort_order': col.sort_order,
        'url': _abs_url(f'/{col.slug}.html')
        if Setting.get('seo_rewrite_enable') == 'on'
        else f'/column/{col.slug}',
    }
    if with_children:
        data['children'] = [
            _column_brief(c, with_children=True)
            for c in col.children.filter_by(is_enabled=True, is_deleted=False)
            .order_by(Column.sort_order.desc())
        ]
    return data


def _column_fields(col):
    """栏目自定义字段（前台可见）+ 当前值（单页栏目自身字段值）。"""
    fields = col.fields.filter_by(
        is_deleted=False, is_frontend_visible=True
    ).order_by(ColumnField.sort_order.desc()).all()
    result = []
    for f in fields:
        value = col.get_field_value(f.id) if hasattr(col, 'get_field_value') else ''
        item = {
            'key': f.field_key, 'label': f.label, 'type': f.field_type,
            'value': value or '',
        }
        if f.field_type in ('image', 'file') and value:
            item['url'] = _abs_url(value)
        result.append(item)
    return result


def _article_summary(a, column=None):
    col = column or a.column
    if Setting.get('seo_rewrite_enable') == 'on':
        url = _abs_url(f'/article-{a.id}.html')
    else:
        from flask import url_for
        try:
            url = url_for('frontend.article_detail', slug=col.slug, aid=a.id,
                          _external=True)
        except Exception:
            url = f'/column/{col.slug}/article/{a.id}'
    return {
        'id': a.id, 'title': a.title, 'summary': a.summary or '',
        'cover': _abs_url(a.cover or ''),
        'author': a.author or '', 'source': a.source or '',
        'published_at': a.published_at.strftime('%Y-%m-%d %H:%M:%S')
        if a.published_at else '',
        'viewed': a.viewed or 0, 'url': url,
        'column': {'id': col.id, 'name': col.name, 'slug': col.slug},
    }


def _article_detail(a, column=None):
    col = column or a.column
    data = _article_summary(a, col)
    data.update({
        'content': a.content or '',
        'seo': {
            'title': a.seo_title or a.title,
            'keywords': a.seo_keywords or '',
            'description': a.seo_description or a.summary or '',
        },
        'fields': [
            {'key': f.field_key, 'label': f.label, 'type': f.field_type,
             'value': a.get_field_value(f.id) or ''}
            for f in col.fields.filter_by(is_deleted=False, is_frontend_visible=True)
            .order_by(ColumnField.sort_order.desc()).all()
        ],
    })
    return data


def _article_query(column_id):
    return Article.query.filter(
        Article.column_id == column_id,
        Article.is_deleted == False,  # noqa: E712
        Article.status == STATUS_PUBLISHED,
    ).order_by(Article.sort_order.desc(), Article.published_at.desc())


def _pagination_meta(pagination):
    return {
        'page': pagination.page, 'per_page': pagination.per_page,
        'total': pagination.total, 'total_pages': pagination.pages,
    }


def _get_enabled_column(slug):
    col = Column.query.filter_by(slug=slug, is_deleted=False).first()
    if col is None or not col.is_enabled or col.type == 'link':
        return None
    return col


# ============================================================
# 核心端点
# ============================================================

@api_bp.route('/site')
@api_cache('site')
def site_info():
    s = Setting.get_dict()
    root_columns = Column.query.filter_by(
        parent_id=None, is_enabled=True, is_deleted=False
    ).order_by(Column.sort_order.desc()).all()
    return api_ok({
        'name': s.get('site_name', ''),
        'subtitle': s.get('site_subtitle', ''),
        'logo': _abs_url(s.get('site_logo', '')),
        'copyright': s.get('footer_copyright', ''),
        'seo': {
            'title': s.get('seo_title', ''),
            'keywords': s.get('seo_keywords', ''),
            'description': s.get('seo_description', ''),
        },
        'nav': [_column_brief(c, with_children=True) for c in root_columns],
    })


@api_bp.route('/columns')
@api_cache('columns')
def columns_index():
    if request.args.get('tree') == '1':
        roots = Column.query.filter_by(
            parent_id=None, is_enabled=True, is_deleted=False
        ).order_by(Column.sort_order.desc()).all()
        return api_ok([_column_brief(c, with_children=True) for c in roots])

    q = Column.query.filter(Column.is_enabled == True,  # noqa: E712
                            Column.is_deleted == False)  # noqa: E712
    parent_id = request.args.get('parent_id')
    if parent_id is not None and parent_id != '':
        q = q.filter(Column.parent_id == parent_id)
    col_type = request.args.get('type')
    if col_type in ('page', 'list', 'link'):
        q = q.filter(Column.type == col_type)
    items = q.order_by(Column.sort_order.desc()).all()
    return api_ok([_column_brief(c) for c in items])


@api_bp.route('/columns/<slug>')
@api_cache('column')
def column_detail(slug):
    col = _get_enabled_column(slug)
    if col is None:
        return api_err(404, '栏目不存在')
    data = _column_brief(col)
    data['seo'] = {
        'title': col.seo_title or col.name,
        'keywords': col.seo_keywords or '',
        'description': col.seo_description or col.summary or '',
    }
    if col.type == 'page':
        data['page_content'] = col.page_content or ''
        data['fields'] = _column_fields(col)
    return api_ok(data)


@api_bp.route('/columns/<slug>/articles')
@api_cache('column_articles')
def column_articles(slug):
    col = _get_enabled_column(slug)
    if col is None:
        return api_err(404, '栏目不存在')

    # 含子栏目文章
    col_ids = [col.id]
    for child in col.children.filter_by(is_enabled=True, is_deleted=False).all():
        col_ids.append(child.id)

    page = max(_to_int(request.args.get('page'), 1), 1)
    per_page = min(max(_to_int(request.args.get('per_page'), 10), 1), 50)
    q = _article_query(col.id)
    if len(col_ids) > 1:
        q = Article.query.filter(
            Article.column_id.in_(col_ids),
            Article.is_deleted == False,  # noqa: E712
            Article.status == STATUS_PUBLISHED,
        ).order_by(Article.sort_order.desc(), Article.published_at.desc())
    keyword = (request.args.get('keyword') or '').strip()
    if keyword:
        q = q.filter(Article.title.like(f'%{keyword}%'))
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    return api_ok(
        [_article_summary(a) for a in pagination.items],
        meta=_pagination_meta(pagination),
    )


@api_bp.route('/articles/<int:aid>')
@api_cache('article')
def article_detail(aid):
    a = db.session.get(Article, aid)
    if a is None or a.is_deleted or a.status != STATUS_PUBLISHED:
        return api_err(404, '文章不存在')
    col = a.column
    if col is None or col.is_deleted or not col.is_enabled:
        return api_err(404, '文章不存在')

    data = _article_detail(a, col)
    prev_a = _article_query(col.id).filter(Article.id < a.id) \
        .order_by(Article.id.desc()).first()
    next_a = _article_query(col.id).filter(Article.id > a.id) \
        .order_by(Article.id.asc()).first()
    data['prev'] = {'id': prev_a.id, 'title': prev_a.title} if prev_a else None
    data['next'] = {'id': next_a.id, 'title': next_a.title} if next_a else None
    return api_ok(data)


def _to_int(val, default):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default
