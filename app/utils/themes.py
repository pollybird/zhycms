"""主题与模板辅助工具：管理多主题、列出可用模板。"""
import os
from functools import lru_cache

from flask import current_app

from ..models.setting import Setting

# 模板根目录（app/frontend/templates/themes）
THEMES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'frontend', 'templates', 'themes'
)

# 受保护的基础模板（不允许栏目指定）
SYSTEM_TEMPLATES = {'base', '404', '500', 'closed', 'form_closed'}

# 各栏目类型可选择的模板分类
# list: 用于列表栏目自身的列表页
# detail: 用于列表栏目下文章详情页
# page: 用于单页栏目自身的页面
TEMPLATE_CATEGORIES = {
    'list': {
        'label': '列表页模板',
        'default': 'list',
        'help': '该列表栏目展示文章列表时使用的模板',
    },
    'detail': {
        'label': '内容页模板',
        'default': 'article',
        'help': '该列表栏目下文章详情页使用的模板',
    },
    'page': {
        'label': '单页模板',
        'default': 'page',
        'help': '该单页栏目展示时使用的模板',
    },
}


def get_active_theme():
    """获取当前启用的主题名称。"""
    theme = (Setting.get('site_theme') or 'default').strip()
    # 校验主题目录存在
    if not os.path.isdir(os.path.join(THEMES_DIR, theme)):
        return 'default'
    return theme


def theme_template(template_name):
    """将模板名转换为带主题前缀的完整路径，如 'list' -> 'themes/default/list.html'。"""
    theme = get_active_theme()
    return f'themes/{theme}/{template_name}.html'


def list_themes():
    """列出所有可用主题。
    返回 [(name, name), ...]，name 即目录名。
    """
    themes = []
    if not os.path.isdir(THEMES_DIR):
        return [('default', 'default')]
    for name in sorted(os.listdir(THEMES_DIR)):
        if os.path.isdir(os.path.join(THEMES_DIR, name)):
            themes.append((name, name))
    return themes if themes else [('default', 'default')]


def list_theme_templates(theme=None, category=None):
    """列出指定主题下可选的模板。
    category: 'list' / 'detail' / 'page' / None(全部)
    返回 [(name, label), ...]
    """
    if theme is None:
        theme = get_active_theme()
    theme_dir = os.path.join(THEMES_DIR, theme)
    if not os.path.isdir(theme_dir):
        return []

    # 根据分类确定匹配模式
    if category == 'list':
        # 列表页模板：list 开头
        prefix = 'list'
    elif category == 'detail':
        # 内容页模板：article 开头
        prefix = 'article'
    elif category == 'page':
        # 单页模板：page 开头
        prefix = 'page'
    else:
        prefix = None

    templates = []
    for fname in sorted(os.listdir(theme_dir)):
        if not fname.endswith('.html'):
            continue
        name = fname[:-5]  # 去掉 .html
        if name in SYSTEM_TEMPLATES:
            continue
        if name in ('index', 'search', 'column_children', 'form'):
            continue
        if prefix and not name.startswith(prefix):
            continue
        templates.append((name, name))

    return templates


def get_column_template(column, category):
    """获取栏目的指定模板，未设置则返回默认值。
    category: 'list' / 'detail' / 'page'
    """
    default = TEMPLATE_CATEGORIES[category]['default']
    if column is None:
        return default

    field_map = {
        'list': 'list_template',
        'detail': 'detail_template',
        'page': 'page_template',
    }
    value = getattr(column, field_map[category], None)
    if not value or not value.strip():
        return default

    # 校验模板文件存在
    theme = get_active_theme()
    template_path = os.path.join(THEMES_DIR, theme, f'{value.strip()}.html')
    if not os.path.isfile(template_path):
        return default

    return value.strip()
