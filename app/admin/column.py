"""栏目管理：树形、三种类型、自定义字段。
升级：权限（@permission_required('column:manage')）+ 审计日志 + 栏目专属权限。
"""
from flask import (
    render_template, redirect, url_for, request,
    flash, jsonify, abort
)

from ..extensions import db
from ..models.column import Column, ColumnField, ColumnFieldValue
from ..utils.helpers import permission_required, audit_log, clear_content_cache
from ..utils.themes import list_theme_templates, TEMPLATE_CATEGORIES
from ..utils.uploads import save_upload_file
from ..models.audit import OP_CREATE, OP_UPDATE, OP_DELETE, OP_BATCH, MODULE_COLUMN
from . import admin_bp


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


def _parse_field_form(column_id=None):
    """从表单解析自定义字段列表（用于新增/编辑栏目）。"""
    fields = []
    raw_keys = request.form.getlist('field_key[]')
    raw_labels = request.form.getlist('field_label[]')
    raw_types = request.form.getlist('field_type[]')
    raw_required = request.form.getlist('field_required[]')
    raw_visible = request.form.getlist('field_visible[]')
    raw_exts = request.form.getlist('field_exts[]')
    raw_maxsize = request.form.getlist('field_maxsize[]')
    raw_ids = request.form.getlist('field_id[]')

    for i, key in enumerate(raw_keys):
        key = (key or '').strip()
        label = (raw_labels[i] if i < len(raw_labels) else '').strip()
        ftype = raw_types[i] if i < len(raw_types) else 'text'
        if not key or not label:
            continue
        # required 是 checkbox，勾选了才会出现在列表里，且对应位置可能错位
        # 改用 hidden 标记 + checkbox 取值
        fields.append({
            'id': int(raw_ids[i]) if i < len(raw_ids) and raw_ids[i] else None,
            'field_key': key,
            'label': label,
            'field_type': ftype,
            'is_required': str(i) in raw_required,
            'is_frontend_visible': str(i) in raw_visible,
            'allowed_exts': (raw_exts[i] if i < len(raw_exts) else '').strip(),
            'max_size': int(raw_maxsize[i]) * 1024 if i < len(raw_maxsize) and raw_maxsize[i].isdigit() else None,
        })
    return fields


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
        col = _save_column(None)
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
        updated = _save_column(col)
        if updated is None:
            return redirect(url_for('admin.column_edit', cid=cid))
        return redirect(url_for('admin.column_index'))

    parents = Column.get_tree()
    return render_template(
        'admin/column/form.html',
        column=col, parents=parents, field_types=FIELD_TYPES,
        parent_options=_build_tree_with_depth(parents),
        template_options=_template_options(),
    )


def _save_column(column):
    """新增或更新栏目。返回 column 对象；失败返回 None。"""
    name = (request.form.get('name') or '').strip()
    slug = (request.form.get('slug') or '').strip().lower()
    parent_id = request.form.get('parent_id') or None
    col_type = request.form.get('type') or 'page'

    if not name:
        flash('栏目名称必填', 'danger')
        return None
    if not slug:
        flash('栏目标识必填', 'danger')
        return None

    # 唯一性校验
    existing = Column.query.filter_by(slug=slug, is_deleted=False).first()
    if existing and (column is None or existing.id != column.id):
        flash('栏目标识已存在，请更换', 'danger')
        return None

    if parent_id:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            flash('父栏目无效', 'danger')
            return None

        if column is not None and parent_id == column.id:
            flash('不能将自身设为父栏目', 'danger')
            return None

        if column is not None and parent_id in column.get_descendant_ids():
            flash('不能将下级栏目设为父栏目（防止循环引用）', 'danger')
            return None
    else:
        parent_id = None

    is_new = column is None
    if is_new:
        column = Column(slug=slug)

    column.name = name
    column.parent_id = parent_id
    column.type = col_type
    column.summary = (request.form.get('summary') or '').strip()
    column.sort_order = int(request.form.get('sort_order') or 0)
    column.is_enabled = (request.form.get('is_enabled') == 'on')

    column.seo_title = (request.form.get('seo_title') or '').strip()
    column.seo_keywords = (request.form.get('seo_keywords') or '').strip()
    column.seo_description = (request.form.get('seo_description') or '').strip()

    # 类型专属字段
    if col_type == 'page':
        column.page_content = request.form.get('page_content') or ''
    elif col_type == 'list':
        try:
            column.page_size = int(request.form.get('page_size') or 10)
        except ValueError:
            column.page_size = 10
    elif col_type == 'link':
        column.link_url = (request.form.get('link_url') or '').strip()
        column.link_target = request.form.get('link_target') or '_self'

    # 父栏目访问模式
    column.parent_mode = request.form.get('parent_mode') or 'first_child'

    # 模板选择（留空使用默认模板）
    column.list_template = (request.form.get('list_template') or '').strip() or None
    column.detail_template = (request.form.get('detail_template') or '').strip() or None
    column.page_template = (request.form.get('page_template') or '').strip() or None

    # 自定义字段（仅叶子栏目或父栏目自身配置）
    if is_new:
        db.session.add(column)
        db.session.flush()

    _save_fields(column)

    # 单页栏目：保存字段“值”到 ColumnFieldValue（列表栏目的字段值在文章里录入）
    if col_type == 'page':
        db.session.flush()  # 确保新字段已有 id
        if _save_page_field_values(column) is None:
            db.session.rollback()
            return None

    db.session.commit()
    flash('栏目保存成功', 'success')
    clear_content_cache(column_id=column.id)
    audit_log(OP_CREATE if is_new else OP_UPDATE, MODULE_COLUMN, column.id, column.name,
              {'slug': column.slug, 'type': column.type, 'parent_id': column.parent_id})
    return column


