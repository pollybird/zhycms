"""数据组件：与栏目/文章/碎片等真实内容绑定的动态组件。"""
from ...constants import Builder as _B
from ..registry import Widget, register_widget


def _column_by_id(column_id):
    if not column_id:
        return None
    try:
        from ...models.column import Column
        return Column.query.filter_by(
            id=int(column_id), is_deleted=False, is_enabled=True).first()
    except (TypeError, ValueError):
        return None


def _resolve_column(node, page_ctx):
    """确定文章列表绑定的栏目。"""
    bind = (node.get('props') or {}).get('bind', _B.BIND_AUTO)
    if bind == _B.BIND_AUTO:
        return page_ctx.get('column')
    return _column_by_id((node.get('props') or {}).get('column_id'))


def _query_articles(node, page_ctx, column):
    """按组件 props 取文章（同一次渲染内缓存，防多组件 N+1）。

    未解析到栏目时（首页组件、未选择栏目）回退为全站最新文章，
    使首页默认布局开箱即有内容。
    """
    props = node.get('props') or {}
    limit = int(props.get('limit') or 6)
    include_children = bool(props.get('include_children'))
    cache = page_ctx.setdefault('_qcache', {})

    if column is None:
        key = ('latest', limit)
        if key in cache:
            return cache[key]
        from ...models.article import Article
        from ...models.workflow import STATUS_PUBLISHED
        items = Article.query.filter_by(
            is_deleted=False, status=STATUS_PUBLISHED
        ).order_by(
            Article.sort_order.desc(), Article.published_at.desc()
        ).limit(limit).all()
        cache[key] = items
        return items

    key = ('articles', column.id, limit, include_children)
    if key in cache:
        return cache[key]

    from ...models.article import Article
    from ...models.workflow import STATUS_PUBLISHED
    col_ids = [column.id]
    if include_children:
        col_ids.extend(
            c.id for c in column.children.filter_by(
                is_deleted=False, is_enabled=True).all()
        )
    items = Article.query.filter(
        Article.column_id.in_(col_ids),
        Article.is_deleted == False,  # noqa: E712
        Article.status == STATUS_PUBLISHED,
    ).order_by(
        Article.sort_order.desc(), Article.published_at.desc()
    ).limit(limit).all()
    cache[key] = items
    return items


class ArticleList(Widget):
    type = 'article-list'
    category = _B.CAT_DATA
    label = '文章列表'
    icon = 'fa-newspaper'
    description = '绑定栏目文章，支持卡片/列表布局与分页'
    scopes = (_B.SCOPE_HOME, _B.SCOPE_PAGE, _B.SCOPE_LIST)
    default_props = {
        'bind': 'auto', 'column_id': None, 'include_children': False,
        'limit': 6, 'layout': 'card', 'card_cols': 3,
        'show_title': False,
        'show_cover': True, 'show_date': True, 'show_summary': True,
        'show_more': True, 'show_pagination': False,
    }
    prop_schema = [
        {'key': 'bind', 'label': '数据来源', 'type': 'select', 'options': [
            ['auto', '当前栏目（自动）'], ['select', '指定栏目'],
        ], 'help': '列表页使用「当前栏目」可一套布局复用到多个栏目'},
        {'key': 'column_id', 'label': '指定栏目', 'type': 'column'},
        {'key': 'include_children', 'label': '包含子栏目文章', 'type': 'toggle'},
        {'key': 'limit', 'label': '显示条数（不分页时生效）', 'type': 'number'},
        {'key': 'layout', 'label': '展示布局', 'type': 'select', 'options': [
            ['card', '卡片网格'], ['list', '图文列表'], ['simple', '简洁标题列表'],
        ]},
        {'key': 'show_title', 'label': '显示栏目标题（H1+简介）',
         'type': 'toggle', 'help': '对齐手写列表页的栏目标题区'},
        {'key': 'card_cols', 'label': '卡片每行数量', 'type': 'select', 'options':
         [[str(i), f'{i} 列'] for i in (2, 3, 4)]},
        {'key': 'show_cover', 'label': '显示封面', 'type': 'toggle'},
        {'key': 'show_date', 'label': '显示日期', 'type': 'toggle'},
        {'key': 'show_summary', 'label': '显示摘要', 'type': 'toggle'},
        {'key': 'show_more', 'label': '显示「更多」链接', 'type': 'toggle'},
        {'key': 'show_pagination', 'label': '启用分页（仅列表页+当前栏目）',
         'type': 'toggle'},
    ]

    def context(self, node, page_ctx):
        props = node.get('props') or {}
        column = _resolve_column(node, page_ctx)

        use_pager = (
            bool(props.get('show_pagination'))
            and page_ctx.get('scope') == _B.SCOPE_LIST
            and props.get('bind') == _B.BIND_AUTO
            and page_ctx.get('pagination') is not None
        )
        if use_pager:
            pager = page_ctx['pagination']
            articles = pager.items
            pagination = pager
        else:
            articles = _query_articles(node, page_ctx, column)
            pagination = None
        return {
            'list_column': column, 'list_articles': articles,
            'list_pagination': pagination,
        }


