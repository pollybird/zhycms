"""国际化（Flask-Babel）核心逻辑（v2.3.0 核心能力，非插件）。

- select_locale：locale 选择器，五级优先
    1) URL ?lang=xx  一次性，写回 session
    2) session['locale']
    3) cookie 'locale'
    4) Accept-Language 自动匹配可用语种
    5) Setting.i18n_default_locale 兜底（默认 zh）
- available_locales / current_locale：模板全局函数，供语言切换器渲染

设计要点：
  - i18n_enable=0（默认）时 select_locale 直接返回默认中文，不进入切换逻辑，
    保证「默认不改变现有行为」，全站渲染与 v2.2.0 一致；
  - 源代码字符串本身为中文，zh 无 .mo 时 gettext 返回 msgid（即中文），
    故 zh 无需翻译文件亦正常；en 需提供翻译。
"""
from flask import request, session


# 语种显示名（扩展如 ja/ko 仅需在此追加映射）
_LOCALE_LABELS = {
    'zh': '中文',
    'en': 'English',
    'ja': '日本語',
    'ko': '한국어',
}


def select_locale():
    """Babel locale 选择器（每请求首调一次，结果缓存于 g）。"""
    from .models.setting import Setting
    # 关闭态：全站按默认语种渲染，不读 .mo，行为同 v2.2.0
    if Setting.get('i18n_enable') != '1':
        return Setting.get('i18n_default_locale') or 'zh'

    available = [c.strip() for c in
                 (Setting.get('i18n_available_locales') or 'zh').split(',')
                 if c.strip()]
    if not available:
        return Setting.get('i18n_default_locale') or 'zh'

    # 1. URL ?lang=xx（一次性，写回 session）
    lang = request.args.get('lang')
    if lang and lang in available:
        session['locale'] = lang
        return lang
    # 2. session
    lang = session.get('locale')
    if lang and lang in available:
        return lang
    # 3. cookie
    lang = request.cookies.get('locale')
    if lang and lang in available:
        return lang
    # 4. Accept-Language 自动匹配
    best = request.accept_languages.best_match(available)
    if best:
        return best
    # 5. 默认语种兜底
    return Setting.get('i18n_default_locale') or 'zh'


def available_locales():
    """返回 [{code, label, active}] 供切换器渲染；i18n 关闭时返回 []。"""
    from .models.setting import Setting
    if Setting.get('i18n_enable') != '1':
        return []
    codes = [c.strip() for c in
             (Setting.get('i18n_available_locales') or 'zh').split(',')
             if c.strip()]
    cur = current_locale()
    return [{'code': c, 'label': _LOCALE_LABELS.get(c, c), 'active': c == cur}
            for c in codes]


def current_locale():
    """当前 locale 代码（如 'zh' / 'en'）。"""
    from flask_babel import get_locale
    try:
        loc = get_locale()
        return str(loc) if loc else 'zh'
    except Exception:
        return 'zh'
