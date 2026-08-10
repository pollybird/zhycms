"""友情链接管理。"""
from flask import (
    render_template, redirect, url_for, request, flash
)

from ..extensions import db
from ..models.friend_link import FriendLink
from ..utils.helpers import admin_required
from ..utils.uploads import save_upload_file
from . import admin_bp


@admin_bp.route('/friend-links')
@admin_required
def friend_link_index():
    links = FriendLink.query.filter_by(is_deleted=False).order_by(
        FriendLink.sort_order.desc(), FriendLink.created_at.desc()
    ).all()
    return render_template('admin/friend_link/index.html', links=links)


@admin_bp.route('/friend-links/create', methods=['GET', 'POST'])
@admin_required
def friend_link_create():
    if request.method == 'POST':
        link = _save_link(None)
        if link is None:
            return redirect(url_for('admin.friend_link_create'))
        return redirect(url_for('admin.friend_link_index'))
    return render_template('admin/friend_link/form.html', link=None)


@admin_bp.route('/friend-links/<int:lid>/edit', methods=['GET', 'POST'])
@admin_required
def friend_link_edit(lid):
    link = FriendLink.query.get_or_404(lid)
    if request.method == 'POST':
        updated = _save_link(link)
        if updated is None:
            return redirect(url_for('admin.friend_link_edit', lid=lid))
        return redirect(url_for('admin.friend_link_index'))
    return render_template('admin/friend_link/form.html', link=link)


def _save_link(link):
    name = (request.form.get('name') or '').strip()
    url = (request.form.get('url') or '').strip()
    if not name or not url:
        flash('名称和 URL 必填', 'danger')
        return None

    is_new = link is None
    if is_new:
        link = FriendLink()

    link.name = name
    link.url = url
    link.sort_order = int(request.form.get('sort_order') or 0)
    link.is_enabled = (request.form.get('is_enabled') == 'on')
    link.target = request.form.get('target') or '_blank'
    link.remark = (request.form.get('remark') or '').strip()

    logo_file = request.files.get('logo')
    if logo_file and logo_file.filename:
        rel, file_url, err = save_upload_file(logo_file, sub_dir='friend_link',
                                              allowed_exts=['jpg', 'jpeg', 'png', 'gif', 'webp'])
        if err:
            flash(f'LOGO 上传失败：{err}', 'danger')
            return None
        link.logo = file_url
    elif request.form.get('logo_remove') == 'on':
        link.logo = None

    if is_new:
        db.session.add(link)
    db.session.commit()
    flash('友情链接已保存', 'success')
    return link


@admin_bp.route('/friend-links/<int:lid>/delete', methods=['POST'])
@admin_required
def friend_link_delete(lid):
    link = FriendLink.query.get_or_404(lid)
    link.is_deleted = True
    db.session.commit()
    flash('已删除', 'success')
    return redirect(url_for('admin.friend_link_index'))


@admin_bp.route('/friend-links/<int:lid>/toggle', methods=['POST'])
@admin_required
def friend_link_toggle(lid):
    link = FriendLink.query.get_or_404(lid)
    link.is_enabled = not link.is_enabled
    db.session.commit()
    return redirect(url_for('admin.friend_link_index'))


@admin_bp.route('/friend-links/batch', methods=['POST'])
@admin_required
def friend_link_batch():
    action = request.form.get('action')
    ids = [int(i) for i in request.form.getlist('ids[]') if i.isdigit()]
    if not ids:
        flash('未选择', 'warning')
        return redirect(url_for('admin.friend_link_index'))

    links = FriendLink.query.filter(FriendLink.id.in_(ids)).all()
    if action == 'enable':
        for l in links: l.is_enabled = True
    elif action == 'disable':
        for l in links: l.is_enabled = False
    elif action == 'delete':
        for l in links: l.is_deleted = True
    db.session.commit()
    flash('批量操作完成', 'success')
    return redirect(url_for('admin.friend_link_index'))
