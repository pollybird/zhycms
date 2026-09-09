# -*- coding: utf-8 -*-
"""一键翻译插件：多翻译服务商统一服务层。

统一入口：
- ``translate_fields(fields, source, target, html_fields)`` 批量翻译表单字段
- ``test_provider()`` 配置页「连接测试」

已支持服务商：
- baidu    百度通用翻译 API（APP ID + 密钥，免费额度）
- youdao   有道智云文本翻译（应用 Key + 密钥）
- google   Google Cloud Translation v2（API Key，format=html 可保留标签）
- deepseek DeepSeek 大模型（OpenAI 兼容，长文/HTML 排版保持最佳）

设计要点：
- 百度/有道单次请求有 ~6000 字节限制，长文按「块级标签 / 换行」安全边界
  切分为多片分别翻译再拼接，避免截断；
- 富文本（HTML）字段在 LLM/Google 下以 HTML 模式翻译，尽量保留标签结构；
- 所有错误统一抛 TranslationError（中文可读信息），由上层转成 JSON 响应。
"""
import hashlib
import json
import random
import re
import time
import uuid

import requests

from app.models.setting import Setting

# 服务商标识 → 中文名（配置页展示）
PROVIDERS = [
    ('baidu', '百度翻译'),
    ('youdao', '有道翻译'),
    ('google', 'Google 翻译'),
    ('deepseek', 'DeepSeek 大模型'),
]

# 单片段最大字符数（百度/有道按字节限制，这里按字符保守取值，UTF-8 下中文 3 字节）
_CHUNK_PLAIN = 1800
_CHUNK_HTML = 1800

# 目标语言代码映射：本系统 locale → 各服务商语言代码
_LANG_NAMES = {
    'en': '英语', 'ja': '日语', 'ko': '韩语', 'fr': '法语', 'de': '德语',
    'es': '西班牙语', 'ru': '俄语', 'it': '意大利语', 'pt': '葡萄牙语',
    'ar': '阿拉伯语', 'th': '泰语', 'vi': '越南语',
}
_BAIDU_LANG = {
    'zh': 'zh', 'en': 'en', 'ja': 'jp', 'ko': 'kor', 'fr': 'fra', 'de': 'de',
    'es': 'spa', 'ru': 'ru', 'it': 'it', 'pt': 'pt', 'ar': 'ara', 'th': 'th',
    'vi': 'vie',
}
_YOUDAO_LANG = {
    'zh': 'zh-CHS', 'en': 'en', 'ja': 'ja', 'ko': 'ko', 'fr': 'fr', 'de': 'de',
    'es': 'es', 'ru': 'ru', 'it': 'it', 'pt': 'pt', 'ar': 'ar', 'th': 'th',
    'vi': 'vi',
}
# Google / DeepSeek 直接使用 ISO 语言码
_ISO_LANG = {
    'zh': 'zh', 'en': 'en', 'ja': 'ja', 'ko': 'ko', 'fr': 'fr', 'de': 'de',
    'es': 'es', 'ru': 'ru', 'it': 'it', 'pt': 'pt', 'ar': 'ar', 'th': 'th',
    'vi': 'vi',
}

# 配置项默认值（DeepSeek 兼容 OpenAI 的自建/第三方网关可改 base_url）
_DEEPSEEK_DEFAULT_BASE = 'https://api.deepseek.com'
_DEEPSEEK_DEFAULT_MODEL = 'deepseek-chat'


class TranslationError(Exception):
    """翻译失败（信息可直接展示给用户）。"""


def _cfg(key, default=''):
    return Setting.get(key, default) or default


def get_provider_code():
    return (_cfg('auto_translate_provider', 'baidu') or 'baidu').strip()


def _lang_name(locale):
    return _LANG_NAMES.get(locale, locale)


