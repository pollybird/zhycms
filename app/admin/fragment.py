"""碎片字段管理。升级：权限装饰器（system:settings）+ 审计日志。"""
from flask import (
    render_template, redirect, url_for, request, flash, abort
)

from ..extensions import db
from ..models.fragment import Fragment, FragmentGroup
from ..utils.helpers import permission_required, audit_log, clear_content_cache
from ..utils.uploads import save_upload_file
from ..models.audit import OP_CREATE, OP_UPDATE, OP_DELETE, MODULE_FRAGMENT
from . import admin_bp


FIELD_TYPES = [
    ('text', '单行文本'),
    ('textarea', '多行文本'),
    ('richtext', '富文本'),
    ('image', '图片'),
    ('url', '链接'),
    ('number', '数字'),
    ('file', '文件上传'),
]


# ============ 分组管理 ============

@admin_bp.route('/fragments/groups')
@permission_required('system:settings')
def fragment_group_index():
    groups = FragmentGroup.query.filter_by(is_deleted=False).order_by(
        FragmentGroup.sort_order.desc(), FragmentGroup.created_at.desc()
    ).all()
    return render_template('admin/fragment/group_index.html', groups=groups)


@admin_bp.route('/fragments/groups/create', methods=['POST'])
@permission_required('system:settings')
def fragment_group_create():
    name = (request.form.get('name') or '').strip()
    if not name:
        flash('分组名称必填', 'danger')
        return redirect(url_for('admin.fragment_group_index'))
    g = FragmentGroup(name=name, sort_order=int(request.form.get('sort_order') or 0))
    db.session.add(g)
    db.session.commit()
    flash('分组已创建', 'success')
    return redirect(url_for('admin.fragment_group_index'))


@admin_bp.route('/fragments/groups/<int:gid>/edit', methods=['POST'])
@permission_required('system:settings')
def fragment_group_edit(gid):
    g = FragmentGroup.query.get_or_404(gid)
    g.name = (request.form.get('name') or '').strip() or g.name
    g.sort_order = int(request.form.get('sort_order') or 0)
    db.session.commit()
    flash('分组已更新', 'success')
    return redirect(url_for('admin.fragment_group_index'))


@admin_bp.route('/fragments/groups/<int:gid>/delete', methods=['POST'])
@permission_required('system:settings')
def fragment_group_delete(gid):
    g = FragmentGroup.query.get_or_404(gid)
    if g.fragments.filter_by(is_deleted=False).count() > 0:
        flash('该分组下还有碎片，请先移动或删除碎片', 'danger')
        return redirect(url_for('admin.fragment_group_index'))
    g.is_deleted = True
    db.session.commit()
    flash('分组已删除', 'success')
    return redirect(url_for('admin.fragment_group_index'))


# ============ 碎片字段管理 ============

@admin_bp.route('/fragments')
@permission_required('system:settings')
def fragment_index():
    gid = request.args.get('gid', type=int)
    query = Fragment.query.filter_by(is_deleted=False)
    if gid:
        query = query.filter_by(group_id=gid)
    fragments = query.order_by(
        Fragment.sort_order.desc(), Fragment.created_at.desc()
    ).all()
    groups = FragmentGroup.query.filter_by(is_deleted=False).order_by(
        FragmentGroup.sort_order.desc()
    ).all()
    return render_template(
        'admin/fragment/index.html',
        fragments=fragments, groups=groups, current_gid=gid, field_types=FIELD_TYPES
    )


@admin_bp.route('/fragments/create', methods=['GET', 'POST'])
@permission_required('system:settings')
def fragment_create():
    groups = FragmentGroup.query.filter_by(is_deleted=False).order_by(
        FragmentGroup.sort_order.desc()
    ).all()
    if request.method == 'POST':
        frag = _save_fragment(None)
        if frag is None:
            return redirect(url_for('admin.fragment_create'))
        return redirect(url_for('admin.fragment_index'))
    return render_template('admin/fragment/form.html', fragment=None, groups=groups, field_types=FIELD_TYPES)


@admin_bp.route('/fragments/<int:fid>/edit', methods=['GET', 'POST'])
@permission_required('system:settings')
def fragment_edit(fid):
    frag = Fragment.query.get_or_404(fid)
    if frag.is_deleted:
        abort(404)
    groups = FragmentGroup.query.filter_by(is_deleted=False).order_by(
        FragmentGroup.sort_order.desc()
    ).all()
    if request.method == 'POST':
        updated = _save_fragment(frag)
        if updated is None:
            return redirect(url_for('admin.fragment_edit', fid=fid))
        return redirect(url_for('admin.fragment_index'))
    return render_template('admin/fragment/form.html', fragment=frag, groups=groups, field_types=FIELD_TYPES)


def _save_fragment(fragment):
    name = (request.form.get('name') or '').strip()
    slug = (request.form.get('slug') or '').strip().lower()
    field_type = request.form.get('field_type') or 'text'
    if not name or not slug:
        flash('名称和标识必填', 'danger')
        return None

    existing = Fragment.query.filter_by(slug=slug, is_deleted=False).first()
    if existing and (fragment is None or existing.id != fragment.id):
        flash('标识已存在', 'danger')
        return None

    gid = request.form.get('group_id') or None
    if gid:
        gid = int(gid)

    is_new = fragment is None
    if is_new:
        fragment = Fragment(slug=slug)
        db.session.add(fragment)

    fragment.name = name
    fragment.group_id = gid
    fragment.field_type = field_type
    fragment.sort_order = int(request.form.get('sort_order') or 0)
    fragment.is_enabled = (request.form.get('is_enabled') == 'on')

    # 处理值
    if field_type in ('image', 'file'):
        file_obj = request.files.get('value_file')
        if file_obj and file_obj.filename:
            allowed = ['jpg', 'jpeg', 'png', 'gif', 'webp'] if field_type == 'image' else None
            rel, url, err = save_upload_file(file_obj, sub_dir=f'fragment/{field_type}',
                                             allowed_exts=allowed)
            if err:
                flash(f'文件上传失败：{err}', 'danger')
                return None
            fragment.value = url
        elif request.form.get('value_remove') == 'on':
            fragment.value = ''
        # 否则保留原值
    else:
        fragment.value = request.form.get('value') or ''

    db.session.commit()
    flash('碎片保存成功', 'success')
    return fragment


@admin_bp.route('/fragments/<int:fid>/delete', methods=['POST'])
@permission_required('system:settings')
def fragment_delete(fid):
    frag = Fragment.query.get_or_404(fid)
    frag.is_deleted = True
    db.session.commit()
    flash('碎片已删除', 'success')
    return redirect(url_for('admin.fragment_index'))


@admin_bp.route('/fragments/<int:fid>/toggle', methods=['POST'])
@permission_required('system:settings')
def fragment_toggle(fid):
    frag = Fragment.query.get_or_404(fid)
    frag.is_enabled = not frag.is_enabled
    db.session.commit()
    return redirect(url_for('admin.fragment_index'))
