"""友情链接插件：后台管理。

路由挂在核心 admin_bp 上（endpoint 归入 admin.*，自动获得后台地址前缀
即时生效机制），路径与核心版一致（/friend-links），老站书签/审计记录不受影响；
未启用插件时所有路由 404（不暴露存在性），菜单本就隐藏。
"""
from functools import wraps

from flask import render_template, redirect, url_for, request, flash, abort

from app.extensions import db
from app.admin import admin_bp
from app.models.audit import OP_CREATE, OP_UPDATE, OP_DELETE, OP_BATCH
from app.utils.helpers import permission_required, audit_log
from app.utils.uploads import save_upload_file
from app.constants import Upload as _U
from app.plugin_system import plugin_enabled

from .models import FriendLink, FriendLinkTranslation
from app.utils.i18n_content import get_available_locales, get_default_locale

from flask_babel import gettext as _gettext
AUDIT_MODULE = 'friend_link'


def _gate(view):
    """插件启用守卫：未启用 → 404。"""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('friend_link'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


@admin_bp.route('/friend-links')
@_gate
@permission_required('friend_link:manage')
def friend_link_index():
    links = FriendLink.query.filter_by(is_deleted=False).order_by(
        FriendLink.sort_order.desc(), FriendLink.created_at.desc()
    ).all()
    return render_template('friend_link/index.html', links=links)


@admin_bp.route('/friend-links/create', methods=['GET', 'POST'])
@_gate
@permission_required('friend_link:manage')
def friend_link_create():
    if request.method == 'POST':
        link = _save_link(None)
        if link is None:
            return redirect(url_for('admin.friend_link_create'))
        return redirect(url_for('admin.friend_link_index'))
    return render_template('friend_link/form.html', link=link,
                           trans_locales=_trans_locales(),
                           default_locale=get_default_locale())


@admin_bp.route('/friend-links/<int:lid>/edit', methods=['GET', 'POST'])
@_gate
@permission_required('friend_link:manage')
def friend_link_edit(lid):
    link = FriendLink.query.get_or_404(lid)
    if request.method == 'POST':
        updated = _save_link(link)
        if updated is None:
            return redirect(url_for('admin.friend_link_edit', lid=lid))
        return redirect(url_for('admin.friend_link_index'))
    return render_template('friend_link/form.html', link=link,
                           trans_locales=_trans_locales(),
                           default_locale=get_default_locale())


def _trans_locales():
    """非默认语言的语种列表（无 i18n 配置时为空列表）。"""
    try:
        default_locale = get_default_locale()
        return [l for l in get_available_locales() if l != default_locale]
    except Exception:
        return []


def _save_link(link):
    name = (request.form.get('name') or '').strip()
    url = (request.form.get('url') or '').strip()
    if not name or not url:
        flash(_gettext('名称和 URL 必填'), 'danger')
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
                                              allowed_exts=list(_U.IMAGE_EXTS))
        if err:
            flash(_gettext('LOGO 上传失败：{0}').format(err), 'danger')
            return None
        link.logo = file_url
    elif request.form.get('logo_remove') == 'on':
        link.logo = None

    if is_new:
        db.session.add(link)
    db.session.commit()
    _save_link_translations(link)
    audit_log(OP_CREATE if is_new else OP_UPDATE, AUDIT_MODULE,
              link.id, link.name, {'action': '链接', 'url': link.url})
    flash(_gettext('友情链接已保存'), 'success')
    return link


def _save_link_translations(link):
    """保存链接名称各语种翻译（v2.5.0）。仅名称；URL/LOGO 不随语言变化。

    表单字段命名：name_{locale}。非默认语言且名称非空 → upsert；
    名称为空 → 删除该翻译（前台回退默认语言名称）。
    """
    locales = _trans_locales()
    if not locales:
        return
    existing = {tr.locale: tr for tr in link.translations}
    for loc in locales:
        tr_name = (request.form.get(f'name_{loc}') or '').strip()
        if not tr_name:
            if loc in existing:
                db.session.delete(existing[loc])
            continue
        tr = existing.get(loc)
        if tr is None:
            tr = FriendLinkTranslation(link_id=link.id, locale=loc)
            db.session.add(tr)
        tr.name = tr_name
    db.session.commit()


@admin_bp.route('/friend-links/<int:lid>/delete', methods=['POST'])
@_gate
@permission_required('friend_link:manage')
def friend_link_delete(lid):
    link = FriendLink.query.get_or_404(lid)
    link.is_deleted = True
    db.session.commit()
    audit_log(OP_DELETE, AUDIT_MODULE, link.id, link.name, {'action': '链接'})
    flash(_gettext('已删除'), 'success')
    return redirect(url_for('admin.friend_link_index'))


@admin_bp.route('/friend-links/<int:lid>/toggle', methods=['POST'])
@_gate
@permission_required('friend_link:manage')
def friend_link_toggle(lid):
    link = FriendLink.query.get_or_404(lid)
    link.is_enabled = not link.is_enabled
    db.session.commit()
    audit_log(OP_UPDATE, AUDIT_MODULE, link.id, link.name,
              {'action': '启停切换', 'is_enabled': link.is_enabled})
    return redirect(url_for('admin.friend_link_index'))


@admin_bp.route('/friend-links/batch', methods=['POST'])
@_gate
@permission_required('friend_link:manage')
def friend_link_batch():
    action = request.form.get('action')
    ids = [int(i) for i in request.form.getlist('ids[]') if i.isdigit()]
    if not ids:
        flash(_gettext('未选择'), 'warning')
        return redirect(url_for('admin.friend_link_index'))

    links = FriendLink.query.filter(FriendLink.id.in_(ids)).all()
    if action == 'enable':
        for l in links:
            l.is_enabled = True
    elif action == 'disable':
        for l in links:
            l.is_enabled = False
    elif action == 'delete':
        for l in links:
            l.is_deleted = True
    db.session.commit()
    audit_log(OP_BATCH, AUDIT_MODULE, None, None,
              {'action': f'批量{action}', 'count': len(links)})
    flash(_gettext('批量操作完成'), 'success')
    return redirect(url_for('admin.friend_link_index'))
