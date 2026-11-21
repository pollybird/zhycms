"""v3.2.0 站群：站点管理（列表 / 新增 / 编辑 / 删除 / 后台切换）。

权限点：`site:manage`（超管与审核员默认拥有）。
约束：
  - 默认站点 id=0 不可删除、不可改为非默认；
  - slug / domain / subdomain 全局唯一（保存前校验）；
  - 删除站点进入回收站，内容保留 30 天，到期前可恢复；
  - 所有变更写审计日志（MODULE_SITE）。
"""
import os
import re
from datetime import datetime

from flask import (render_template, redirect, url_for, request, flash, session,
                   current_app, abort, jsonify, send_file)
from flask_babel import gettext as _gettext
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from ...extensions import db, cache
from ...models.site import Site, DEFAULT_SITE_ID
from ...models.column import Column
from ...models.article import Article
from ...models.fragment import Fragment
from ...models.audit import (
    OP_CREATE, OP_UPDATE, OP_DELETE, OP_BATCH, OP_OTHER, MODULE_SITE, MODULE_ROLE,
)
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


def _emit_site_status(site, old_status):
    """v3.2.12：站点启停状态变化后发射 Webhook 事件。"""
    try:
        from ...services.webhook import emit as webhook_emit
        webhook_emit('site.status_changed', site.id, {
            'site_id': site.id, 'from': old_status, 'to': site.status})
    except Exception as e:
        current_app.logger.warning('Webhook 事件发射失败：%s', e)


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
                           counts=counts, current_site_id=current_site_id(),
                           recycle_count=_recycle_count(),
                           assignable_roles=_assignable_roles(),
                           assignable_users=_assignable_users())


def _recycle_count():
    from ...models.site_recycle import SiteRecycleBin
    try:
        return SiteRecycleBin.query.filter(
            SiteRecycleBin.restored_at.is_(None)).count()
    except SQLAlchemyError:
        return 0


def _assignable_roles():
    from ...services.user_service import assignable_site_roles
    try:
        return assignable_site_roles()
    except SQLAlchemyError:
        return []


def _assignable_users():
    from ...models.user import User
    try:
        return User.query.filter_by(is_deleted=False).order_by(
            User.username.asc()).all()
    except SQLAlchemyError:
        return []


@admin_bp.route('/sites/<int:sid>/deploy')
@permission_required('site:manage')
def site_deploy(sid):
    """只读展示站点部署所需的 nginx 片段与证书状态，不修改服务器配置。"""
    from ...models.setting import Setting
    from ...services.site_deploy import render_site_block, site_hostnames
    from ...services.site_ssl import check_site_certificate

    site = Site.query.filter_by(id=sid, is_deleted=False).first_or_404()
    base_domain = Setting.get('site_url') or ''
    try:
        max_mb = int(Setting.get('upload_single_max_size_mb', '10') or 10)
    except (TypeError, ValueError):
        max_mb = 10

    config_text = ''
    config_error = None
    try:
        config_text = render_site_block(
            site, base_domain=base_domain, upload_max_mb=max_mb)
    except ValueError as e:
        config_error = str(e)

    hosts = site_hostnames(site, base_domain)
    certificate = check_site_certificate(site, base_domain=base_domain)

    return render_template(
        'admin/system/site_deploy.html', site=site,
        config_text=config_text, config_error=config_error,
        server_names=' '.join(hosts) or '_', base_domain=base_domain,
        certificate=certificate, current_site_id=current_site_id())


