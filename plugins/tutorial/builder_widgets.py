"""教程插件贡献给页面构建器的组件（v3.0.0）。

tutorial-list：按分类 slug（可选）取最新教程卡片，数据取自 Tutorial
模型；详情链接走 tutorial_frontend.tutorial_detail（/tutorials/<slug>）。
"""
from flask import url_for

from app.builder.registry import Widget
from app.constants import Builder as _B


class TutorialList(Widget):
    type = 'tutorial-list'
    category = _B.CAT_DATA
    label = '教程列表（插件）'
    icon = 'fa-graduation-cap'
    description = '教程插件数据：最新教程/课程卡片，可按分类筛选'
    scopes = (_B.SCOPE_HOME, _B.SCOPE_PAGE)
    allowed_children = ()

    default_props = {
        'category': '', 'limit': 6, 'card_cols': 3,
        'show_cover': True, 'show_summary': True, 'show_meta': True,
        'show_more': True,
    }
    prop_schema = [
        {'key': 'category', 'label': '分类标识（slug，空=全部分类）',
         'type': 'text'},
        {'key': 'limit', 'label': '显示条数', 'type': 'number'},
        {'key': 'card_cols', 'label': '每行卡片数', 'type': 'select', 'options':
         [[str(i), f'{i} 列'] for i in (2, 3, 4)]},
        {'key': 'show_cover', 'label': '显示封面', 'type': 'toggle'},
        {'key': 'show_summary', 'label': '显示简介', 'type': 'toggle'},
        {'key': 'show_meta', 'label': '显示难度/时长', 'type': 'toggle'},
        {'key': 'show_more', 'label': '显示「教程中心」入口', 'type': 'toggle'},
    ]

    def context(self, node, page_ctx):
        from .models import Tutorial, TutorialCategory

        props = node.get('props') or {}
        limit = max(int(props.get('limit') or 6), 1)
        q = Tutorial.query.filter_by(is_deleted=False, is_enabled=True)
        cat = None
        slug = (props.get('category') or '').strip()
        if slug:
            cat = TutorialCategory.query.filter_by(
                slug=slug, is_deleted=False, is_enabled=True).first()
            if cat is not None:
                q = q.filter_by(category_id=cat.id)
        tutorials = q.order_by(
            Tutorial.sort_order.desc(), Tutorial.created_at.desc()
        ).limit(limit).all()
        items = [{
            'id': t.id,
            'title': t.title,
            'summary': t.summary or '',
            'cover': t.cover or '',
            'difficulty_label': t.difficulty_label,
            'duration': t.duration or 0,
            'url': url_for('tutorial_frontend.tutorial_detail', slug=t.slug),
        } for t in tutorials]
        return {'tutorial_items': items}
