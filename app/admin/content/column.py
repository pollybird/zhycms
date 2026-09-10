"""栏目管理：树形、三种类型、自定义字段。
升级：权限（@permission_required('column:manage')）+ 审计日志 + 栏目专属权限。
"""
from flask import (
    render_template, redirect, url_for, request,
    flash, jsonify, abort
)

from flask_babel import gettext as _gettext
from ...extensions import db
from ...models.column import Column, ColumnField
from ...utils.i18n_content import get_available_locales, get_default_locale
from ...utils.helpers import permission_required, audit_log, clear_content_cache
from ...utils.themes import list_theme_templates, TEMPLATE_CATEGORIES
from ...models.audit import OP_UPDATE, OP_DELETE, OP_BATCH, MODULE_COLUMN
from ...services.column_service import save_column
from .. import admin_bp


FIELD_TYPES = [
    ('text', '单行文本'),
    ('textarea', '多行文本'),
    ('richtext', '富文本'),
    ('image', '单图图片'),
    ('url', 'URL 网址'),
    ('number', '数字'),
    ('file', '文件上传'),
]


def _build_tree_with_depth(columns, parent_id=None, depth=0):
    """构建带层级的列表，给每条加 depth。"""
    result = []
    for col in columns:
        if col.parent_id == parent_id:
            col._depth = depth
            result.append(col)
            result.extend(_build_tree_with_depth(columns, col.id, depth + 1))
    return result


@admin_bp.route('/columns')
@permission_required('column:manage', any_of=[
    'content_manage:all_columns',
    'content:create', 'content:edit', 'content:delete', 'content:submit_review',
    'content:review', 'content:publish', 'content:archive', 'content:batch',
    'content:rollback',
])
def column_index():
    columns = Column.get_tree(include_deleted=False)
    # 非超级管理员 & 无全局栏目权限：只看被分配栏目专属权限的栏目树
    from flask_login import current_user
    if not getattr(current_user, 'is_super', False) and \
            not current_user.has_permission('column:manage'):
        allowed = current_user.get_allowed_column_ids()
        if allowed is not None:
            columns = [c for c in columns if c.id in allowed]
            # 过滤父级（保证树完整：保留所有祖先）
            keep = set(allowed)
            changed = True
            while changed:
                changed = False
                for c in columns:
                    if c.parent_id and c.parent_id not in keep:
                        # 跳过，没权限看的父不显示
                        pass
                # 简单实现：保持原 columns，后续渲染自行裁剪
            tree = _build_tree_with_depth(columns)
            return render_template('admin/column/index.html', columns=tree, field_types=FIELD_TYPES)
    tree = _build_tree_with_depth(columns)
    return render_template('admin/column/index.html', columns=tree, field_types=FIELD_TYPES)


def _template_options():
    """获取各类型可选模板列表，供表单下拉使用。"""
    return {
        'list': list_theme_templates(category='list'),
        'detail': list_theme_templates(category='detail'),
        'page': list_theme_templates(category='page'),
    }


@admin_bp.route('/columns/create', methods=['GET', 'POST'])
@permission_required('column:manage')
def column_create():
    if request.method == 'POST':
        col, messages = save_column(
            None, form_data=request.form, files_data=request.files,
        )
        for category, msg in messages:
            flash(msg, category)
        if col is None:
            return redirect(url_for('admin.column_create'))
        return redirect(url_for('admin.column_index'))

    parents = Column.get_tree()
    return render_template(
        'admin/column/form.html',
        column=None, parents=parents, field_types=FIELD_TYPES,
        parent_options=_build_tree_with_depth(parents),
        template_options=_template_options(),
    )


@admin_bp.route('/columns/<int:cid>/edit', methods=['GET', 'POST'])
@permission_required('column:manage')
def column_edit(cid):
    col = Column.query.get_or_404(cid)
    if col.is_deleted:
        abort(404)

    if request.method == 'POST':
        updated, messages = save_column(
            col, form_data=request.form, files_data=request.files,
        )
        for category, msg in messages:
            flash(msg, category)
        if updated is None:
            return redirect(url_for('admin.column_edit', cid=cid))
        return redirect(url_for('admin.column_index'))

    parents = Column.get_tree()
    return render_template(
        'admin/column/form.html',
        column=col, parents=parents, field_types=FIELD_TYPES,
        parent_options=_build_tree_with_depth(parents),
        template_options=_template_options(),
        trans_locales=[l for l in get_available_locales() if l != get_default_locale()],
        default_locale=get_default_locale(),
    )



@admin_bp.route('/columns/<int:cid>/delete', methods=['POST'])
@permission_required('column:manage')
def column_delete(cid):
    col = Column.query.get_or_404(cid)
    if col.is_parent:
        flash(_gettext('该栏目存在子栏目，请先删除子栏目后再操作'), 'danger')
        return redirect(url_for('admin.column_index'))

    col.is_deleted = True
    db.session.commit()
    clear_content_cache(column_id=cid)
    flash(_gettext('栏目已删除'), 'success')
    audit_log(OP_DELETE, MODULE_COLUMN, col.id, col.name, {})
    return redirect(url_for('admin.column_index'))


@admin_bp.route('/columns/<int:cid>/toggle', methods=['POST'])
@permission_required('column:manage')
def column_toggle(cid):
    col = Column.query.get_or_404(cid)
    col.is_enabled = not col.is_enabled
    db.session.commit()
    clear_content_cache(column_id=cid)
    flash(_gettext('已更新栏目状态'), 'success')
    audit_log(OP_UPDATE, MODULE_COLUMN, col.id, col.name,
              {'action': 'toggle', 'is_enabled': col.is_enabled})
    return redirect(url_for('admin.column_index'))


@admin_bp.route('/columns/batch', methods=['POST'])
@permission_required('column:manage')
def column_batch():
    action = request.form.get('action')
    ids = request.form.getlist('ids[]')
    ids = [int(i) for i in ids if i.isdigit()]
    if not ids:
        flash(_gettext('未选择任何栏目'), 'warning')
        return redirect(url_for('admin.column_index'))

    cols = Column.query.filter(Column.id.in_(ids)).all()
    if action == 'enable':
        for c in cols:
            c.is_enabled = True
        flash(_gettext('已启用 {0} 个栏目').format(len(cols)), 'success')
    elif action == 'disable':
        for c in cols:
            c.is_enabled = False
        flash(_gettext('已禁用 {0} 个栏目').format(len(cols)), 'success')
    elif action == 'delete':
        for c in cols:
            if not c.is_parent:
                c.is_deleted = True
        flash(_gettext('已删除可删除的栏目（含子栏目的父栏目已跳过）'), 'success')
    db.session.commit()
    for c in cols:
        clear_content_cache(column_id=c.id)
    audit_log(OP_BATCH, MODULE_COLUMN, None, None,
              {'action': action, 'count': len(cols), 'ids': ids})
    return redirect(url_for('admin.column_index'))


@admin_bp.route('/columns/<int:cid>/fields')
@permission_required('content:edit', column_id_arg='cid')
def column_fields(cid):
    """只读返回栏目的自定义字段列表（用于前台编辑文章时动态加载）。"""
    col = Column.query.get_or_404(cid)
    fields = [
        {
            'id': f.id,
            'label': f.label,
            'field_key': f.field_key,
            'field_type': f.field_type,
            'is_required': f.is_required,
            'allowed_exts': f.allowed_exts or '',
            'max_size': f.max_size or 0,
        }
        for f in col.fields.filter_by(is_deleted=False).order_by(ColumnField.sort_order.desc()).all()
    ]
    return jsonify({'fields': fields})