@admin_bp.route('/sites/metrics')
@permission_required('system:settings', any_of=['site:manage'])
def site_metrics():
    """展示各站点资源占用，并按阈值标记告警行。"""
    from flask_login import current_user
    from ...models.setting import Setting
    from ...services.site_metrics import (collect_site_metrics, format_bytes,
                                          format_number)
    from ...sites import accessible_sites

    refresh = request.args.get('refresh') == '1'

    def _threshold(key, default=0):
        try:
            return int(Setting.get(key, default) or 0)
        except (TypeError, ValueError):
            return default

    article_warn = _threshold('site_metric_article_warn', 5000)
    cache_warn = _threshold('site_metric_cache_warn', 20000)
    disk_warn = _threshold('site_metric_disk_warn_mb', 2048) * 1024 * 1024
    disk_limit = _threshold('site_metric_disk_limit_mb', 0) * 1024 * 1024

    raw = []
    for site in accessible_sites(current_user):
        raw.append((site, collect_site_metrics(site.id, refresh=refresh)))

    total_articles = sum(m['article_count'] for _, m in raw)
    total_disk = sum(m['disk_bytes'] for _, m in raw)

    rows = []
    warn_sites = 0
    for site, metrics in raw:
        reasons = []
        if article_warn and metrics['article_count'] > article_warn:
            reasons.append(_gettext('文章数超过 %(n)s', n=article_warn))
        if (cache_warn and metrics['cache_entries'] is not None
                and metrics['cache_entries'] > cache_warn):
            reasons.append(_gettext('缓存条目超过 %(n)s', n=cache_warn))
        if disk_warn and metrics['disk_bytes'] > disk_warn:
            reasons.append(_gettext('磁盘占用超过 %(n)s MB',
                                    n=disk_warn // (1024 * 1024)))
        danger = bool(disk_limit and metrics['disk_bytes'] > disk_limit)

        if danger:
            row_class = 'table-danger'
        elif reasons:
            row_class = 'table-warning'
        else:
            row_class = ''
        if row_class:
            warn_sites += 1

        percent = (metrics['disk_bytes'] / total_disk * 100) if total_disk else 0
        rows.append({
            'site': site,
            'article_count': format_number(metrics['article_count']),
            'view_count': format_number(metrics['view_count']),
            'cache_entries': format_number(metrics['cache_entries']),
            'disk': format_bytes(metrics['disk_bytes']),
            'percent': f'{percent:.1f}%',
            'reasons': reasons,
            'row_class': row_class,
            'danger': danger,
        })

    return render_template(
        'admin/system/site_metrics.html', rows=rows,
        site_count=len(rows),
        total_articles=format_number(total_articles),
        total_disk=format_bytes(total_disk),
        warn_sites=warn_sites,
        thresholds={
            'article': article_warn,
            'cache': cache_warn,
            'disk_mb': disk_warn // (1024 * 1024),
            'disk_limit_mb': disk_limit // (1024 * 1024),
        },
        current_site_id=current_site_id())


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
        old_status = site.status
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
        if old_status != site.status:
            _emit_site_status(site, old_status)
        return redirect(url_for('admin.site_index'))

    return render_template('admin/system/site_form.html', site=site,
                           form={}, themes=_theme_slugs())


@admin_bp.route('/sites/<int:sid>/delete', methods=['POST'])
@permission_required('site:manage')
def site_delete(sid):
    from ...services.site_clone import move_site_to_recycle

    site = Site.query.filter_by(id=sid, is_deleted=False).first_or_404()
    if site.id == DEFAULT_SITE_ID or site.is_default:
        flash(_gettext('默认站点不可删除'), 'danger')
        return redirect(url_for('admin.site_index'))
    try:
        record = move_site_to_recycle(site, deleted_by=_current_user_id())
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('admin.site_index'))

    _invalidate_all()
    if session.get(SESSION_KEY) == site.id:
        session.pop(SESSION_KEY, None)
    flash(_gettext('站点「{}」已移入回收站，可在 {} 前恢复').format(
        site.name, record.purge_at.strftime('%Y-%m-%d')), 'success')
    return redirect(url_for('admin.site_index'))


def _current_user_id():
    from flask_login import current_user
    return getattr(current_user, 'id', None)


def _is_super_user():
    from flask_login import current_user
    return bool(getattr(current_user, 'is_super', False))


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


# ============================================================
# 证书状态面板
# ============================================================

@admin_bp.route('/sites/ssl')
@permission_required('system:settings', any_of=['site:manage'])
def site_ssl_status():
    from flask_login import current_user
    from ...sites import accessible_sites
    from ...services.site_ssl import check_expiring_certificates

    summary = check_expiring_certificates(sites=accessible_sites(current_user))
    return render_template('admin/system/site_ssl.html', summary=summary,
                           current_site_id=current_site_id())


# ============================================================
# 站点克隆
# ============================================================

CLONE_ASYNC_TOTAL = 5000
CLONE_ASYNC_COLUMNS = 500


@admin_bp.route('/sites/<int:sid>/clone', methods=['GET', 'POST'])
@permission_required('site:manage')
def site_clone(sid):
    from ...services.site_clone import (
        CloneError, clone_site, estimate_clone_size, run_clone_job,
    )

    source = Site.query.filter_by(id=sid, is_deleted=False).first_or_404()
    estimate = estimate_clone_size(source.id)
    if request.method != 'POST':
        return render_template(
            'admin/system/site_clone.html', source=source, estimate=estimate,
            form={}, themes=_theme_slugs(), job=None,
            current_site_id=current_site_id())

    errors, data = _validate(request.form)
    if errors:
        for e in errors:
            flash(e, 'danger')
        return render_template(
            'admin/system/site_clone.html', source=source, estimate=estimate,
            form=request.form, themes=_theme_slugs(), job=None,
            current_site_id=current_site_id())

    options = {
        'plugins': request.form.get('copy_plugins') == 'on',
        'builder': request.form.get('copy_builder') == 'on',
    }
    use_async = (estimate['total'] > CLONE_ASYNC_TOTAL
                 or estimate['columns'] > CLONE_ASYNC_COLUMNS)

    if use_async:
        from ...models.site_job import JOB_CLONE
        from ...services.site_jobs import create_job, start_background

        job = create_job(JOB_CLONE, payload={
            'source_site_id': source.id, 'target': data, 'options': options,
        }, created_by=_current_user_id())
        start_background(current_app._get_current_object(), run_clone_job,
                         job.id, source.id, data, options)
        flash(_gettext('站点内容较多，已在后台克隆，可在本页查看进度'), 'info')
        return render_template(
            'admin/system/site_clone.html', source=source, estimate=estimate,
            form=request.form, themes=_theme_slugs(), job=job,
            current_site_id=current_site_id())

    try:
        result = clone_site(source.id, data, options=options)
    except CloneError as e:
        audit_log(OP_OTHER, MODULE_SITE, target_id=source.id,
                  target_name=source.name,
                  detail={'action': 'clone_failed', 'error': str(e)})
        flash(_gettext('克隆失败：{}').format(e), 'danger')
        return render_template(
            'admin/system/site_clone.html', source=source, estimate=estimate,
            form=request.form, themes=_theme_slugs(), job=None,
            current_site_id=current_site_id())

    _invalidate_all()
    counts = '、'.join(f'{k} {v}' for k, v in result['counts'].items())
    flash(_gettext('站点克隆完成（{}）').format(counts), 'success')
    return redirect(url_for('admin.site_index'))


@admin_bp.route('/sites/clone/jobs/<int:job_id>')
@permission_required('site:manage')
def site_clone_job(job_id):
    from ...models.site_job import SiteJob
    from ...services.site_jobs import job_to_dict

    job = db.session.get(SiteJob, job_id)
    if job is None:
        abort(404)
    if (job.created_by and job.created_by != _current_user_id()
            and not _is_super_user()):
        abort(403)
    return jsonify(job_to_dict(job))


# ============================================================
# 站点级备份
# ============================================================

def _backup_token(site_id, filename):
    serializer = URLSafeTimedSerializer(
        current_app.secret_key, salt='site-backup')
    return serializer.dumps({'site_id': site_id, 'filename': filename})


def _render_backups(site, pending=None):
    from ...services.site_backup import list_site_backups

    items = list_site_backups(site.id)
    for item in items:
        item['download_token'] = _backup_token(site.id, item['filename'])
    return render_template(
        'admin/system/site_backups.html', site=site, backups=items,
        pending=pending, current_site_id=current_site_id())


@admin_bp.route('/sites/<int:sid>/backups')
@permission_required('site:manage')
def site_backups(sid):
    site = Site.query.filter_by(id=sid, is_deleted=False).first_or_404()
    return _render_backups(site)


@admin_bp.route('/sites/<int:sid>/backups/export', methods=['POST'])
@permission_required('site:manage')
def site_backup_export(sid):
    from ...services.site_backup import BackupError, export_site

    site = Site.query.filter_by(id=sid, is_deleted=False).first_or_404()
    try:
        result = export_site(site.id, created_by=_current_user_id())
    except BackupError as e:
        flash(str(e), 'danger')
        return redirect(url_for('admin.site_backups', sid=site.id))
    flash(_gettext('备份已生成：{}（{} 字节）').format(
        result['filename'], result['size']), 'success')
    return redirect(url_for('admin.site_backups', sid=site.id))


@admin_bp.route('/sites/<int:sid>/backups/import', methods=['POST'])
@permission_required('site:manage')
def site_backup_import(sid):
    from ...services.site_backup import (
        BackupError, discard_incoming, import_site_backup, incoming_path,
        inspect_backup, save_incoming,
    )

    site = Site.query.filter_by(id=sid, is_deleted=False).first_or_404()

    if request.form.get('confirm') == '1':
        incoming = request.form.get('incoming') or ''
        mode = request.form.get('mode') or 'new'
        try:
            path = incoming_path(incoming)
            result = import_site_backup(
                path,
                target_site_id=site.id if mode == 'overwrite' else None,
                mode=mode, created_by=_current_user_id())
        except (BackupError, ValueError) as e:
            flash(_gettext('导入失败：{}').format(e), 'danger')
            return _render_backups(site)
        finally:
            discard_incoming(incoming)

        _invalidate_all()
        flash(_gettext('备份导入完成，站点 ID {}').format(result['site_id']),
              'success')
        for warning in result['warnings'][:5]:
            flash(warning, 'warning')
        return redirect(url_for('admin.site_index'))

    upload = request.files.get('file')
    if upload is None or not upload.filename:
        flash(_gettext('请选择要导入的 ZIP 备份文件'), 'danger')
        return redirect(url_for('admin.site_backups', sid=site.id))
    if not upload.filename.lower().endswith('.zip'):
        flash(_gettext('只支持 .zip 格式的站点备份'), 'danger')
        return redirect(url_for('admin.site_backups', sid=site.id))

    incoming = save_incoming(upload)
    try:
        summary = inspect_backup(incoming_path(incoming))
    except BackupError as e:
        discard_incoming(incoming)
        flash(_gettext('备份文件校验失败：{}').format(e), 'danger')
        return redirect(url_for('admin.site_backups', sid=site.id))

    mode = request.form.get('mode') or 'new'
    if mode not in ('new', 'overwrite', 'rename'):
        mode = 'new'
    return _render_backups(site, pending={
        'incoming': incoming, 'summary': summary, 'mode': mode})


@admin_bp.route('/sites/<int:sid>/backups/delete', methods=['POST'])
@permission_required('site:manage')
def site_backup_delete(sid):
    from ...services.site_backup import BackupError, delete_site_backup

    site = Site.query.filter_by(id=sid, is_deleted=False).first_or_404()
    filename = request.form.get('filename') or ''
    try:
        delete_site_backup(site.id, filename, operator_id=_current_user_id())
    except (BackupError, ValueError) as e:
        flash(str(e), 'danger')
    else:
        flash(_gettext('备份已删除：{}').format(filename), 'success')
    return redirect(url_for('admin.site_backups', sid=site.id))


@admin_bp.route('/sites/backups/download')
@permission_required('site:manage')
def site_backup_download():
    from ...services.site_backup import DOWNLOAD_MAX_AGE, backup_path

    token = request.args.get('token') or ''
    serializer = URLSafeTimedSerializer(
        current_app.secret_key, salt='site-backup')
    try:
        payload = serializer.loads(token, max_age=DOWNLOAD_MAX_AGE)
    except (BadSignature, SignatureExpired):
        abort(403)
    try:
        path = backup_path(int(payload['site_id']), payload['filename'])
    except (KeyError, TypeError, ValueError):
        abort(403)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=True,
                     download_name=payload['filename'])


