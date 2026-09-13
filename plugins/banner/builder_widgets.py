"""轮播图插件贡献给页面构建器的组件（v3.0.0）。

banner-hero：读取「轮播管理」中指定分组（默认 home-hero）的生效图片，
数据模型与手写模板 include 的 banner/hero_carousel.html 完全同源，
插件禁用时构建器自动门控（生产空占位、预览标红）。
"""
from app.builder.registry import Widget
from app.constants import Builder as _B


class BannerHero(Widget):
    type = 'banner-hero'
    category = _B.CAT_DATA
    label = '轮播图（插件分组）'
    icon = 'fa-images'
    description = '读取轮播图插件分组的大图轮播（数据在「轮播管理」维护）'
    scopes = (_B.SCOPE_HOME, _B.SCOPE_PAGE)
    allowed_children = ()

    default_props = {
        'group': 'home-hero', 'height': '420px',
        'show_caption': True, 'autoplay': True,
    }
    prop_schema = [
        {'key': 'group', 'label': '轮播分组标识', 'type': 'text',
         'help': '与后台「轮播管理」的分组 slug 一致，默认首页位 home-hero'},
        {'key': 'height', 'label': '高度', 'type': 'select', 'options': [
            ['300px', '300px'], ['420px', '420px'], ['560px', '560px'],
        ]},
        {'key': 'show_caption', 'label': '显示图片标题', 'type': 'toggle'},
        {'key': 'autoplay', 'label': '自动播放（5 秒切换）', 'type': 'toggle'},
    ]

    def context(self, node, page_ctx):
        from .frontend import banner_items
        group = self.prop(node, 'group', 'home-hero') or 'home-hero'
        return {'hero_banners': banner_items(group)}