class ArticleDetail(Widget):
    type = 'article-detail'
    category = _B.CAT_DATA
    label = '文章正文区块'
    icon = 'fa-file-alt'
    description = '文章标题/元信息/封面/正文/上下篇复合区块'
    scopes = (_B.SCOPE_ARTICLE,)
    default_props = {
        'show_title': True, 'show_meta': True, 'show_cover': True,
        'show_content': True, 'show_fields': True, 'show_prev_next': True,
    }
    prop_schema = [
        {'key': 'show_title', 'label': '显示标题', 'type': 'toggle'},
        {'key': 'show_meta', 'label': '显示元信息（日期/栏目/浏览量）', 'type': 'toggle'},
        {'key': 'show_cover', 'label': '显示封面图', 'type': 'toggle'},
        {'key': 'show_content', 'label': '显示正文', 'type': 'toggle'},
        {'key': 'show_fields', 'label': '显示自定义字段', 'type': 'toggle'},
        {'key': 'show_prev_next', 'label': '显示上一篇/下一篇', 'type': 'toggle'},
    ]


class PageContent(Widget):
    type = 'page-content'
    category = _B.CAT_DATA
    label = '单页内容'
    icon = 'fa-file'
    description = '输出单页栏目的正文与自定义字段'
    scopes = (_B.SCOPE_PAGE,)
    default_props = {'show_title': True, 'show_content': True, 'show_fields': True}
    prop_schema = [
        {'key': 'show_title', 'label': '显示栏目标题', 'type': 'toggle'},
        {'key': 'show_content', 'label': '显示正文', 'type': 'toggle'},
        {'key': 'show_fields', 'label': '显示自定义字段', 'type': 'toggle'},
    ]


class Breadcrumb(Widget):
    type = 'breadcrumb'
    category = _B.CAT_DATA
    label = '面包屑导航'
    icon = 'fa-angle-double-right'
    description = '首页 / 栏目 / 文章 路径'
    default_props = {}
    prop_schema = []


class FragmentBlock(Widget):
    type = 'fragment'
    category = _B.CAT_DATA
    label = '全站碎片'
    icon = 'fa-puzzle-piece'
    description = '引用「碎片管理」中的内容块（下拉选择）'
    default_props = {'slug': ''}
    prop_schema = [
        {'key': 'slug', 'label': '选择碎片', 'type': 'fragment',
         'help': '内容在「内容 → 碎片管理」中维护'},
    ]

    def context(self, node, page_ctx):
        from ...models.fragment import Fragment
        slug = self.prop(node, 'slug', '')
        value = ''
        frag = Fragment.query.filter_by(
            slug=slug, is_enabled=True, is_deleted=False).first()
        if frag is not None:
            value = frag.value or ''
        return {'fragment_value': value}


