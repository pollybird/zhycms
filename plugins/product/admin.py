"""产品插件：后台管理（列表 / 新增编辑 / 相册 / 规格 / 批量）。

路由挂在核心 admin_bp 上（endpoint 归入 admin.*，自动获得后台地址前缀
即时生效机制）；未启用插件时所有路由 404（不暴露存在性），菜单本就隐藏。

权限分层（与设计 §4.3 一致）：
  - product:manage    管插件入口（菜单 / 列表页可见性）
  - content:create/edit/delete/batch + 栏目绑定管栏目内增删改（与文章一致）
    因产品路由不带 cid 路径参数，栏目校验在视图内手动执行 can_access_column。
"""
import json
from functools import wraps

from flask import render_template, redirect, url_for, request, flash, abort

from app.extensions import db
from app.admin import admin_bp
from app.models.column import Column
from app.models.audit import OP_CREATE, OP_UPDATE, OP_DELETE, OP_BATCH
from app.utils.helpers import permission_required, audit_log, clear_content_cache
from app.utils.uploads import save_upload_file
from app.plugin_system import plugin_enabled

from .models import Product

from flask_babel import gettext as _gettext
AUDIT_MODULE = 'product'

_IMAGE_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp']


# ============================================================
# 守卫与小工具
# ============================================================

