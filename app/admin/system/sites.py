"""v3.2.0 站群：站点管理（列表 / 新增 / 编辑 / 删除 / 后台切换）。

权限点：`site:manage`（超管与审核员默认拥有）。
约束：
  - 默认站点 id=0 不可删除、不可改为非默认；
  - slug / domain / subdomain 全局唯一（保存前校验）；
  - 站点下仍有栏目时禁止删除，需先清空内容；
  - 所有变更写审计日志（MODULE_SITE）。
"""
import re

from flask import (render_template, redirect, url_for, request, flash, session,
                   current_app)
from flask_babel import gettext as _gettext
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from ...extensions import db, cache
from ...models.site import Site, DEFAULT_SITE_ID
from ...models.column import Column
from ...models.article import Article
from ...models.fragment import Fragment
from ...models.audit import OP_CREATE, OP_UPDATE, OP_DELETE, MODULE_SITE
from ...utils.helpers import permission_required, audit_log
from ...utils.themes import list_theme_records
from ...sites import SESSION_KEY, invalidate_site_cache, can_access_site, current_site_id
from .. import admin_bp

SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{1,49}$')
SUBDOMAIN_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')

# 删除站点前检查的插件内容表（存在且有 site_id 时计数）
_PLUGIN_SITE_TABLES = (
    ('表单', 'forms'), ('友情链接', 'friend_links'), ('产品', 'products'),
    ('招聘职位', 'recruit_jobs'), ('轮播组', 'banner_groups'),
    ('轮播图', 'banners'), ('会员', 'members'),
    # v3.2.2：教程、页面构建、上传索引、第三方绑定
    ('教程分类', 'tutorial_categories'), ('教程', 'tutorials'),
    ('页面构建', 'builder_pages'), ('上传文件', 'uploaded_files'),
    ('第三方绑定', 'member_oauths'),
)


def _theme_slugs():
    try:
        return [r['slug'] for r in list_theme_records()]
    except (OSError, ValueError) as e:
        current_app.logger.warning('读取主题列表失败，站点表单仅保留全局主题：%s', e)
        return []


def _clean(value):
    return (value or '').strip()


def _validate(data, site=None):
    """校验站点表单，返回 (errors: list, cleaned: dict)。"""
    errors = []
    name = _clean(data.get('name'))
    slug = _clean(data.get('slug')).lower()
    domain = Site.normalize_host(data.get('domain'))
    subdomain = Site.normalize_host(data.get('subdomain'))
    status = _clean(data.get('status')) or 'open'
    theme = _clean(data.get('theme'))

    if not name:
        errors.append(_gettext('站点名称不能为空'))
    if not SLUG_RE.match(slug):
        errors.append(_gettext('站点标识只能包含小写字母/数字/连字符/下划线，长度 2-50 位'))
    if domain and not Site.is_valid_domain(domain):
        errors.append(_gettext('域名格式不合法（示例：www.example.com）'))
    if subdomain and not SUBDOMAIN_RE.match(subdomain):
        errors.append(_gettext('子域标签格式不合法（示例：news）'))
    if status not in ('open', 'closed'):
        status = 'open'
    if theme and theme not in _theme_slugs():
        errors.append(_gettext('主题目录不存在：themes/{}').format(theme))

    # v3.2.1：sort_order 表单层解析，非法值给出提示并兜底 0（不再延迟到 DB 报错）
    sort_raw = _clean(data.get('sort_order'))
    try:
        sort_order = int(sort_raw) if sort_raw else 0
    except ValueError:
        errors.append(_gettext('排序值必须为整数'))
        sort_order = 0

    # 唯一性校验（排除自身）
    if slug:
        q = Site.query.filter_by(slug=slug)
        if site is not None:
            q = q.filter(Site.id != site.id)
        if q.first() is not None:
            errors.append(_gettext('站点标识已被占用：{}').format(slug))
    if domain:
        q = Site.query.filter_by(domain=domain)
        if site is not None:
            q = q.filter(Site.id != site.id)
        if q.first() is not None:
            errors.append(_gettext('域名已被占用：{}').format(domain))
    if subdomain:
        q = Site.query.filter_by(subdomain=subdomain)
        if site is not None:
            q = q.filter(Site.id != site.id)
        if q.first() is not None:
            errors.append(_gettext('子域标签已被占用：{}').format(subdomain))

    cleaned = {
        'name': name,
        'slug': slug,
        'domain': domain or None,
        'subdomain': subdomain or None,
        'status': status,
        'theme': theme or None,
        'seo_title': _clean(data.get('seo_title'))[:255] or None,
        'seo_keywords': _clean(data.get('seo_keywords'))[:255] or None,
        'seo_description': _clean(data.get('seo_description'))[:500] or None,
        'sort_order': sort_order,
    }
    return errors, cleaned


def _invalidate_all():
    """站点变更后：失效请求级站点缓存 + 清前台整页缓存。"""
    invalidate_site_cache()
    try:
        cache.clear()
    except Exception as e:
        current_app.logger.warning('站点变更后清空前台缓存失败：%s', e)


def _site_content_counts(site_id):
    """统计站点下的内容量（核心内容 + 已安装插件的 site_id 表）。

    删除站点前用于拦截，避免软删除站点后留下无法访问的孤儿内容。
    """
    counts = {}
    try:
        for label, model in (('栏目', Column), ('文章', Article), ('碎片', Fragment)):
            n = db.session.query(model).filter(model.site_id == site_id).count()
            if n:
                counts[label] = n
        insp = inspect(db.engine)
        for label, table in _PLUGIN_SITE_TABLES:
            if not insp.has_table(table):
                continue
            try:
                n = db.session.execute(
                    text(f'SELECT COUNT(*) FROM {table} WHERE site_id = :sid'),
                    {'sid': site_id}).scalar()
            except SQLAlchemyError:
                # 旧版插件表尚未迁移出 site_id：跳过该表，不影响其余统计
                continue
            if n:
                counts[label] = n
    except SQLAlchemyError as e:
        current_app.logger.warning('统计站点 %s 内容量失败：%s', site_id, e)
        return {}
    return counts