# ============================================================
# 批量操作与回收站
# ============================================================

def _parse_site_ids():
    ids = []
    for raw in request.form.getlist('site_ids'):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return ids


@admin_bp.route('/sites/batch', methods=['POST'])
@permission_required('site:manage')
def site_batch():
    from ...services.site_clone import move_site_to_recycle

    action = request.form.get('action') or ''
    if action not in ('enable', 'disable', 'delete'):
        flash(_gettext('批量操作不合法'), 'danger')
        return redirect(url_for('admin.site_index'))

    site_ids = _parse_site_ids()
    if not site_ids:
        flash(_gettext('请先选择站点'), 'warning')
        return redirect(url_for('admin.site_index'))

    done = []
    skipped = []
    for site in Site.query.filter(Site.id.in_(site_ids)).all():
        if site.id == DEFAULT_SITE_ID or site.is_default:
            skipped.append(site.name)
            continue
        try:
            if action == 'delete':
                if site.is_deleted:
                    skipped.append(site.name)
                    continue
                move_site_to_recycle(site, deleted_by=_current_user_id())
            else:
                new_status = 'open' if action == 'enable' else 'closed'
                old_status = site.status
                site.status = new_status
                db.session.commit()
                if old_status != new_status:
                    _emit_site_status(site, old_status)
            done.append(site.id)
        except (SQLAlchemyError, ValueError) as e:
            db.session.rollback()
            current_app.logger.warning('批量操作站点 %s 失败：%s', site.id, e)
            skipped.append(site.name)

    _invalidate_all()
    if session.get(SESSION_KEY) in done and action == 'delete':
        session.pop(SESSION_KEY, None)
    audit_log(OP_BATCH, MODULE_SITE, detail={
        'action': action, 'site_ids': done, 'skipped': skipped})
    flash(_gettext('批量{}完成：成功 {} 个，跳过 {} 个').format(
        {'enable': '启用', 'disable': '停用', 'delete': '删除'}[action],
        len(done), len(skipped)), 'success')
    return redirect(url_for('admin.site_index'))


