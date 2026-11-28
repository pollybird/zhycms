"""内容 API 写端点与扩展只读端点（v3.2.11）。

写端点默认关闭（``api_write_enable=off``），仅接受 Bearer JWT；
所有写操作复用后台服务层并落审计日志，站点取请求解析结果，
禁止请求体指定 ``site_id``。
"""
from datetime import date

from flask import g, request
from werkzeug.datastructures import MultiDict

from ..constants import Workflow as _W
from ..extensions import db, limiter
from ..models.article import Article
from ..models.column import Column, ColumnField
from ..models.fragment import Fragment
from ..models.setting import Setting
from ..services.article_service import save_article
from ..services.column_service import save_column
from ..sites import current_site_id
from ..utils.helpers import audit_log
from ..utils.search import reindex_article, unindex_article
from . import api_bp
from .openapi import openapi_doc
from .views import active_user_for_identity, api_err, api_ok, _check_jwt

_FRAGMENT_TYPES = frozenset({
    'text', 'textarea', 'richtext', 'image', 'url', 'number', 'file',
})


def _write_limit():
    return f"{Setting.get('api_rate_limit_write', '30')} per minute"


def _write_key():
    return f"{getattr(g, 'api_identity', 'anonymous')}:{request.remote_addr}"


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _form_data(payload, fields=()):
    """把 JSON 转为服务层期望的表单映射（布尔转 on/空串）。

    自定义字段按 ``fields`` 的 field_key（或直接写字段 id）映射为
    ``field_<id>``，与后台表单命名保持一致。
    """
    form = MultiDict()
    for key, value in payload.items():
        if isinstance(value, bool):
            form[key] = 'on' if value else ''
        elif isinstance(value, (str, int, float)) or value is None:
            form[key] = '' if value is None else str(value)
    values = payload.get('fields')
    if isinstance(values, dict):
        by_key = {f.field_key: f.id for f in fields}
        for key, value in values.items():
            fid = by_key.get(key)
            if fid is None and str(key).isdigit():
                fid = int(key)
            if fid is None:
                continue
            form[f'field_{fid}'] = '' if value is None else str(value)
    return form