def _gate(view):
    """插件启用守卫：未启用 → 404。"""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('product'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def _visible_list_columns():
    """当前用户可管理的列表栏目（树序由模板缩进处理，这里按 id 排）。"""
    cols = Column.query.filter_by(type='list', is_deleted=False) \
        .order_by(Column.id).all()
    from flask_login import current_user
    if getattr(current_user, 'is_super', False):
        return cols
    allowed = current_user.get_allowed_column_ids()
    if allowed is None:
        return cols
    return [c for c in cols if c.id in allowed]


def _check_column_access(col_id):
    """视图内栏目级权限校验（超管放行）。"""
    from flask_login import current_user
    if getattr(current_user, 'is_super', False):
        return
    if not current_user.can_access_column(col_id):
        abort(403)


def _check_columns_access(col_ids):
    for cid in set(col_ids):
        _check_column_access(cid)


def _to_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _parse_specs(raw):
    """解析并规整规格参数 JSON；非法输入返回 None（由调用方 flash 提示）。"""
    raw = (raw or '').strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    result = []
    for g in data:
        if not isinstance(g, dict):
            continue
        items = []
        for it in (g.get('items') or []):
            if not isinstance(it, dict):
                continue
            name = (it.get('name') or '').strip()
            value = (it.get('value') or '').strip()
            if name:
                items.append({'name': name, 'value': value})
        group = (g.get('group') or '').strip()
        if group or items:
            result.append({'group': group, 'items': items})
    return result


def _serialize_specs(groups):
    return json.dumps(groups, ensure_ascii=False, separators=(',', ':'))


# ============================================================
# 产品列表（全局入口 + 栏目维度入口）
# ============================================================

@admin_bp.route('/products')
@_gate
@permission_required('product:manage',
                     any_of=['content:edit', 'content:create',
                             'content:delete', 'content:batch'])
def product_index():
    col = None
    cid = request.args.get('cid', type=int)
    if cid:
        col = Column.query.filter_by(id=cid, is_deleted=False).first_or_404()
        _check_column_access(col.id)

    page = max(_to_int(request.args.get('page'), 1), 1)
    keyword = (request.args.get('keyword') or '').strip()
    status = request.args.get('status', '')

    query = Product.query.filter_by(is_deleted=False)
    if col is not None:
        query = query.filter_by(column_id=col.id)
    else:
        # 非超管只看自己有权限的栏目产品
        from flask_login import current_user
        if not getattr(current_user, 'is_super', False):
            allowed = current_user.get_allowed_column_ids()
            if allowed is not None:
                query = query.filter(Product.column_id.in_(allowed or [0]))
    if keyword:
        query = query.filter(Product.title.like(f'%{keyword}%'))
    if status == 'enabled':
        query = query.filter_by(is_enabled=True)
    elif status == 'disabled':
        query = query.filter_by(is_enabled=False)

    pagination = query.order_by(
        Product.sort_order.desc(), Product.id.desc()
    ).paginate(page=page, per_page=15, error_out=False)

    return render_template(
        'product/index.html',
        products=pagination.items, pagination=pagination,
        column=col, list_columns=_visible_list_columns(),
        keyword=keyword, status=status,
    )


@admin_bp.route('/columns/<int:cid>/products')
@_gate
@permission_required('product:manage',
                     any_of=['content:edit', 'content:create',
                             'content:delete', 'content:batch'])
def product_column_index(cid):
    """栏目维度入口（同文章习惯）：转到全局列表页并锁定该栏目。"""
    Column.query.get_or_404(cid)
    return redirect(url_for('admin.product_index', cid=cid))


# ============================================================
# 新增 / 编辑
# ============================================================

@admin_bp.route('/products/create', methods=['GET', 'POST'])
@_gate
@permission_required('content:create')
def product_create():
    if request.method == 'POST':
        product = _save_product(None)
        if product is None:
            return redirect(url_for('admin.product_create',
                                    cid=request.values.get('cid', type=int)))
        return redirect(url_for('admin.product_edit', pid=product.id))
    cid = request.args.get('cid', type=int)
    pre_col = None
    if cid:
        pre_col = Column.query.filter_by(id=cid, is_deleted=False).first()
        if pre_col is not None:
            _check_column_access(pre_col.id)
    return render_template('product/form.html', product=None,
                           columns=_visible_list_columns(), pre_col=pre_col)


@admin_bp.route('/products/<int:pid>/edit', methods=['GET', 'POST'])
@_gate
@permission_required('content:edit')
def product_edit(pid):
    product = Product.query.get_or_404(pid)
    if product.is_deleted:
        abort(404)
    if request.method == 'POST':
        updated = _save_product(product)
        if updated is None:
            return redirect(url_for('admin.product_edit', pid=pid))
        return redirect(url_for('admin.product_edit', pid=pid))
    _check_column_access(product.column_id)
    return render_template('product/form.html', product=product,
                           columns=_visible_list_columns(), pre_col=None)


def _save_product(product):
    """表单保存（新增/编辑共用）。失败 flash 并返回 None。"""
    from flask_login import current_user

    is_new = product is None
    if is_new:
        product = Product()

    title = (request.form.get('title') or '').strip()
    column_id = request.form.get('column_id', type=int)
    if not title:
        flash(_gettext('标题必填'), 'danger')
        return None
    col = Column.query.filter_by(id=column_id or 0,
                                 is_deleted=False).first() if column_id else None
    if col is None or col.type != 'list':
        flash(_gettext('请选择有效的列表栏目'), 'danger')
        return None
    _check_column_access(col.id)   # 含编辑时目标栏目（换栏目即移动）
    if not is_new and product.column_id != col.id:
        _check_column_access(product.column_id)   # 原栏目也要有权限

    # ---- 相册：保留项（客户端排序后的 URL 列表）+ 新上传追加 ----
    old_urls = product.gallery_urls() if not is_new else []
    try:
        kept = json.loads(request.form.get('gallery_json') or '[]')
        kept = [u for u in kept if isinstance(u, str) and u]
    except (ValueError, TypeError):
        kept = []
    unknown = [u for u in kept if u not in old_urls]
    if unknown:
        flash(_gettext('相册数据异常（包含非本产品图片），已拒绝保存'), 'danger')
        return None

    new_urls = []
    for f in request.files.getlist('gallery_files'):
        if not f or not f.filename:
            continue
        rel, url, err = save_upload_file(f, sub_dir='product',
                                         allowed_exts=_IMAGE_EXTS)
        if err:
            flash(_gettext('相册图片上传失败：{0}').format(err), 'danger')
            return None
        new_urls.append(url)
    gallery_urls = kept + new_urls

    # ---- 封面 ----
    cover = product.cover if not is_new else None
    upload_cover = request.files.get('cover')
    if upload_cover and upload_cover.filename:
        rel, url, err = save_upload_file(upload_cover, sub_dir='product',
                                         allowed_exts=_IMAGE_EXTS)
        if err:
            flash(_gettext('封面上传失败：{0}').format(err), 'danger')
            return None
        cover = url
    elif request.form.get('cover_remove') == 'on':
        cover = None
    # 封面为空时展示层取相册第一张（cover_url()），此处不强制

    # ---- 规格参数 ----
    specs = _parse_specs(request.form.get('specs_json'))
    if specs is None:
        flash(_gettext('规格参数数据格式错误，请检查编辑器内容'), 'danger')
        return None

    product.column_id = col.id
    product.title = title
    product.summary = (request.form.get('summary') or '').strip()
    product.content = request.form.get('content') or ''
    product.cover = cover
    product.gallery = json.dumps(gallery_urls, ensure_ascii=False) \
        if gallery_urls else None
    product.specs = _serialize_specs(specs) if specs else None
    product.seo_title = (request.form.get('seo_title') or '').strip() or None
    product.seo_keywords = (request.form.get('seo_keywords') or '').strip() or None
    product.seo_description = (request.form.get('seo_description') or '').strip() or None
    product.is_enabled = (request.form.get('is_enabled') == 'on')
    product.sort_order = _to_int(request.form.get('sort_order'), 0)
    if is_new:
        product.created_by = current_user.id
        db.session.add(product)
    product.updated_by = current_user.id
    db.session.commit()

    audit_log(OP_CREATE if is_new else OP_UPDATE, AUDIT_MODULE,
              product.id, product.title,
              {'action': '产品', 'column_id': col.id,
               'gallery_count': len(gallery_urls),
               'specs_groups': len(specs)})
    clear_content_cache(column_id=col.id)
    flash(_gettext('产品已保存'), 'success')
    return product


# ============================================================
# 删除 / 批量
# ============================================================

@admin_bp.route('/products/<int:pid>/delete', methods=['POST'])
@_gate
@permission_required('content:delete')
def product_delete(pid):
    product = Product.query.get_or_404(pid)
    if product.is_deleted:
        abort(404)
    _check_column_access(product.column_id)
    product.is_deleted = True
    db.session.commit()
    audit_log(OP_DELETE, AUDIT_MODULE, pid, product.title,
              {'action': '产品', 'column_id': product.column_id})
    clear_content_cache(column_id=product.column_id)
    flash(_gettext('产品已删除（软删除，可由管理员在数据库恢复）'), 'success')
    return redirect(url_for('admin.product_index',
                            cid=product.column_id))


@admin_bp.route('/products/batch', methods=['POST'])
@_gate
@permission_required('content:batch')
def product_batch():
    action = request.form.get('action')
    ids = [int(i) for i in request.form.getlist('ids[]') if i.isdigit()]
    if not ids:
        flash(_gettext('未选择产品'), 'warning')
        return redirect(url_for('admin.product_index'))

    products = Product.query.filter(Product.id.in_(ids),
                                    Product.is_deleted == False).all()  # noqa: E712
    if not products:
        flash(_gettext('未找到可选产品'), 'warning')
        return redirect(url_for('admin.product_index'))
    _check_columns_access([p.column_id for p in products])

    col_ids = set()
    if action == 'enable':
        for p in products:
            p.is_enabled = True
            col_ids.add(p.column_id)
    elif action == 'disable':
        for p in products:
            p.is_enabled = False
            col_ids.add(p.column_id)
    elif action == 'delete':
        for p in products:
            p.is_deleted = True
            col_ids.add(p.column_id)
    elif action == 'move':
        target_id = request.form.get('target_column_id', type=int)
        target = Column.query.filter_by(id=target_id or 0, type='list',
                                        is_deleted=False).first()
        if target is None:
            flash(_gettext('目标栏目无效'), 'danger')
            return redirect(url_for('admin.product_index'))
        _check_column_access(target.id)
        for p in products:
            p.column_id = target.id
        col_ids.add(target.id)
    else:
        flash(_gettext('未知批量操作'), 'warning')
        return redirect(url_for('admin.product_index'))

    db.session.commit()
    audit_log(OP_BATCH, AUDIT_MODULE, None, None,
              {'action': f'批量{action}', 'count': len(products)})
    for cid in col_ids:
        clear_content_cache(column_id=cid)
    flash(_gettext('批量操作完成'), 'success')
    return redirect(url_for('admin.product_index'))