@admin_bp.route('/sites/batch/assign-role', methods=['POST'])
@permission_required('site:manage')
def site_batch_assign_role():
    from ...models.rbac import Role, UserRole
    from ...models.user import User
    from ...services.user_service import assignable_site_roles

    user_id = request.form.get('user_id')
    role_code = (request.form.get('role_code') or '').strip()
    site_ids = _parse_site_ids()

    user = db.session.get(User, int(user_id)) if (user_id or '').isdigit() else None
    role = Role.query.filter_by(code=role_code, is_deleted=False).first()
    allowed = {r.code for r in assignable_site_roles()}
    if user is None or role is None or role.code not in allowed:
        flash(_gettext('用户或站点角色不合法'), 'danger')
        return redirect(url_for('admin.site_index'))
    if not site_ids:
        flash(_gettext('请先选择站点'), 'warning')
        return redirect(url_for('admin.site_index'))

    assigned = 0
    for site in Site.query.filter(
            Site.id.in_(site_ids), Site.is_deleted.is_(False)).all():
        exists = UserRole.query.filter_by(
            user_id=user.id, role_id=role.id, site_id=site.id).first()
        if exists is not None:
            continue
        db.session.add(UserRole(user_id=user.id, role_id=role.id,
                                site_id=site.id))
        assigned += 1
    db.session.commit()
    audit_log(OP_BATCH, MODULE_ROLE, target_id=user.id,
              target_name=user.username,
              detail={'action': 'assign_site_role', 'role': role.code,
                      'site_ids': site_ids, 'assigned': assigned})
    flash(_gettext('已为 {} 在 {} 个站点分配角色「{}」').format(
        user.username, assigned, role.name), 'success')
    return redirect(url_for('admin.site_index'))


