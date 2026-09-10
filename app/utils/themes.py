"""主题与模板辅助工具：管理多主题、列出可用模板、主题包上传校验。"""
import json
import os
import re
from functools import lru_cache

from flask import current_app

from ..models.setting import Setting

# 模板根目录（app/frontend/templates/themes）
THEMES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'frontend', 'templates', 'themes'
)

# 主题上传：扩展名白名单（v2.6.0 起统一定义在 app/constants.py）
from ..constants import Upload as _U

THEME_ALLOWED_EXTS = _U.THEME_EXTS
THEME_SLUG_RE = re.compile(r'^[a-zA-Z0-9_-]{2,32}$')

# 主题必备模板文件（缺一不可，否则主题不完整会在渲染时抛错）
# index: 首页 / list: 列表栏目文章列表 / article: 详情 / page: 单页 / base: 基础骨架
# 404/500/closed: 系统错误与维护页
THEME_REQUIRED_FILES = (
    'index.html', 'list.html', 'article.html', 'page.html',
    'base.html', '404.html', '500.html',
)

# manifest.json 中可选声明 template_required（自定义主题可加 form.html）；
# 校验时会把 THEME_REQUIRED_FILES ∪ manifest.template_required(若有) 合并为最终要求。

# 受保护的基础模板（不允许栏目指定）
SYSTEM_TEMPLATES = {'base', '404', '500', 'closed', 'form_closed'}


def _read_manifest(theme_dir):
    """读取主题目录的 manifest.json；失败返回 {}。"""
    mf = os.path.join(theme_dir, 'manifest.json')
    if not os.path.isfile(mf):
        return {}
    try:
        with open(mf, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def list_theme_records(active=None):
    """返回所有已发现主题的记录列表。

    每条记录: {
        slug, name, version, description, author, builtin,
        is_active: bool,
        required_files: [template_required 合并结果],
        present_required_files: [真正存在的必备模板],
        missing_required_files: [缺失的必备模板],
        template_count: .html 文件数,
        has_list_product: bool,
    }
    """
    if active is None:
        active = get_active_theme()
    records = []
    if not os.path.isdir(THEMES_DIR):
        return records
    for slug in sorted(os.listdir(THEMES_DIR)):
        d = os.path.join(THEMES_DIR, slug)
        if not os.path.isdir(d):
            continue
        mf = _read_manifest(d)
        if not isinstance(mf, dict):
            mf = {}
        # slug 以 manifest.slug 优先，否则目录名
        mf_slug = (mf.get('slug') or '').strip() or slug
        # 必备模板：基础强制 + manifest 声明的额外项
        extra = mf.get('template_required') or []
        if isinstance(extra, str):
            extra = [x.strip() for x in extra.split(',') if x.strip()]
        required = list(THEME_REQUIRED_FILES)
        for x in extra:
            if isinstance(x, str) and x and x not in required:
                required.append(x)
        present = [f for f in required if os.path.isfile(os.path.join(d, f))]
        missing = [f for f in required if f not in present]
        tpl_count = sum(1 for f in os.listdir(d) if f.endswith('.html'))
        records.append({
            'slug': mf_slug,
            'dir_name': slug,  # 目录名（与 slug 不一致时的真实路径来源）
            'name': (mf.get('name') or '').strip() or mf_slug,
            'version': (mf.get('version') or '').strip() or '-',
            'description': (mf.get('description') or '').strip(),
            'author': (mf.get('author') or '').strip(),
            'builtin': bool(mf.get('builtin')),
            'is_active': (mf_slug == active) or (slug == active),
            'required_files': required,
            'present_required_files': present,
            'missing_required_files': missing,
            'template_count': tpl_count,
            'has_list_product': os.path.isfile(os.path.join(d, 'list_product.html')),
        })
    return records

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