def _split_text(text, html, max_len=_CHUNK_PLAIN):
    """把长文本切分为不超过 max_len 的片段，在安全边界断开。

    HTML：在块级闭合标签后断开（尽量保持标签配对）；
    纯文本：按换行断开；均保证单片长度不超过 max_len（超长再硬切）。
    """
    if not text:
        return []
    if html:
        # 在块级标签结束处断开：re.split 加捕获组会把分隔符一并保留，
        # 再把「文本 + 紧随的块级标签」拼回为完整片段
        parts = re.split(r'(</p>|</h\d>|</li>|</div>|</tr>|<br\s*/?>|<br>)', text)
        pieces = [parts[i] + (parts[i + 1] if i + 1 < len(parts) else '')
                  for i in range(0, len(parts), 2)]
    else:
        pieces = text.split('\n')
    chunks, buf = [], ''
    sep = '' if html else '\n'
    for p in pieces:
        if not p:
            continue
        if len(p) > max_len:
            # 单片仍超长：按 max_len 硬切（极端情况，一般是一整段无空格正文）
            if buf:
                chunks.append(buf)
                buf = ''
            for i in range(0, len(p), max_len):
                chunks.append(p[i:i + max_len])
            continue
        if buf and len(buf) + len(sep) + len(p) > max_len:
            chunks.append(buf)
            buf = p
        else:
            buf = buf + sep + p if buf else p
    if buf:
        chunks.append(buf)
    return chunks


# ---------------------------------------------------------------------------
# 各服务商实现
# ---------------------------------------------------------------------------

def _translate_baidu(text, src, tgt, html):
    appid = _cfg('auto_translate_baidu_appid')
    secret = _cfg('auto_translate_baidu_secret')
    if not appid or not secret:
        raise TranslationError('请先在插件设置中填写百度翻译的 APP ID 与密钥')
    to = _BAIDU_LANG.get(tgt, 'en')
    fr = _BAIDU_LANG.get(src, 'zh')
    out_parts = []
    for chunk in _split_text(text, html):
        salt = str(random.randint(32768, 65536))
        sign = hashlib.md5((appid + chunk + salt + secret).encode('utf-8')).hexdigest()
        try:
            r = requests.get(
                'https://fanyi-api.baidu.com/api/trans/vip/translate',
                params={'q': chunk, 'from': fr, 'to': to, 'appid': appid,
                        'salt': salt, 'sign': sign},
                timeout=20)
            data = r.json()
        except requests.RequestException as e:
            raise TranslationError(f'百度翻译请求失败：{e}')
        except ValueError:
            raise TranslationError('百度翻译返回了无法解析的响应')
        if 'error_code' in data:
            raise TranslationError(
                f"百度翻译错误 {data.get('error_code')}：{data.get('error_msg', '')}")
        out_parts.append(''.join(item.get('dst', '') for item in data.get('trans_result', [])))
    return ''.join(out_parts) if html else '\n'.join(out_parts)


def _translate_youdao(text, src, tgt, html):
    app_key = _cfg('auto_translate_youdao_key')
    app_secret = _cfg('auto_translate_youdao_secret')
    if not app_key or not app_secret:
        raise TranslationError('请先在插件设置中填写有道翻译的应用 Key 与密钥')
    to = _YOUDAO_LANG.get(tgt, 'en')
    fr = _YOUDAO_LANG.get(src, 'zh-CHS')
    out_parts = []
    for chunk in _split_text(text, html):
        salt = str(uuid.uuid4())
        curtime = str(int(time.time()))
        # 有道 v3 签名：input 超过 20 字符时取 前10 + 长度 + 后10
        if len(chunk) > 20:
            sign_input = chunk[:10] + str(len(chunk)) + chunk[-10:]
        else:
            sign_input = chunk
        sign_str = app_key + sign_input + salt + curtime + app_secret
        sign = hashlib.sha256(sign_str.encode('utf-8')).hexdigest()
        try:
            r = requests.post(
                'https://openapi.youdao.com/api',
                data={'q': chunk, 'from': fr, 'to': to, 'appKey': app_key,
                      'salt': salt, 'sign': sign, 'signType': 'v3',
                      'curtime': curtime},
                timeout=20)
            data = r.json()
        except requests.RequestException as e:
            raise TranslationError(f'有道翻译请求失败：{e}')
        except ValueError:
            raise TranslationError('有道翻译返回了无法解析的响应')
        if str(data.get('errorCode', '0')) != '0':
            raise TranslationError(f"有道翻译错误 {data.get('errorCode')}，请检查凭证")
        out_parts.append('\n'.join(data.get('translation', [])))
    return ''.join(out_parts) if html else '\n'.join(out_parts)