def _column_form(payload, column=None):
    """构造 save_column 需要的表单映射。

    ``save_column`` 面向后台表单，用 ``getlist`` 读取自定义字段数组；
    因此这里必须返回 MultiDict。更新时额外回填 API 未暴露的子资源
    （字段配置、单页字段值、翻译、模板等），避免 PUT 把它们清空。
    """
    form = _form_data(payload)
    if column is not None:
        fields = column.fields.filter_by(is_deleted=False).order_by(
            ColumnField.sort_order.asc()).all()
        for i, f in enumerate(fields):
            form.add('field_id[]', str(f.id))
            form.add('field_key[]', f.field_key)
            form.add('field_label[]', f.label)
            form.add('field_type[]', f.field_type)
            form.add('field_required[]', str(i) if f.is_required else '')
            form.add('field_visible[]', str(i) if f.is_frontend_visible else '')
            form.add('field_exts[]', f.allowed_exts or '')
            form.add('field_maxsize[]',
                     str(f.max_size // 1024) if f.max_size else '')
            value = column.get_field_value(f.id) or ''
            if f.field_type in ('image', 'file'):
                form[f'field_{f.id}_existing'] = value
            else:
                form[f'field_{f.id}'] = value

        if column.type == 'page':
            for key, val in (
                ('page_content', column.page_content or ''),
                ('page_content_format', column.page_content_format or 'html'),
                ('page_content_md', column.page_content_md or ''),
            ):
                if key not in form:
                    form[key] = val
        for tr in column.translations:
            for key, val in (
                ('name', tr.name or ''),
                ('summary', tr.summary or ''),
                ('page_content', tr.page_content or ''),
                ('page_content_format', tr.page_content_format or 'html'),
                ('page_content_md', tr.page_content_md or ''),
                ('seo_title', tr.seo_title or ''),
                ('seo_keywords', tr.seo_keywords or ''),
                ('seo_description', tr.seo_description or ''),
            ):
                name = f'{key}_{tr.locale}'
                if name not in form:
                    form[name] = val

        for key, val in (
            ('parent_mode', column.parent_mode),
            ('list_template', column.list_template or ''),
            ('detail_template', column.detail_template or ''),
            ('page_template', column.page_template or ''),
            ('page_size', column.page_size),
            ('link_url', column.link_url or ''),
            ('link_target', column.link_target or '_self'),
            ('member_only', 'on' if column.member_only else ''),
        ):
            if key not in form and val is not None:
                form[key] = str(val)

    if 'is_enabled' not in form:
        # 后台表单未勾选即关闭；API 新建默认启用，更新则沿用原状态
        form['is_enabled'] = 'on' if column is None or column.is_enabled else ''
    return form


def _apply_cover(article, payload):
    """JSON 请求无文件上传，封面按字符串 URL 写入。"""
    if 'cover' in payload:
        article.cover = str(payload.get('cover') or '').strip() or None
        db.session.commit()


def _current_writer():
    _check_jwt()
    user = active_user_for_identity(getattr(g, 'api_identity', None))
    if user is None:
        return None
    return user


def _deny(user, permission, column=None):
    if user.is_super:
        return False
    if not user.has_permission(permission, site_id=current_site_id()):
        return True
    if column is not None and not user.can_access_column(column.id):
        return True
    return False


def _find_column(column_id):
    try:
        column_id = int(column_id)
    except (TypeError, ValueError):
        return None
    return Column.query.filter_by(
        id=column_id, site_id=current_site_id(), is_deleted=False).first()


def _find_article(article_id):
    try:
        article_id = int(article_id)
    except (TypeError, ValueError):
        return None
    return Article.query.filter_by(
        id=article_id, site_id=current_site_id(), is_deleted=False).first()


def _article_payload(article):
    return {
        'id': article.id,
        'title': article.title,
        'column_id': article.column_id,
        'status': article.status,
        'summary': article.summary,
        'cover': article.cover,
        'published_at': article.published_at.isoformat() if article.published_at else None,
    }


# ---------------------------------------------------------------------------
# 文章
# ---------------------------------------------------------------------------

@api_bp.route('/articles', methods=['POST'])
@limiter.limit(_write_limit, key_func=_write_key)
@openapi_doc(
    '创建文章（默认草稿）', tags=['content'], auth='jwt', write=True,
    body={'type': 'object', 'required': ['column_id', 'title'], 'properties': {
        'column_id': {'type': 'integer'},
        'title': {'type': 'string'},
        'summary': {'type': 'string'},
        'content': {'type': 'string'},
        'status': {'type': 'string',
                   'enum': [_W.STATUS_DRAFT, _W.STATUS_REVIEW,
                            _W.STATUS_PUBLISHED, _W.STATUS_ARCHIVED]},
        'author': {'type': 'string'},
        'source': {'type': 'string'},
        'cover': {'type': 'string'},
        'seo_title': {'type': 'string'},
        'seo_keywords': {'type': 'string'},
        'seo_description': {'type': 'string'},
        'fields': {'type': 'object'},
    }},
)
def create_article():
    user = _current_writer()
    if user is None:
        return api_err(401, '账号不可用或令牌已失效')
    payload = _json_body()
    column = _find_column(payload.get('column_id'))
    if column is None:
        return api_err(404, '栏目不存在')
    if _deny(user, 'content:create', column):
        return api_err(403, '无权在该栏目创建内容')
    if payload.get('status') == _W.STATUS_PUBLISHED and not (
            user.is_super or user.column_flag('can_publish', column.id)):
        return api_err(403, '无发布权限')

    fields = column.fields.filter_by(is_deleted=False).all()
    article, messages = save_article(
        None, column, fields,
        form_data=_form_data(payload, fields), files_data={}, current_user=user)
    if article is None:
        return api_err(400, '；'.join(m for _c, m in messages) or '创建失败')
    _apply_cover(article, payload)

    if article.status == _W.STATUS_PUBLISHED:
        reindex_article(article.id)
    return api_ok(_article_payload(article))


@api_bp.route('/articles/<int:article_id>', methods=['PUT'])
@limiter.limit(_write_limit, key_func=_write_key)
@openapi_doc(
    '更新文章', tags=['content'], auth='jwt', write=True,
    params=[{'name': 'article_id', 'in': 'path', 'required': True,
             'schema': {'type': 'integer'}}],
    body={'type': 'object', 'required': ['title'], 'properties': {
        'column_id': {'type': 'integer'},
        'title': {'type': 'string'},
        'summary': {'type': 'string'},
        'content': {'type': 'string'},
        'status': {'type': 'string',
                   'enum': [_W.STATUS_DRAFT, _W.STATUS_REVIEW,
                            _W.STATUS_PUBLISHED, _W.STATUS_ARCHIVED]},
        'author': {'type': 'string'},
        'source': {'type': 'string'},
        'cover': {'type': 'string'},
        'seo_title': {'type': 'string'},
        'seo_keywords': {'type': 'string'},
        'seo_description': {'type': 'string'},
        'fields': {'type': 'object'},
    }},
)
def update_article(article_id):
    user = _current_writer()
    if user is None:
        return api_err(401, '账号不可用或令牌已失效')
    article = _find_article(article_id)
    if article is None:
        return api_err(404, '文章不存在')
    column = _find_column(article.column_id)
    if _deny(user, 'content:edit', column):
        return api_err(403, '无权编辑该内容')

    payload = _json_body()
    target = _find_column(payload['column_id']) if payload.get('column_id') else column
    if target is None:
        return api_err(404, '目标栏目不存在')
    if target.id != column.id and _deny(user, 'content:edit', target):
        return api_err(403, '无权操作目标栏目')

    if payload.get('status') == _W.STATUS_PUBLISHED and not (
            user.is_super or user.column_flag('can_publish', target.id)):
        return api_err(403, '无发布权限')

    fields = target.fields.filter_by(is_deleted=False).all()
    updated, messages = save_article(
        article, target, fields,
        form_data=_form_data(payload, fields), files_data={}, current_user=user)
    if updated is None:
        return api_err(400, '；'.join(m for _c, m in messages) or '更新失败')
    _apply_cover(updated, payload)

    if updated.status == _W.STATUS_PUBLISHED:
        reindex_article(updated.id)
    else:
        unindex_article(updated.id)
    return api_ok(_article_payload(updated))


@api_bp.route('/articles/<int:article_id>', methods=['DELETE'])
@limiter.limit(_write_limit, key_func=_write_key)
@openapi_doc(
    '删除文章（软删除）', tags=['content'], auth='jwt', write=True,
    params=[{'name': 'article_id', 'in': 'path', 'required': True,
             'schema': {'type': 'integer'}}],
)
def delete_article(article_id):
    user = _current_writer()
    if user is None:
        return api_err(401, '账号不可用或令牌已失效')
    article = _find_article(article_id)
    if article is None:
        return api_err(404, '文章不存在')
    column = _find_column(article.column_id)
    if _deny(user, 'content:delete', column):
        return api_err(403, '无权删除该内容')

    article.is_deleted = True
    article.is_enabled = False
    db.session.commit()
    unindex_article(article.id)
    audit_log('delete', 'article', article.id, article.title,
              {'via': 'api', 'site_id': article.site_id})
    return api_ok({'id': article.id})


# ---------------------------------------------------------------------------
# 栏目
# ---------------------------------------------------------------------------

@api_bp.route('/columns', methods=['POST'])
@limiter.limit(_write_limit, key_func=_write_key)
@openapi_doc(
    '创建栏目', tags=['content'], auth='jwt', write=True,
    body={'type': 'object', 'required': ['name', 'slug'], 'properties': {
        'name': {'type': 'string'},
        'slug': {'type': 'string'},
        'type': {'type': 'string', 'enum': ['list', 'page', 'link']},
        'parent_id': {'type': 'integer', 'nullable': True},
        'summary': {'type': 'string'},
        'sort_order': {'type': 'integer'},
        'is_enabled': {'type': 'boolean'},
    }},
)
def create_column():
    user = _current_writer()
    if user is None:
        return api_err(401, '账号不可用或令牌已失效')
    if _deny(user, 'column:manage'):
        return api_err(403, '无栏目管理权限')

    form = _column_form(_json_body())
    column, messages = save_column(None, form_data=form, files_data={})
    if column is None:
        return api_err(400, '；'.join(m for _c, m in messages) or '创建失败')
    return api_ok({'id': column.id, 'name': column.name, 'slug': column.slug})


@api_bp.route('/columns/<int:column_id>', methods=['PUT'])
@limiter.limit(_write_limit, key_func=_write_key)
@openapi_doc(
    '更新栏目', tags=['content'], auth='jwt', write=True,
    params=[{'name': 'column_id', 'in': 'path', 'required': True,
             'schema': {'type': 'integer'}}],
    body={'type': 'object', 'required': ['name', 'slug'], 'properties': {
        'name': {'type': 'string'},
        'slug': {'type': 'string'},
        'type': {'type': 'string', 'enum': ['list', 'page', 'link']},
        'parent_id': {'type': 'integer', 'nullable': True},
        'summary': {'type': 'string'},
        'sort_order': {'type': 'integer'},
        'is_enabled': {'type': 'boolean'},
        'seo_title': {'type': 'string'},
        'seo_keywords': {'type': 'string'},
        'seo_description': {'type': 'string'},
    }},
)
def update_column(column_id):
    user = _current_writer()
    if user is None:
        return api_err(401, '账号不可用或令牌已失效')
    if _deny(user, 'column:manage'):
        return api_err(403, '无栏目管理权限')
    column = Column.query.filter_by(
        id=column_id, site_id=current_site_id(), is_deleted=False).first()
    if column is None:
        return api_err(404, '栏目不存在')

    form = _column_form(_json_body(), column)
    updated, messages = save_column(
        column, form_data=form, files_data={})
    if updated is None:
        return api_err(400, '；'.join(m for _c, m in messages) or '更新失败')
    return api_ok({'id': updated.id, 'name': updated.name, 'slug': updated.slug})


@api_bp.route('/columns/<int:column_id>', methods=['DELETE'])
@limiter.limit(_write_limit, key_func=_write_key)
@openapi_doc(
    '删除栏目', tags=['content'], auth='jwt', write=True,
    params=[{'name': 'column_id', 'in': 'path', 'required': True,
             'schema': {'type': 'integer'}}],
)
def delete_column(column_id):
    user = _current_writer()
    if user is None:
        return api_err(401, '账号不可用或令牌已失效')
    if _deny(user, 'column:manage'):
        return api_err(403, '无栏目管理权限')
    column = Column.query.filter_by(
        id=column_id, site_id=current_site_id(), is_deleted=False).first()
    if column is None:
        return api_err(404, '栏目不存在')

    sid = column.site_id
    child = Column.query.filter_by(
        parent_id=column.id, site_id=sid, is_deleted=False).first()
    article = Article.query.filter_by(
        column_id=column.id, site_id=sid, is_deleted=False).first()
    if child or article:
        return api_err(409, '栏目下仍有子栏目或内容，无法删除')

    column.is_deleted = True
    db.session.commit()
    audit_log('delete', 'column', column.id, column.name,
              {'via': 'api', 'site_id': sid})
    return api_ok({'id': column.id})


# ---------------------------------------------------------------------------
# 碎片
# ---------------------------------------------------------------------------

@api_bp.route('/fragments', methods=['POST'])
@limiter.limit(_write_limit, key_func=_write_key)
@openapi_doc(
    '创建碎片', tags=['content'], auth='jwt', write=True,
    body={'type': 'object', 'required': ['name', 'slug'], 'properties': {
        'name': {'type': 'string'},
        'slug': {'type': 'string'},
        'field_type': {'type': 'string',
                       'enum': ['text', 'textarea', 'richtext', 'image', 'url',
                                'number', 'file']},
        'value': {'type': 'string'},
    }},
)
def create_fragment():
    user = _current_writer()
    if user is None:
        return api_err(401, '账号不可用或令牌已失效')
    if _deny(user, 'system:settings'):
        return api_err(403, '无碎片管理权限')

    payload = _json_body()
    name = str(payload.get('name') or '').strip()
    slug = str(payload.get('slug') or '').strip().lower()
    if not name or not slug:
        return api_err(400, '名称与标识必填')
    field_type = str(payload.get('field_type') or 'text')
    if field_type not in _FRAGMENT_TYPES:
        return api_err(400, '碎片类型无效')
    sid = current_site_id()
    exists = Fragment.query.filter_by(slug=slug, site_id=sid, is_deleted=False).first()
    if exists:
        return api_err(409, '碎片标识已存在')

    fragment = Fragment(
        name=name, slug=slug, site_id=sid, field_type=field_type,
        value=str(payload.get('value', payload.get('content')) or ''))
    db.session.add(fragment)
    db.session.commit()
    audit_log('create', 'fragment', fragment.id, fragment.name,
              {'via': 'api', 'site_id': sid})
    return api_ok({'id': fragment.id, 'name': fragment.name, 'slug': fragment.slug})


@api_bp.route('/fragments/<int:fragment_id>', methods=['PUT'])
@limiter.limit(_write_limit, key_func=_write_key)
@openapi_doc(
    '更新碎片', tags=['content'], auth='jwt', write=True,
    params=[{'name': 'fragment_id', 'in': 'path', 'required': True,
             'schema': {'type': 'integer'}}],
)
def update_fragment(fragment_id):
    user = _current_writer()
    if user is None:
        return api_err(401, '账号不可用或令牌已失效')
    if _deny(user, 'system:settings'):
        return api_err(403, '无碎片管理权限')
    fragment = Fragment.query.filter_by(
        id=fragment_id, site_id=current_site_id(), is_deleted=False).first()
    if fragment is None:
        return api_err(404, '碎片不存在')

    payload = _json_body()
    if 'name' in payload:
        fragment.name = str(payload['name']).strip()
    if 'value' in payload or 'content' in payload:
        fragment.value = str(payload.get('value', payload.get('content')) or '')
    db.session.commit()
    audit_log('update', 'fragment', fragment.id, fragment.name,
              {'via': 'api', 'site_id': fragment.site_id})
    return api_ok({'id': fragment.id, 'name': fragment.name})


@api_bp.route('/fragments/<int:fragment_id>', methods=['DELETE'])
@limiter.limit(_write_limit, key_func=_write_key)
@openapi_doc(
    '删除碎片', tags=['content'], auth='jwt', write=True,
    params=[{'name': 'fragment_id', 'in': 'path', 'required': True,
             'schema': {'type': 'integer'}}],
)
def delete_fragment(fragment_id):
    user = _current_writer()
    if user is None:
        return api_err(401, '账号不可用或令牌已失效')
    if _deny(user, 'system:settings'):
        return api_err(403, '无碎片管理权限')
    fragment = Fragment.query.filter_by(
        id=fragment_id, site_id=current_site_id(), is_deleted=False).first()
    if fragment is None:
        return api_err(404, '碎片不存在')

    fragment.is_deleted = True
    db.session.commit()
    audit_log('delete', 'fragment', fragment.id, fragment.name,
              {'via': 'api', 'site_id': fragment.site_id})
    return api_ok({'id': fragment.id})


# ---------------------------------------------------------------------------
# 表单提交与站点计量（只读）
# ---------------------------------------------------------------------------

@api_bp.route('/forms/<slug>/submissions')
@openapi_doc(
    '表单提交列表', tags=['forms'], auth='jwt',
    params=[
        {'name': 'slug', 'in': 'path', 'required': True, 'schema': {'type': 'string'}},
        {'name': 'page', 'in': 'query', 'schema': {'type': 'integer'}},
        {'name': 'per_page', 'in': 'query', 'schema': {'type': 'integer'}},
    ],
)
def form_submissions(slug):
    user = _current_writer()
    if user is None:
        return api_err(401, '账号不可用或令牌已失效')
    if not (user.is_super or user.has_permission('form:view', site_id=current_site_id())):
        return api_err(403, '无表单查看权限')

    from plugins.form.models import Form, FormSubmission

    form = Form.query.filter_by(
        slug=slug, site_id=current_site_id(), is_deleted=False).first()
    if form is None:
        return api_err(404, '表单不存在')

    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(100, max(1, request.args.get('per_page', 20, type=int)))
    pagination = FormSubmission.query.filter_by(
        form_id=form.id, is_deleted=False).order_by(
        FormSubmission.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False)
    items = [{
        'id': s.id,
        'created_at': s.created_at.isoformat() if s.created_at else None,
        'is_read': s.is_read,
        'values': [{'field_id': v.field_id, 'value': v.value} for v in s.values],
    } for s in pagination.items]
    return api_ok(items, meta={
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'total_pages': pagination.pages,
    })


@api_bp.route('/sites')
@openapi_doc('站点列表（超管）', tags=['sites'], auth='jwt')
def sites_index():
    user = _current_writer()
    if user is None:
        return api_err(401, '账号不可用或令牌已失效')
    if not user.is_super:
        return api_err(403, '仅超级管理员可访问')

    from ..models.site import Site

    items = [{
        'id': s.id,
        'name': s.name,
        'domain': s.domain,
        'domains': [row.domain for row in (s.domain_entries or [])],
        'subdomain': s.subdomain,
        'status': s.status,
    } for s in Site.query.order_by(Site.id.asc()).all()]
    return api_ok(items)


@api_bp.route('/sites/<int:site_id>/metrics')
@openapi_doc(
    '站点资源计量（超管）', tags=['sites'], auth='jwt',
    params=[{'name': 'site_id', 'in': 'path', 'required': True,
             'schema': {'type': 'integer'}}],
)
def site_metrics(site_id):
    user = _current_writer()
    if user is None:
        return api_err(401, '账号不可用或令牌已失效')
    if not user.is_super:
        return api_err(403, '仅超级管理员可访问')

    from ..models.site import Site
    from ..models.site_metric import SiteMetricSnapshot

    if db.session.get(Site, site_id) is None:
        return api_err(404, '站点不存在')
    items = [{
        'date': row.date.isoformat() if isinstance(row.date, date) else row.date,
        'article_count': row.article_count,
        'view_count': row.view_count,
        'cache_entries': row.cache_entries,
        'disk_bytes': row.disk_bytes,
    } for row in SiteMetricSnapshot.query.filter_by(
        site_id=site_id).order_by(SiteMetricSnapshot.date.desc()).limit(30).all()]
    return api_ok(items)
