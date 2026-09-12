"""栏目业务逻辑（service 层）。

从 app/admin/content/column.py 的 _save_column / _save_column_translations /
_save_page_field_values / _save_fields / _parse_field_form 抽离而来。
"""
from flask_babel import gettext as _gettext

from ..extensions import db
from ..constants import Upload as _U
from ..models.column import Column, ColumnField, ColumnFieldValue, ColumnTranslation
from ..utils.helpers import audit_log, clear_content_cache
from ..utils.uploads import save_upload_file
from ..utils.i18n_content import get_available_locales, get_default_locale
from ..models.audit import OP_CREATE, OP_UPDATE, MODULE_COLUMN


def save_column(column, *, form_data, files_data):
    """新增或更新栏目。

    :param column: Column 实例；为 None 表示新建
    :param form_data:  表单数据（request.form）
    :param files_data: 文件数据（request.files）
    :returns: (column_or_None, messages)
    """
    messages = []

    def _flash(msg, category='info'):
        messages.append((category, msg))

    name = (form_data.get('name') or '').strip()
    slug = (form_data.get('slug') or '').strip().lower()
    parent_id = form_data.get('parent_id') or None
    col_type = form_data.get('type') or 'page'

    if not name:
        _flash(_gettext('栏目名称必填'), 'danger')
        return None, messages
    if not slug:
        _flash(_gettext('栏目标识必填'), 'danger')
        return None, messages

    # 唯一性校验
    existing = Column.query.filter_by(slug=slug, is_deleted=False).first()
    if existing and (column is None or existing.id != column.id):
        _flash(_gettext('栏目标识已存在，请更换'), 'danger')
        return None, messages

    if parent_id:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            _flash(_gettext('父栏目无效'), 'danger')
            return None, messages

        if column is not None and parent_id == column.id:
            _flash(_gettext('不能将自身设为父栏目'), 'danger')
            return None, messages

        if column is not None and parent_id in column.get_descendant_ids():
            _flash(_gettext('不能将下级栏目设为父栏目（防止循环引用）'), 'danger')
            return None, messages
    else:
        parent_id = None

    is_new = column is None
    if is_new:
        column = Column(slug=slug)

    column.name = name
    column.parent_id = parent_id
    column.type = col_type
    column.summary = (form_data.get('summary') or '').strip()
    column.sort_order = int(form_data.get('sort_order') or 0)
    column.is_enabled = (form_data.get('is_enabled') == 'on')
    # 前台会员可见性（member 插件启用时后台表单才展示本项；未启用时恒为 False）
    column.member_only = (form_data.get('member_only') == 'on')

    column.seo_title = (form_data.get('seo_title') or '').strip()
    column.seo_keywords = (form_data.get('seo_keywords') or '').strip()
    column.seo_description = (form_data.get('seo_description') or '').strip()

    # 类型专属字段
    if col_type == 'page':
        column.page_content = form_data.get('page_content') or ''
    elif col_type == 'list':
        try:
            column.page_size = int(form_data.get('page_size') or 10)
        except ValueError:
            column.page_size = 10
    elif col_type == 'link':
        column.link_url = (form_data.get('link_url') or '').strip()
        column.link_target = form_data.get('link_target') or '_self'

    # 父栏目访问模式
    column.parent_mode = form_data.get('parent_mode') or 'first_child'

    # 模板选择（留空使用默认模板）
    column.list_template = (form_data.get('list_template') or '').strip() or None
    column.detail_template = (form_data.get('detail_template') or '').strip() or None
    column.page_template = (form_data.get('page_template') or '').strip() or None

    # 自定义字段（仅叶子栏目或父栏目自身配置）
    if is_new:
        db.session.add(column)
        db.session.flush()

    _save_fields(column, form_data)

    # v2.5.0：保存各语种翻译（非默认语言）
    _save_column_translations(column, form_data)

    # 单页栏目：保存字段"值"到 ColumnFieldValue（列表栏目的字段值在文章里录入）
    if col_type == 'page':
        db.session.flush()  # 确保新字段已有 id
        if _save_page_field_values(column, form_data, files_data) is None:
            db.session.rollback()
            return None, messages

    db.session.commit()
    _flash(_gettext('栏目保存成功'), 'success')
    clear_content_cache(column_id=column.id)
    audit_log(OP_CREATE if is_new else OP_UPDATE, MODULE_COLUMN, column.id, column.name,
              {'slug': column.slug, 'type': column.type, 'parent_id': column.parent_id})
    return column, messages


