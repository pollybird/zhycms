"""国际化（Flask-Babel）核心逻辑（v2.3.0 核心能力，含插件翻译域）。

- select_locale：locale 选择器，五级优先
    1) URL ?lang=xx  一次性，写回 session
    2) session['locale']
    3) cookie 'locale'
    4) Accept-Language 自动匹配可用语种
    5) Setting.i18n_default_locale 兜底（默认 zh）
- available_locales / current_locale：模板全局函数，供语言切换器渲染
- plugin_gettext / plugin_ngettext / _p：插件独立翻译域查找
    每个插件可在 plugins/<slug>/translations/<lang>/LC_MESSAGES/messages.(mo|po)
    放置自有翻译文件，核心按 locale 懒加载为 babel.support.Translations，
    查找不到时回退原文（中文）。
- register_plugin_i18n：插件系统在启动时为每个提供了 translations/
    目录的插件注册 domain + 目录元数据（请求内再按 locale 具体加载）。

设计要点：
  - i18n_enable=0（默认）时 select_locale 直接返回默认中文，不进入切换逻辑，
    保证「默认不改变现有行为」，全站渲染与 v2.2.0 一致；
  - 源代码字符串本身为中文，zh 无 .mo 时 gettext 返回 msgid（即中文），
    故 zh 无需翻译文件亦正常；en 需提供翻译。
"""
import os
import threading

from flask import request, session

# 语种显示名（扩展如 ja/ko 仅需在此追加映射）
# 用 N_ 标记以便 pybabel 抽取，运行时 _translate_label 再用 gettext 翻译实际值
from flask_babel import lazy_gettext as N_
_LOCALE_LABELS = {
    'zh': N_('中文'),
    'en': N_('English'),
    'ja': N_('日本語'),
    'ko': N_('한국어'),
}
# 保留原文字符串，运行时用这个真实原文 key（N_ 返回 lazy 字符串，会翻译，
# 因此我们把它转为 plain str 当作 msgid key 存储）
_LOCALE_LABEL_PLAIN = {
    'zh': '中文',
    'en': 'English',
    'ja': '日本語',
    'ko': '한국어',
}


def _translate_label(raw_label: str, code: str) -> str:
    """把本地 label 字符串用 gettext 翻译，保证切换到英文时 UI 不残留中文。"""
    from flask_babel import gettext as _g
    if not raw_label:
        return raw_label
    # 只要 label 含中文，就交给 gettext 翻译（含 '中文' / '日本語' 这类标签）
    if any('\u3400' <= ch <= '\u9fff' for ch in raw_label):
        return _g(raw_label)
    return raw_label

# ---- 插件翻译域注册表：{slug: (translations_dir, domain)} ----
_PLUGIN_I18N = {}
_PLUGIN_I18N_LOCK = threading.Lock()

# 请求级（per-locale）翻译实例缓存：{(locale, slug): Translations}
# 使用元组键避免不同 locale 串台；Translations 对象本身线程安全。
_t_cache = {}
_t_cache_lock = threading.Lock()


def register_plugin_i18n(slug, translations_dir, domain='messages'):
    """插件系统加载后调用：登记插件使用的翻译目录与 domain。"""
    if not slug or not translations_dir or not os.path.isdir(translations_dir):
        return
    with _PLUGIN_I18N_LOCK:
        _PLUGIN_I18N[slug] = (os.path.abspath(translations_dir), domain)


def _plugin_i18n_meta(slug):
    with _PLUGIN_I18N_LOCK:
        return _PLUGIN_I18N.get(slug)


_SENTINEL = object()


def _load_plugin_translations(slug, locale_str):
    """为 (slug, locale) 加载一个 Translations 实例，找不到返回 None。"""
    from babel.support import Translations
    meta = _plugin_i18n_meta(slug)
    if meta is None:
        return None
    i18n_dir, domain = meta
    if not os.path.isdir(i18n_dir):
        return None
    # 兼容 locale 中可能带的区域代码：en_US 先查 en_US 再退 en，反之亦然
    candidates = []
    if locale_str not in candidates:
        candidates.append(locale_str)
    if '_' in locale_str:
        base = locale_str.split('_', 1)[0]
        if base not in candidates:
            candidates.append(base)
    else:
        try:
            for name in sorted(os.listdir(i18n_dir)):
                if not os.path.isdir(os.path.join(i18n_dir, name)):
                    continue
                if name.startswith(locale_str + '_') and name not in candidates:
                    candidates.append(name)
        except OSError:
            pass
    for loc in candidates:
        mo = os.path.join(i18n_dir, loc, 'LC_MESSAGES', domain + '.mo')
        po = os.path.join(i18n_dir, loc, 'LC_MESSAGES', domain + '.po')
        fileobj = None
        fp_path = None
        try:
            if os.path.isfile(mo):
                fp_path = mo
            elif os.path.isfile(po):
                # 开发便利：mo 未编译也能工作（正式部署应 pybabel compile）
                import subprocess
                import tempfile
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mo')
                tmp.close()
                try:
                    subprocess.run(
                        ['pybabel', 'compile', '-i', po, '-o', tmp.name, '-f'],
                        check=True, capture_output=True,
                    )
                except Exception as _e:
                    last_err = _e
                    try:
                        os.unlink(tmp.name)
                    except Exception:
                        pass
                    continue
                fp_path = tmp.name
            if fp_path:
                with open(fp_path, 'rb') as fileobj:
                    tr = Translations(fileobj, domain=domain)
                return tr
        except Exception as _e:
            last_err = _e
        finally:
            if fp_path and fp_path != mo and fp_path != po and os.path.exists(fp_path):
                try:
                    os.unlink(fp_path)
                except Exception:
                    pass
    return None