@admin_bp.route('/sites/recycle')
@permission_required('site:manage')
def site_recycle():
    from ...models.site_recycle import SiteRecycleBin

    records = SiteRecycleBin.query.filter(
        SiteRecycleBin.restored_at.is_(None)).order_by(
        SiteRecycleBin.deleted_at.desc()).all()
    return render_template('admin/system/site_recycle.html', records=records,
                           now=datetime.now(),
                           current_site_id=current_site_id())


@admin_bp.route('/sites/recycle/<int:rid>/restore', methods=['POST'])
@permission_required('site:manage')
def site_recycle_restore(rid):
    from ...models.site_recycle import SiteRecycleBin
    from ...services.site_clone import restore_site

    record = db.session.get(SiteRecycleBin, rid)
    if record is None or record.restored_at is not None:
        flash(_gettext('回收站记录不存在'), 'danger')
        return redirect(url_for('admin.site_recycle'))
    try:
        site = restore_site(record)
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('admin.site_recycle'))
    _invalidate_all()
    flash(_gettext('站点「{}」已恢复，当前为关闭状态').format(site.name), 'success')
    return redirect(url_for('admin.site_recycle'))


@admin_bp.route('/sites/recycle/<int:rid>/purge', methods=['POST'])
@permission_required('site:manage')
def site_recycle_purge(rid):
    from ...models.site_recycle import SiteRecycleBin
    from ...services.site_backup import BackupError
    from ...services.site_clone import purge_site

    if not _is_super_user():
        abort(403)
    record = db.session.get(SiteRecycleBin, rid)
    if record is None or record.restored_at is not None:
        flash(_gettext('回收站记录不存在'), 'danger')
        return redirect(url_for('admin.site_recycle'))
    try:
        purge_site(record.site_id, created_by=_current_user_id())
    except (BackupError, ValueError) as e:
        flash(_gettext('彻底删除失败（已保留站点）：{}').format(e), 'danger')
        return redirect(url_for('admin.site_recycle'))
    db.session.delete(record)
    db.session.commit()
    _invalidate_all()
    flash(_gettext('站点已彻底删除，删除前备份已保留'), 'success')
    return redirect(url_for('admin.site_recycle'))