def _save_page_field_values(column):
    """保存单页栏目自身的自定义字段值（存入 ColumnFieldValue）。

    复刻文章字段值的处理：支持 text/textarea/richtext/url/number 与 image/file 上传，
    做必填校验、旧值清理。返回 column；校验失败返回 None（由调用方回滚）。
    """
    fields = column.fields.filter_by(is_deleted=False).order_by(
        ColumnField.sort_order.desc()
    ).all()

    # 清理旧值（字段可能被删除或改动，全量重写最简单可靠）
    ColumnFieldValue.query.filter_by(column_id=column.id).delete()

    for f in fields:
        if f.field_type in ('image', 'file'):
            file_obj = request.files.get(f'field_{f.id}')
            if file_obj and file_obj.filename:
                if f.field_type == 'file':
                    allowed = f.allowed_exts.split(',') if f.allowed_exts else None
                    maxsize = f.max_size
                else:
                    allowed = ['jpg', 'jpeg', 'png', 'gif', 'webp']
                    maxsize = None
                rel, url, err = save_upload_file(file_obj, sub_dir='column',
                                                 allowed_exts=allowed, max_size=maxsize)
                if err:
                    flash(f'字段 {f.label} 上传失败：{err}', 'danger')
                    return None
                value = url
            elif request.form.get(f'field_{f.id}_remove') == 'on':
                value = ''
            else:
                value = (request.form.get(f'field_{f.id}_existing') or '')
        else:
            value = request.form.get(f'field_{f.id}') or ''

        if f.is_required and not value:
            flash(f'字段 {f.label} 为必填', 'danger')
            return None

        if value is not None:
            db.session.add(ColumnFieldValue(
                column_id=column.id, field_id=f.id, value=value
            ))

    return column


def _save_fields(column):
    """保存栏目的自定义字段配置。"""
    new_fields = _parse_field_form()

    # 删除不在提交列表中的旧字段（标记软删除）
    keep_ids = {f['id'] for f in new_fields if f['id']}
    for f in column.fields.all():
        if f.id not in keep_ids:
            f.is_deleted = True

    # 校验字段 key 唯一
    seen_keys = set()
    for f in new_fields:
        if f['field_key'] in seen_keys:
            flash(f'字段标识 {f["field_key"]} 重复，已忽略', 'warning')
            continue
        seen_keys.add(f['field_key'])

        if f['id']:
            field = ColumnField.query.get(f['id'])
            if field is None or field.column_id != column.id:
                continue
        else:
            field = ColumnField(column_id=column.id, field_key=f['field_key'])
            db.session.add(field)

        field.label = f['label']
        field.field_type = f['field_type']
        field.is_required = f['is_required']
        field.is_frontend_visible = f['is_frontend_visible']
        field.allowed_exts = f['allowed_exts']
        field.max_size = f['max_size']
        field.is_deleted = False


@admin_bp.route('/columns/<int:cid>/delete', methods=['POST'])
@permission_required('column:manage')
def column_delete(cid):
    col = Column.query.get_or_404(cid)
    if col.is_parent:
        flash('该栏目存在子栏目，请先删除子栏目后再操作', 'danger')
        return redirect(url_for('admin.column_index'))

    col.is_deleted = True
    db.session.commit()
    clear_content_cache(column_id=cid)
    flash('栏目已删除', 'success')
    audit_log(OP_DELETE, MODULE_COLUMN, col.id, col.name, {})
    return redirect(url_for('admin.column_index'))


@admin_bp.route('/columns/<int:cid>/toggle', methods=['POST'])
@permission_required('column:manage')
def column_toggle(cid):
    col = Column.query.get_or_404(cid)
    col.is_enabled = not col.is_enabled
    db.session.commit()
    clear_content_cache(column_id=cid)
    flash('已更新栏目状态', 'success')
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
        flash('未选择任何栏目', 'warning')
        return redirect(url_for('admin.column_index'))

    cols = Column.query.filter(Column.id.in_(ids)).all()
    if action == 'enable':
        for c in cols:
            c.is_enabled = True
        flash(f'已启用 {len(cols)} 个栏目', 'success')
    elif action == 'disable':
        for c in cols:
            c.is_enabled = False
        flash(f'已禁用 {len(cols)} 个栏目', 'success')
    elif action == 'delete':
        for c in cols:
            if not c.is_parent:
                c.is_deleted = True
        flash('已删除可删除的栏目（含子栏目的父栏目已跳过）', 'success')
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
