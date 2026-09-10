"""轮播图插件：后台管理（分组 / 图片）。

路由挂在核心 admin_bp 上（endpoint 归入 admin.*，自动获得后台地址前缀
即时生效机制）；未启用插件时所有路由 404（不暴露存在性），菜单本就隐藏。
"""
import re
from datetime import datetime
from functools import wraps

from flask import render_template, redirect, url_for, request, flash, abort

from app.extensions import db
from app.admin import admin_bp
from app.models.upload import UploadedFile
from app.models.audit import OP_CREATE, OP_UPDATE, OP_DELETE
from app.utils.helpers import permission_required, audit_log
from app.utils.uploads import save_upload_file
from app.constants import Upload as _U
from app.plugin_system import plugin_enabled

from .models import BannerGroup, Banner

from flask_babel import gettext as _gettext
AUDIT_MODULE = 'banner'


# ============================================================
# 守卫与小工具
# ============================================================

def _gate(view):
    """插件启用守卫：未启用 → 404。"""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('banner'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def _release_image(item):
    """释放轮播图对上传文件的引用（ref_count -1，下限 0）。"""
    if item.image_id:
        f = db.session.get(UploadedFile, item.image_id)
        if f is not None:
            f.ref_count = max((f.ref_count or 1) - 1, 0)
        item.image_id = None


def _touch(group):
    """更新分组时间戳，使 banner_items 的缓存键自动失效。"""
    group.updated_at = datetime.now()


def _parse_dt(val):
    val = (val or '').strip()
    if not val:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    return None


def _to_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# ============================================================
# 分组管理
# ============================================================

@admin_bp.route('/banners')
@_gate
@permission_required('banner:manage')
def banner_group_index():
    groups = BannerGroup.query.order_by(BannerGroup.created_at.desc()).all()
    return render_template('banner/group_index.html', groups=groups)


@admin_bp.route('/banners/create', methods=['GET', 'POST'])
@_gate
@permission_required('banner:manage')
def banner_group_create():
    if request.method == 'POST':
        group = _save_group(None)
        if group is None:
            return redirect(url_for('admin.banner_group_create'))
        return redirect(url_for('admin.banner_group_items', gid=group.id))
    return render_template('banner/group_form.html', group=None)


@admin_bp.route('/banners/<int:gid>/edit', methods=['GET', 'POST'])
@_gate
@permission_required('banner:manage')
def banner_group_edit(gid):
    group = BannerGroup.query.get_or_404(gid)
    if request.method == 'POST':
        updated = _save_group(group)
        if updated is None:
            return redirect(url_for('admin.banner_group_edit', gid=gid))
        return redirect(url_for('admin.banner_group_items', gid=gid))
    return render_template('banner/group_form.html', group=group)


def _save_group(group):
    name = (request.form.get('name') or '').strip()
    slug = (request.form.get('slug') or '').strip()
    if not name or not slug:
        flash(_gettext('名称与调用标识必填'), 'danger')
        return None
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', slug):
        flash(_gettext('调用标识须以字母开头，仅含字母、数字、中划线或下划线'), 'danger')
        return None
    exists = BannerGroup.query.filter(
        BannerGroup.slug == slug,
        BannerGroup.id != (group.id if group else 0),
    ).first()
    if exists is not None:
        flash(_gettext('调用标识「{0}」已存在').format(slug), 'danger')
        return None

    is_new = group is None
    if is_new:
        group = BannerGroup()
    group.name = name
    group.slug = slug
    group.remark = (request.form.get('remark') or '').strip()
    group.is_enabled = (request.form.get('is_enabled') == 'on')
    if is_new:
        db.session.add(group)
    db.session.commit()
    audit_log(OP_CREATE if is_new else OP_UPDATE, AUDIT_MODULE,
              group.id, group.name, {'action': '分组', 'slug': slug})
    flash(_gettext('轮播分组已保存'), 'success')
    return group


@admin_bp.route('/banners/<int:gid>/delete', methods=['POST'])
@_gate
@permission_required('banner:manage')
def banner_group_delete(gid):
    group = BannerGroup.query.get_or_404(gid)
    name = group.name
    for item in group.items.all():
        _release_image(item)
    db.session.delete(group)   # 级联删除组内图片记录
    db.session.commit()
    audit_log(OP_DELETE, AUDIT_MODULE, gid, name, {'action': '分组'})
    flash(_gettext('分组已删除，组内图片引用已释放'), 'success')
    return redirect(url_for('admin.banner_group_index'))


# ============================================================
# 图片管理
# ============================================================

@admin_bp.route('/banners/<int:gid>/items')
@_gate
@permission_required('banner:manage')
def banner_group_items(gid):
    group = BannerGroup.query.get_or_404(gid)
    items = group.items.all()
    return render_template('banner/items.html', group=group, items=items)


@admin_bp.route('/banners/<int:gid>/items/create', methods=['GET', 'POST'])
@_gate
@permission_required('banner:manage')
def banner_item_create(gid):
    group = BannerGroup.query.get_or_404(gid)
    if request.method == 'POST':
        item = _save_item(group, None)
        if item is None:
            return redirect(url_for('admin.banner_item_create', gid=gid))
        return redirect(url_for('admin.banner_group_items', gid=gid))
    return render_template('banner/item_form.html', group=group, item=None)


@admin_bp.route('/banners/<int:gid>/items/<int:bid>/edit', methods=['GET', 'POST'])
@_gate
@permission_required('banner:manage')
def banner_item_edit(gid, bid):
    group = BannerGroup.query.get_or_404(gid)
    item = Banner.query.get_or_404(bid)
    if item.group_id != group.id:
        abort(404)
    if request.method == 'POST':
        updated = _save_item(group, item)
        if updated is None:
            return redirect(url_for('admin.banner_item_edit', gid=gid, bid=bid))
        return redirect(url_for('admin.banner_group_items', gid=gid))
    return render_template('banner/item_form.html', group=group, item=item)


def _save_item(group, item):
    is_new = item is None
    if is_new:
        item = Banner(group_id=group.id)

    item.title = (request.form.get('title') or '').strip()
    item.link_url = (request.form.get('link_url') or '').strip()
    item.link_target = request.form.get('link_target') or '_self'
    item.sort_order = _to_int(request.form.get('sort_order'), 0)
    item.is_enabled = (request.form.get('is_enabled') == 'on')
    item.start_at = _parse_dt(request.form.get('start_at'))
    item.end_at = _parse_dt(request.form.get('end_at'))

    upload = request.files.get('image')
    external = (request.form.get('external_url') or '').strip()

    if upload and upload.filename:
        rel, file_url, err = save_upload_file(
            upload, sub_dir='banner',
            allowed_exts=list(_U.IMAGE_EXTS))
        if err:
            flash(_gettext('图片上传失败：{0}').format(err), 'danger')
            return None
        rec = UploadedFile.find_by_url(file_url)
        if rec is None:
            flash(_gettext('图片记录写入异常，请重试'), 'danger')
            return None
        _release_image(item)
        item.image_id = rec.id
        item.external_url = ''
    elif external:
        _release_image(item)
        item.external_url = external
    elif is_new and not item.image_id:
        flash(_gettext('请上传图片或填写图片 URL'), 'danger')
        return None

    if is_new:
        db.session.add(item)
    _touch(group)
    db.session.commit()
    audit_log(OP_CREATE if is_new else OP_UPDATE, AUDIT_MODULE,
              item.id, item.title or f'轮播图#{item.id}',
              {'action': '图片', 'group_id': group.id})
    flash(_gettext('轮播图已保存'), 'success')
    return item


@admin_bp.route('/banners/<int:gid>/items/<int:bid>/delete', methods=['POST'])
@_gate
@permission_required('banner:manage')
def banner_item_delete(gid, bid):
    group = BannerGroup.query.get_or_404(gid)
    item = Banner.query.get_or_404(bid)
    if item.group_id != group.id:
        abort(404)
    _release_image(item)
    title = item.title or f'轮播图#{bid}'
    db.session.delete(item)
    _touch(group)
    db.session.commit()
    audit_log(OP_DELETE, AUDIT_MODULE, bid, title,
              {'action': '图片', 'group_id': gid})
    flash(_gettext('已删除'), 'success')
    return redirect(url_for('admin.banner_group_items', gid=gid))


@admin_bp.route('/banners/<int:gid>/items/<int:bid>/toggle', methods=['POST'])
@_gate
@permission_required('banner:manage')
def banner_item_toggle(gid, bid):
    group = BannerGroup.query.get_or_404(gid)
    item = Banner.query.get_or_404(bid)
    if item.group_id != group.id:
        abort(404)
    item.is_enabled = not item.is_enabled
    _touch(group)
    db.session.commit()
    return redirect(url_for('admin.banner_group_items', gid=gid))


@admin_bp.route('/banners/<int:gid>/items/batch', methods=['POST'])
@_gate
@permission_required('banner:manage')
def banner_item_batch(gid):
    group = BannerGroup.query.get_or_404(gid)
    action = request.form.get('action')
    ids = [int(i) for i in request.form.getlist('ids[]') if i.isdigit()]
    if not ids:
        flash(_gettext('未选择'), 'warning')
        return redirect(url_for('admin.banner_group_items', gid=gid))

    items = Banner.query.filter(Banner.id.in_(ids),
                                Banner.group_id == group.id).all()
    if action == 'enable':
        for it in items:
            it.is_enabled = True
    elif action == 'disable':
        for it in items:
            it.is_enabled = False
    elif action == 'delete':
        for it in items:
            _release_image(it)
            db.session.delete(it)
    _touch(group)
    db.session.commit()
    audit_log(OP_UPDATE if action in ('enable', 'disable') else OP_DELETE,
              AUDIT_MODULE, None, group.name,
              {'action': f'批量{action}', 'count': len(items)})
    flash(_gettext('批量操作完成'), 'success')
    return redirect(url_for('admin.banner_group_items', gid=gid))
