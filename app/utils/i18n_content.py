"""内容级多语言工具（v2.5.0 i18n 2.0）。

核心思想：
- 主表（articles/columns/fragments 等）保留默认语言的全部内容字段（冗余存储）。
- 非默认语言的翻译存于对应 `*_translations` 关联表。
- `t_field(obj, field)` 按当前 locale 取翻译，查不到或为空则 fallback 主表默认语言字段。
- i18n 未开启（i18n_enable != '1'）时，`t_field` 直接返回主表字段，行为与 v2.4 一致。
"""
from flask import current_app, has_app_context

from ..i18n import select_locale


def get_default_locale():
    """默认语言代码（从 Setting 读取，兜底 'zh'）。"""
    try:
        from ..models.setting import Setting
        return Setting.get('i18n_default_locale') or 'zh'
    except Exception:
        return 'zh'


def i18n_enabled():
    """内容级多语言是否开启。"""
    try:
        from ..models.setting import Setting
        return Setting.get('i18n_enable') == '1'
    except Exception:
        return False


def get_available_locales():
    """可用语言代码列表（如 ['zh', 'en']）。"""
    try:
        from ..models.setting import Setting
        raw = Setting.get('i18n_available_locales') or 'zh'
        return [c.strip() for c in raw.split(',') if c.strip()]
    except Exception:
        return ['zh']


def t_field(obj, field, locale=None):
    """取对象的多语言字段值。

    Args:
        obj: 模型实例（需有 `translations` 关系，或为普通 dict）。
        field: 字段名，如 'title' / 'content' / 'name'。
        locale: 目标语言，默认当前请求 locale。

    Returns:
        对应语言的字段值；无翻译或为空时 fallback 主表默认语言字段。
    """
    # dict 类型（如 Fragment.get_dict 返回的结构）：直接取值
    if isinstance(obj, dict):
        return obj.get(field, '')

    # i18n 未开启：直接返回主表字段
    if not i18n_enabled():
        return getattr(obj, field, None)

    target = locale or _safe_current_locale()
    default_locale = get_default_locale()

    # 目标即默认语言：直接返回主表字段
    if target == default_locale:
        return getattr(obj, field, None)

    # 查翻译表
    translations = getattr(obj, 'translations', None)
    if translations:
        # translations 可能是 list 或 Query（lazy='selectin' 时为 list）
        try:
            trans_list = list(translations)
        except TypeError:
            trans_list = translations
        for tr in trans_list:
            if getattr(tr, 'locale', None) == target:
                val = getattr(tr, field, None)
                if val not in (None, ''):
                    return val
    # fallback 主表默认语言
    return getattr(obj, field, None)


def _safe_current_locale():
    """安全获取当前 locale（直接调用 select_locale，不依赖 babel 缓存）。"""
    if has_app_context():
        try:
            return select_locale()
        except Exception:
            return get_default_locale()
    return get_default_locale()


def t(obj, field, locale=None):
    """Jinja 全局函数：t(obj, field)。

    主题模板中用法：{{ t(article, 'title') }}、{{ t(column, 'name') }}。
    与 t_field 等价，短名便于模板书写。
    """
    return t_field(obj, field, locale)


def get_translation(obj, locale):
    """取对象指定语言的翻译记录（无则返回 None）。

    供后台编辑页回填各语种翻译表单使用。
    """
    translations = getattr(obj, 'translations', None)
    if not translations:
        return None
    try:
        trans_list = list(translations)
    except TypeError:
        trans_list = translations
    for tr in trans_list:
        if getattr(tr, 'locale', None) == locale:
            return tr
    return None
