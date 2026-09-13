"""产品插件贡献给页面构建器的组件（v3.0.0）。

product-list：按栏目（可选，含子栏目）取最新产品卡片，数据与
list_product.html、product_latest() 同源（Product 模型，非文章）。
"""
from app.builder.registry import Widget
from app.constants import Builder as _B


class ProductList(Widget):
    type = 'product-list'
    category = _B.CAT_DATA
    label = '产品列表（插件）'
    icon = 'fa-box-open'
    description = '产品插件数据：按栏目取最新产品卡片，独立于文章体系'
    scopes = (_B.SCOPE_HOME, _B.SCOPE_PAGE, _B.SCOPE_LIST)
    allowed_children = ()

    default_props = {
        'bind': 'all', 'column_id': None, 'include_children': True,
        'limit': 8, 'card_cols': 4,
        'show_summary': False, 'show_more': True,
    }
    prop_schema = [
        {'key': 'bind', 'label': '数据来源', 'type': 'select', 'options': [
            ['all', '全站最新产品'], ['select', '指定产品栏目'],
        ]},
        {'key': 'column_id', 'label': '产品栏目', 'type': 'column'},
        {'key': 'include_children', 'label': '包含子栏目产品', 'type': 'toggle'},
        {'key': 'limit', 'label': '显示条数', 'type': 'number'},
        {'key': 'card_cols', 'label': '每行卡片数', 'type': 'select', 'options':
         [[str(i), f'{i} 列'] for i in (2, 3, 4)]},
        {'key': 'show_summary', 'label': '显示产品简介', 'type': 'toggle'},
        {'key': 'show_more', 'label': '显示「更多」链接（需指定栏目）',
         'type': 'toggle'},
    ]

    def context(self, node, page_ctx):
        from app.models.column import Column
        from .models import Product
        from .frontend import product_brief

        props = node.get('props') or {}
        limit = max(int(props.get('limit') or 8), 1)
        column = None
        if props.get('bind') == 'select':
            cid = props.get('column_id')
            try:
                column = Column.query.filter_by(
                    id=int(cid), is_deleted=False, is_enabled=True).first() \
                    if cid else None
            except (TypeError, ValueError):
                column = None

        q = Product.query.filter_by(is_enabled=True, is_deleted=False)
        if column is not None:
            col_ids = [column.id]
            if props.get('include_children'):
                col_ids.extend(
                    c.id for c in column.children.filter_by(
                        is_deleted=False, is_enabled=True).all())
            q = q.filter(Product.column_id.in_(col_ids))
        products = q.order_by(
            Product.sort_order.desc(), Product.id.desc()).limit(limit).all()
        return {
            'product_items': [product_brief(p, column) for p in products],
            'product_column': column,
        }
