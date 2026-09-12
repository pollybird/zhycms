"""v3.0.0 可视化页面构建器核心包。

- registry：组件（Widget）注册表
- schema：布局 JSON 校验
- service：页面/草稿/发布/修订业务逻辑
- renderer：布局 → 服务端 HTML 渲染（主题覆写 → 核心兜底）
"""
from .registry import (
    Widget, register_widget, get_widget, available_widget_types,
    widget_catalog, core_widget_count,
)
from .schema import validate_layout, LayoutError, normalize_layout
from .service import (
    get_or_create_page, get_published_layout, save_draft,
    publish_page, rollback_revision, init_default_layout,
    list_pages_grouped,
)
from . import widgets  # noqa: F401  触发核心组件自注册
from .renderer import render_builder_page, render_layout_html

__all__ = [
    'Widget', 'register_widget', 'get_widget', 'available_widget_types',
    'widget_catalog', 'core_widget_count',
    'validate_layout', 'LayoutError', 'normalize_layout',
    'get_or_create_page', 'get_published_layout', 'save_draft',
    'publish_page', 'rollback_revision', 'init_default_layout',
    'list_pages_grouped',
    'render_builder_page', 'render_layout_html',
]