# ============================================================
# Webhook 事件订阅（v3.2.12，站点设置 → 集成）
# ============================================================

from ...models.webhook import WebhookSubscription, WebhookEvent  # noqa: E402


def _webhook_sub_or_404(sid):
    return WebhookSubscription.query.filter_by(
        id=sid, site_id=current_site_id()).first_or_404()


def _webhook_validate_form():
    """校验订阅表单，返回 (url, events_csv, enabled, error)。"""
    from ...services.webhook import EVENT_TYPES, validate_target_url
    url = (request.form.get('url') or '').strip()
    events = [e for e in request.form.getlist('events') if e in EVENT_TYPES]
    enabled = request.form.get('enabled') == 'on'
    if not url:
        return None, None, None, _gettext('接收地址必填')
    if not events:
        return None, None, None, _gettext('请至少选择一个事件类型')
    try:
        validate_target_url(url)
    except ValueError as e:
        return None, None, None, _gettext('接收地址未通过安全校验：{}').format(e)
    return url, ','.join(events), enabled, None


@admin_bp.route('/sites/webhooks')
@permission_required('site:manage')
def site_webhooks():
    subs = WebhookSubscription.query.filter_by(
        site_id=current_site_id()).order_by(WebhookSubscription.id.desc()).all()
    last_events = {s.id: s.deliveries.order_by(
        WebhookEvent.id.desc()).first() for s in subs}
    return render_template('admin/system/site_webhooks.html',
                           subs=subs, last_events=last_events)


@admin_bp.route('/sites/webhooks/create', methods=['GET', 'POST'])
@permission_required('site:manage')
def site_webhook_create():
    from ...services.webhook import EVENT_TYPES
    if request.method == 'POST':
        url, events, enabled, error = _webhook_validate_form()
        if error:
            flash(error, 'danger')
        elif WebhookSubscription.query.filter_by(
                site_id=current_site_id(), url=url).first():
            flash(_gettext('该接收地址已存在订阅'), 'danger')
        else:
            sub = WebhookSubscription(site_id=current_site_id(), url=url,
                                      events=events, enabled=enabled)
            secret = WebhookSubscription.generate_secret()
            sub.set_secret(secret)
            db.session.add(sub)
            db.session.commit()
            audit_log(OP_CREATE, MODULE_SITE, target_id=sub.id, target_name=url,
                      detail={'action': 'webhook_create', 'events': events})
            flash(_gettext('Webhook 订阅已创建'), 'success')
            flash(_gettext('签名密钥（仅显示一次，请立即保存）：{}').format(secret),
                  'warning')
            return redirect(url_for('admin.site_webhooks'))
    return render_template('admin/system/site_webhook_form.html', sub=None,
                           event_types=EVENT_TYPES, form=request.form)


@admin_bp.route('/sites/webhooks/<int:sid>/edit', methods=['GET', 'POST'])
@permission_required('site:manage')
def site_webhook_edit(sid):
    from ...services.webhook import EVENT_TYPES
    sub = _webhook_sub_or_404(sid)
    if request.method == 'POST':
        url, events, enabled, error = _webhook_validate_form()
        if error:
            flash(error, 'danger')
        else:
            duplicate = WebhookSubscription.query.filter(
                WebhookSubscription.site_id == current_site_id(),
                WebhookSubscription.url == url,
                WebhookSubscription.id != sub.id).first()
            if duplicate:
                flash(_gettext('该接收地址已存在订阅'), 'danger')
            else:
                sub.url, sub.events, sub.enabled = url, events, enabled
                db.session.commit()
                audit_log(OP_UPDATE, MODULE_SITE, target_id=sub.id,
                          target_name=url,
                          detail={'action': 'webhook_update', 'events': events,
                                  'enabled': enabled})
                flash(_gettext('Webhook 订阅已保存'), 'success')
                return redirect(url_for('admin.site_webhooks'))
    return render_template('admin/system/site_webhook_form.html', sub=sub,
                           event_types=EVENT_TYPES, form=request.form)