@admin_bp.route('/sites')
@permission_required('site:manage')
def site_index():
    sites = Site.query.filter_by(is_deleted=False).order_by(
        Site.sort_order.desc(), Site.id.asc()).all()
    # 各站点内容量（用于删除前提示）
    counts = {}
    try:
        for sid, cnt in db.session.query(
                Column.site_id, db.func.count(Column.id)).filter(
                Column.is_deleted == False).group_by(Column.site_id).all():  # noqa: E712
            counts[sid] = cnt
    except SQLAlchemyError as e:
        current_app.logger.warning('统计站点栏目数失败，删除提示将不含内容量：%s', e)
        counts = {}
    return render_template('admin/system/sites.html', sites=sites,
                           counts=counts, current_site_id=current_site_id())


@admin_bp.route('/sites/create', methods=['GET', 'POST'])
@permission_required('site:manage')
def site_create():
    if request.method == 'POST':
        errors, data = _validate(request.form)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('admin/system/site_form.html', site=None,
                                   form=request.form, themes=_theme_slugs())
        site = Site(is_default=False)
        for k, v in data.items():
            setattr(site, k, v)
        db.session.add(site)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(_gettext('创建站点失败：{}').format(e), 'danger')
            return render_template('admin/system/site_form.html', site=None,
                                   form=request.form, themes=_theme_slugs())
        _invalidate_all()
        audit_log(OP_CREATE, MODULE_SITE, target_id=site.id, target_name=site.name,
                  detail={'slug': site.slug, 'domain': site.domain,
                          'subdomain': site.subdomain})
        flash(_gettext('站点「{}」创建成功').format(site.name), 'success')
        return redirect(url_for('admin.site_index'))

    return render_template('admin/system/site_form.html', site=None,
                           form={}, themes=_theme_slugs())


@admin_bp.route('/sites/<int:sid>/edit', methods=['GET', 'POST'])
@permission_required('site:manage')
def site_edit(sid):
    site = Site.query.filter_by(id=sid, is_deleted=False).first_or_404()
    if request.method == 'POST':
        errors, data = _validate(request.form, site=site)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('admin/system/site_form.html', site=site,
                                   form=request.form, themes=_theme_slugs())
        for k, v in data.items():
            setattr(site, k, v)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(_gettext('保存站点失败：{}').format(e), 'danger')
            return render_template('admin/system/site_form.html', site=site,
                                   form=request.form, themes=_theme_slugs())
        _invalidate_all()
        audit_log(OP_UPDATE, MODULE_SITE, target_id=site.id, target_name=site.name,
                  detail={'slug': site.slug, 'domain': site.domain,
                          'subdomain': site.subdomain, 'status': site.status,
                          'theme': site.theme})
        flash(_gettext('站点「{}」已保存').format(site.name), 'success')
        return redirect(url_for('admin.site_index'))

    return render_template('admin/system/site_form.html', site=site,
                           form={}, themes=_theme_slugs())


@admin_bp.route('/sites/<int:sid>/delete', methods=['POST'])
@permission_required('site:manage')
def site_delete(sid):
    site = Site.query.filter_by(id=sid, is_deleted=False).first_or_404()
    if site.id == DEFAULT_SITE_ID or site.is_default:
        flash(_gettext('默认站点不可删除'), 'danger')
        return redirect(url_for('admin.site_index'))
    # v3.2.1：删除前检查全部内容（栏目/文章/碎片/插件内容），避免留下孤儿数据
    counts = _site_content_counts(site.id)
    if counts:
        detail = '、'.join(f'{k} {v} 条' for k, v in counts.items())
        flash(_gettext('该站点下仍有内容（{}），请先清空后再删除站点').format(detail),
              'danger')
        return redirect(url_for('admin.site_index'))

    site.is_deleted = True
    site.status = 'closed'
    db.session.commit()
    _invalidate_all()
    if session.get(SESSION_KEY) == site.id:
        session.pop(SESSION_KEY, None)
    audit_log(OP_DELETE, MODULE_SITE, target_id=site.id, target_name=site.name,
              detail={'slug': site.slug, 'domain': site.domain})
    flash(_gettext('站点「{}」已删除（软删除）').format(site.name), 'success')
    return redirect(url_for('admin.site_index'))


@admin_bp.route('/sites/switch', methods=['POST'])
def site_switch():
    """后台切换当前站点：写 session['admin_site_id'] 后回到来源页。"""
    from flask_login import current_user
    raw = request.form.get('site_id') or request.args.get('site_id')
    try:
        sid = int(raw)
    except (TypeError, ValueError):
        flash(_gettext('站点参数不合法'), 'danger')
        return redirect(request.referrer or url_for('admin.dashboard'))
    site = Site.query.filter_by(id=sid, is_deleted=False).first()
    if site is None:
        flash(_gettext('站点不存在'), 'danger')
        return redirect(request.referrer or url_for('admin.dashboard'))
    if not can_access_site(current_user, site.id):
        flash(_gettext('无权访问该站点'), 'danger')
        return redirect(request.referrer or url_for('admin.dashboard'))
    session[SESSION_KEY] = site.id
    invalidate_site_cache()
    flash(_gettext('已切换到站点「{}」').format(site.name), 'success')
    return redirect(request.referrer or url_for('admin.dashboard'))