def _translate_google(text, src, tgt, html):
    key = _cfg('auto_translate_google_key')
    if not key:
        raise TranslationError('请先在插件设置中填写 Google 翻译 API Key')
    to = _ISO_LANG.get(tgt, 'en')
    fr = _ISO_LANG.get(src, 'zh')
    body = {'q': _split_text(text, html, max_len=2000), 'target': to,
            'source': fr, 'format': 'html' if html else 'text'}
    try:
        r = requests.post(
            'https://translation.googleapis.com/language/translate/v2',
            params={'key': key}, json=body, timeout=30)
        data = r.json()
    except requests.RequestException as e:
        raise TranslationError(f'Google 翻译请求失败：{e}（国内服务器可能无法直连）')
    except ValueError:
        raise TranslationError('Google 翻译返回了无法解析的响应')
    if 'error' in data:
        msg = data['error'].get('message', '未知错误')
        raise TranslationError(f'Google 翻译错误：{msg}')
    translations = data.get('data', {}).get('translations', [])
    sep = '' if html else '\n'
    return sep.join(t.get('translatedText', '') for t in translations)


def _translate_deepseek(text, src, tgt, html):
    key = _cfg('auto_translate_deepseek_key')
    if not key:
        raise TranslationError('请先在插件设置中填写 DeepSeek API Key')
    base_url = (_cfg('auto_translate_deepseek_base_url', _DEEPSEEK_DEFAULT_BASE)
                or _DEEPSEEK_DEFAULT_BASE).rstrip('/')
    model = _cfg('auto_translate_deepseek_model', _DEEPSEEK_DEFAULT_MODEL) \
        or _DEEPSEEK_DEFAULT_MODEL
    target_name = _lang_name(tgt)
    if html:
        sys_prompt = (
            f'你是专业的网站内容翻译引擎。请把用户给出的 HTML 内容翻译成{target_name}，'
            '严格保留所有 HTML 标签、标签属性与结构不变，只翻译标签内的可见文字；'
            '不要输出任何解释、Markdown 代码围栏或额外内容，直接返回翻译后的 HTML。')
    else:
        sys_prompt = (
            f'你是专业的网站内容翻译引擎。请把用户给出的文本翻译成{target_name}，'
            '不要输出任何解释或额外内容，直接返回译文。')
    try:
        r = requests.post(
            f'{base_url}/chat/completions',
            headers={'Authorization': f'Bearer {key}',
                     'Content-Type': 'application/json'},
            json={'model': model, 'temperature': 0.3,
                  'messages': [{'role': 'system', 'content': sys_prompt},
                               {'role': 'user', 'content': text}]},
            timeout=120)
    except requests.RequestException as e:
        raise TranslationError(f'DeepSeek 请求失败：{e}')
    if r.status_code != 200:
        try:
            detail = r.json().get('error', {}).get('message', r.text[:200])
        except ValueError:
            detail = r.text[:200]
        raise TranslationError(f'DeepSeek 返回错误（{r.status_code}）：{detail}')
    try:
        data = r.json()
        return data['choices'][0]['message']['content'].strip()
    except (ValueError, KeyError, IndexError):
        raise TranslationError('DeepSeek 返回了无法解析的响应')


_PROVIDER_FUNCS = {
    'baidu': _translate_baidu,
    'youdao': _translate_youdao,
    'google': _translate_google,
    'deepseek': _translate_deepseek,
}


def translate_text(text, source, target, html=False):
    """翻译单段文本。text 为空时原样返回。"""
    if not text or not str(text).strip():
        return text
    if source == target:
        return text
    provider = get_provider_code()
    func = _PROVIDER_FUNCS.get(provider)
    if func is None:
        raise TranslationError(f'未知的翻译服务商：{provider}')
    return func(str(text), source, target, bool(html))


def translate_fields(fields, source, target, html_fields=()):
    """批量翻译表单字段。

    :param fields: {字段名: 原文} 字典
    :param html_fields: 其中按 HTML（富文本）处理的字段名集合
    :return: {字段名: 译文}（仅包含实际翻译的非空字段）
    """
    result = {}
    for name, value in fields.items():
        if value is None or not str(value).strip():
            continue  # 空字段不翻译
        result[name] = translate_text(value, source, target, html=name in html_fields)
    return result


def test_provider():
    """配置页连接测试：翻译一句示例文本，返回 (ok, message)。"""
    provider = get_provider_code()
    if provider not in _PROVIDER_FUNCS:
        return False, f'未知的翻译服务商：{provider}'
    try:
        out = translate_text('一键翻译功能正常。', 'zh', 'en', html=False)
        return True, f'连接成功，测试译文：{out}'
    except TranslationError as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001  兜底，避免异常页
        return False, f'测试失败：{e}'