@admin_bp.route('/sites/webhooks/<int:sid>/rotate', methods=['POST'])
@permission_required('site:manage')
def site_webhook_rotate(sid):
    sub = _webhook_sub_or_404(sid)
    secret = WebhookSubscription.generate_secret()
    sub.set_secret(secret)
    db.session.commit()
    audit_log(OP_UPDATE, MODULE_SITE, target_id=sub.id, target_name=sub.url,
              detail={'action': 'webhook_rotate_secret'})
    flash(_gettext('密钥已轮换，旧密钥立即失效'), 'success')
    flash(_gettext('新签名密钥（仅显示一次，请立即保存）：{}').format(secret),
          'warning')
    return redirect(url_for('admin.site_webhooks'))


@admin_bp.route('/sites/webhooks/<int:sid>/delete', methods=['POST'])
@permission_required('site:manage')
def site_webhook_delete(sid):
    sub = _webhook_sub_or_404(sid)
    url = sub.url
    db.session.delete(sub)
    db.session.commit()
    audit_log(OP_DELETE, MODULE_SITE, target_id=sid, target_name=url,
              detail={'action': 'webhook_delete'})
    flash(_gettext('Webhook 订阅已删除'), 'success')
    return redirect(url_for('admin.site_webhooks'))


@admin_bp.route('/sites/webhooks/<int:sid>/test', methods=['POST'])
@permission_required('site:manage')
def site_webhook_test(sid):
    from ...services.webhook import create_test_event
    sub = _webhook_sub_or_404(sid)
    event = create_test_event(sub)
    audit_log(OP_OTHER, MODULE_SITE, target_id=sub.id, target_name=sub.url,
              detail={'action': 'webhook_test', 'event_id': event.id})
    flash(_gettext('测试事件已生成，将由投递器在约 10 秒内发送'), 'success')
    return redirect(url_for('admin.site_webhook_events', subscription_id=sub.id))


@admin_bp.route('/sites/webhooks/events')
@permission_required('site:manage')
def site_webhook_events():
    from ...services.webhook import EVENT_TYPES
    query = WebhookEvent.query.filter_by(site_id=current_site_id())
    status = request.args.get('status') or ''
    event_type = request.args.get('event_type') or ''
    subscription_id = request.args.get('subscription_id', type=int)
    if status in (WebhookEvent.STATUS_PENDING, WebhookEvent.STATUS_DELIVERING,
                  WebhookEvent.STATUS_SUCCESS, WebhookEvent.STATUS_FAILED):
        query = query.filter_by(status=status)
    else:
        status = ''
    if event_type in EVENT_TYPES:
        query = query.filter_by(event_type=event_type)
    else:
        event_type = ''
    if subscription_id:
        query = query.filter_by(subscription_id=subscription_id)
    events = query.order_by(WebhookEvent.id.desc()).limit(100).all()
    return render_template('admin/system/site_webhook_events.html',
                           events=events, event_types=EVENT_TYPES,
                           status=status, event_type=event_type,
                           subscription_id=subscription_id)


@admin_bp.route('/sites/webhooks/events/<int:eid>/retry', methods=['POST'])
@permission_required('site:manage')
def site_webhook_event_retry(eid):
    from ...services.webhook import retry_event
    event = retry_event(eid, site_id=current_site_id())
    if event is None:
        flash(_gettext('投递记录不存在'), 'danger')
    else:
        audit_log(OP_OTHER, MODULE_SITE, target_id=event.id,
                  target_name=event.event_type,
                  detail={'action': 'webhook_retry',
                          'replay_id': event.replay_id})
        flash(_gettext('已重新加入投递队列'), 'success')
    return redirect(request.referrer or url_for('admin.site_webhook_events'))