class Carousel(Widget):
    type = 'carousel'
    category = _B.CAT_DATA
    label = '轮播图'
    icon = 'fa-images'
    description = '手动配置多张大图轮播（Bootstrap 轮播）'
    default_props = {
        'items': [
            {'image': '', 'title': '', 'subtitle': '', 'link': ''},
            {'image': '', 'title': '', 'subtitle': '', 'link': ''},
        ],
        'height': '420px', 'show_indicators': True, 'show_caption': True,
    }
    prop_schema = [
        {'key': 'items', 'label': '轮播项', 'type': 'repeater',
         'itemLabel': '轮播项',
         'fields': [
             {'key': 'image', 'label': '图片', 'type': 'image'},
             {'key': 'title', 'label': '标题', 'type': 'text'},
             {'key': 'subtitle', 'label': '副标题', 'type': 'text'},
             {'key': 'link', 'label': '链接', 'type': 'url'},
         ]},
        {'key': 'height', 'label': '高度', 'type': 'select', 'options': [
            ['300px', '300px'], ['420px', '420px'], ['560px', '560px'],
        ]},
        {'key': 'show_indicators', 'label': '显示指示点', 'type': 'toggle'},
        {'key': 'show_caption', 'label': '显示文字', 'type': 'toggle'},
    ]


class ContactCard(Widget):
    type = 'contact-card'
    category = _B.CAT_DATA
    label = '联系我们卡片'
    icon = 'fa-address-card'
    description = '读取「碎片管理」中的电话/邮箱/地址'
    default_props = {'title': '联系我们'}
    prop_schema = [
        {'key': 'title', 'label': '卡片标题', 'type': 'text', 'localized': True},
    ]


class CtaBanner(Widget):
    type = 'cta-banner'
    category = _B.CAT_DATA
    label = '行动号召条幅'
    icon = 'fa-bullhorn'
    description = '全宽背景条幅 + 标题 + 按钮'
    allowed_children = ()
    default_props = {
        'title': '准备好开始了吗？', 'subtitle': '立即联系我们获取专属方案',
        'button_text': '立即咨询', 'button_url': '#',
        'bg_color': '#34495e', 'text_color': '#ffffff',
    }
    prop_schema = [
        {'key': 'title', 'label': '主标题', 'type': 'text', 'localized': True},
        {'key': 'subtitle', 'label': '副标题', 'type': 'text', 'localized': True},
        {'key': 'button_text', 'label': '按钮文字', 'type': 'text', 'localized': True},
        {'key': 'button_url', 'label': '按钮链接', 'type': 'url'},
        {'key': 'bg_color', 'label': '背景色', 'type': 'color'},
        {'key': 'text_color', 'label': '文字颜色', 'type': 'color'},
    ]


class FriendLinks(Widget):
    type = 'friend-links'
    category = _B.CAT_DATA
    label = '友情链接'
    icon = 'fa-link'
    description = '友情链接插件数据（插件禁用时自动隐藏）'
    default_props = {}
    prop_schema = []


class StatNumbers(Widget):
    type = 'stat-numbers'
    category = _B.CAT_DATA
    label = '数据统计'
    icon = 'fa-chart-bar'
    description = '数字 + 标签统计条'
    default_props = {
        'bg_color': '#2c3e50', 'text_color': '#ffffff',
        'items': [
            {'number': '10+', 'label': '年行业经验'},
            {'number': '500+', 'label': '服务客户'},
        ],
    }
    prop_schema = [
        {'key': 'bg_color', 'label': '背景色', 'type': 'color'},
        {'key': 'text_color', 'label': '文字颜色', 'type': 'color'},
        {'key': 'items', 'label': '统计项', 'type': 'repeater',
         'itemLabel': '统计项',
         'fields': [
             {'key': 'number', 'label': '数字', 'type': 'text'},
             {'key': 'label', 'label': '标签', 'type': 'text'},
         ]},
    ]


for _w in (ArticleList, ArticleDetail, PageContent, Breadcrumb, FragmentBlock,
           Carousel, ContactCard, CtaBanner, FriendLinks, StatNumbers):
    register_widget(_w)