def _parse_field_form(form_data):
    """从表单解析自定义字段列表（用于新增/编辑栏目）。"""
    fields = []
    raw_keys = form_data.getlist('field_key[]')
    raw_labels = form_data.getlist('field_label[]')
    raw_types = form_data.getlist('field_type[]')
    raw_required = form_data.getlist('field_required[]')
    raw_visible = form_data.getlist('field_visible[]')
    raw_exts = form_data.getlist('field_exts[]')
    raw_maxsize = form_data.getlist('field_maxsize[]')
    raw_ids = form_data.getlist('field_id[]')

    for i, key in enumerate(raw_keys):
        key = (key or '').strip()
        label = (raw_labels[i] if i < len(raw_labels) else '').strip()
        ftype = raw_types[i] if i < len(raw_types) else 'text'
        if not key or not label:
            continue
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


def _save_fields(column, form_data):
    """保存栏目的自定义字段配置。"""
    new_fields = _parse_field_form(form_data)

    # 删除不在提交列表中的旧字段（标记软删除）
    keep_ids = {f['id'] for f in new_fields if f['id']}
    for f in column.fields.all():
        if f.id not in keep_ids:
            f.is_deleted = True

    # 校验字段 key 唯一
    seen_keys = set()
    for f in new_fields:
        if f['field_key'] in seen_keys:
            # 重复 key 静默忽略
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


def _save_column_translations(column, form_data):
    """保存栏目各语种翻译（v2.5.0）。

    表单字段命名：{field}_{locale}，如 name_en / page_content_en。
    非默认语言且名称非空 → upsert 翻译记录；名称为空 → 删除该翻译。
    """
    default_locale = get_default_locale()
    locales = [l for l in get_available_locales() if l != default_locale]
    if not locales:
        return

    existing = {tr.locale: tr for tr in column.translations}
    trans_fields = ('name', 'summary', 'page_content', 'seo_title', 'seo_keywords', 'seo_description')

    for loc in locales:
        tr_name = (form_data.get(f'name_{loc}') or '').strip()
        if not tr_name:
            if loc in existing:
                db.session.delete(existing[loc])
            continue
        tr = existing.get(loc)
        if tr is None:
            tr = ColumnTranslation(column_id=column.id, locale=loc)
            db.session.add(tr)
        tr.name = tr_name
        for fld in trans_fields[1:]:
            setattr(tr, fld, (form_data.get(f'{fld}_{loc}') or '').strip())


def _save_page_field_values(column, form_data, files_data):
    """保存单页栏目自身的自定义字段值（存入 ColumnFieldValue）。

    支持 text/textarea/richtext/url/number 与 image/file 上传，
    做必填校验、旧值清理。返回 column；校验失败返回 None（由调用方回滚）。
    """
    fields = column.fields.filter_by(is_deleted=False).order_by(
        ColumnField.sort_order.desc()
    ).all()

    # 清理旧值（字段可能被删除或改动，全量重写最简单可靠）
    ColumnFieldValue.query.filter_by(column_id=column.id).delete()

    for f in fields:
        if f.field_type in ('image', 'file'):
            file_obj = files_data.get(f'field_{f.id}')
            if file_obj and file_obj.filename:
                if f.field_type == 'file':
                    allowed = f.allowed_exts.split(',') if f.allowed_exts else None
                    maxsize = f.max_size
                else:
                    allowed = list(_U.IMAGE_EXTS)
                    maxsize = None
                rel, url, err = save_upload_file(file_obj, sub_dir='column',
                                                 allowed_exts=allowed, max_size=maxsize)
                if err:
                    return None
                value = url
            elif form_data.get(f'field_{f.id}_remove') == 'on':
                value = ''
            else:
                value = (form_data.get(f'field_{f.id}_existing') or '')
        else:
            value = form_data.get(f'field_{f.id}') or ''

        if f.is_required and not value:
            return None

        if value is not None:
            db.session.add(ColumnFieldValue(
                column_id=column.id, field_id=f.id, value=value
            ))

    return column