def _get_plugin_t(slug, locale_str):
    """带缓存的插件 Translations 加载；返回可调用对象或 None（调用方回退原文）。"""
    key = (locale_str, slug)
    cached = _t_cache.get(key)
    if cached is not None:
        return None if cached is _SENTINEL else cached
    with _t_cache_lock:
        cached = _t_cache.get(key)
        if cached is not None:
            return None if cached is _SENTINEL else cached
        t = _load_plugin_translations(slug, locale_str)
        _t_cache[key] = t if t is not None else _SENTINEL
        return t


def plugin_gettext(slug, message):
    """按插件 slug 翻译单数字符串，未命中返回 message 原文。"""
    if not message:
        return message
    locale_str = str(current_locale()) or 'zh'
    if locale_str.startswith('zh'):
        # 中文是源语言，直接返回原文
        return message
    t = _get_plugin_t(slug, locale_str)
    if t is None:
        return message
    # 注意：babel.support.Translations 继承自 NullTranslations，
    # 不能用 isinstance(t, NullTranslations) 做有效性判断——真翻译也会被误判为无效。
    # 改为检查 t.catalog（加载了 MO 后必有 _messages 属性）或 has gettext 即可
    if not hasattr(t, 'gettext'):
        return message
    got = t.gettext(message)
    return got if got is not None else message


def plugin_ngettext(slug, singular, plural, n):
    """插件域的复数翻译。"""
    locale_str = str(current_locale()) or 'zh'
    if locale_str.startswith('zh'):
        return singular if n == 1 else plural
    t = _get_plugin_t(slug, locale_str)
    if t is None or not hasattr(t, 'ngettext'):
        return singular if n == 1 else plural
    got = t.ngettext(singular, plural, n)
    return got if got is not None else (singular if n == 1 else plural)


def _p(slug, message):
    """Jinja 全局函数：插件独立翻译域翻译（显式 slug 版）。"""
    return plugin_gettext(slug, message)


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
    return [{'code': c,
             'label': _translate_label(_LOCALE_LABEL_PLAIN.get(c, c), c),
             'active': c == cur}
            for c in codes]


def current_locale():
    """当前 locale 代码（如 'zh' / 'en'）。"""
    from flask_babel import get_locale
    try:
        loc = get_locale()
        return str(loc) if loc else 'zh'
    except Exception:
        return 'zh'


def ensure_translations_compiled():
    """启动时兜底编译核心翻译：.mo 缺失或落后于 .po 时自动生成。

    背景：`*.mo` 在 .gitignore 中不入库，正式部署用 `pybabel compile -d
    app/translations` 生成；但开发环境（run.py）若未手动编译，Flask-Babel
    运行时只加载 .mo，会导致全站 `_()` 文案回退成中文。故在 create_app 时
    做一次幂等编译。任何失败都静默跳过（gettext 回退原文，不影响启动）。
    """
    try:
        from babel.messages import mofile as _mofile, pofile as _pofile
        trans_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'translations')
        if not os.path.isdir(trans_root):
            return
        for loc in os.listdir(trans_root):
            lc_dir = os.path.join(trans_root, loc, 'LC_MESSAGES')
            if not os.path.isdir(lc_dir):
                continue
            po_path = os.path.join(lc_dir, 'messages.po')
            mo_path = os.path.join(lc_dir, 'messages.mo')
            if not os.path.isfile(po_path):
                continue
            if os.path.isfile(mo_path) and \
                    os.path.getmtime(mo_path) >= os.path.getmtime(po_path):
                continue
            with open(po_path, 'rb') as fp:
                catalog = _pofile.read_po(fp)
            with open(mo_path, 'wb') as fp:
                _mofile.write_mo(fp, catalog)
    except Exception:
        pass
