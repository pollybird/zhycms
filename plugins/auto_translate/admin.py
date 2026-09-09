# -*- coding: utf-8 -*-
"""一键翻译插件：后台设置页 + 翻译 API 路由。

路由挂在核心 admin_bp 上（endpoint 归入 admin.*，自动获得后台地址前缀
即时生效机制），未启用插件时 404：
- GET/POST /<后台前缀>/auto-translate        插件设置页
- POST     /<后台前缀>/auto-translate/translate  JSON 翻译接口（供编辑页调用）
"""
from functools import wraps

from flask import render_template, redirect, url_for, request, flash, abort, jsonify

from app.extensions import db
from app.admin import admin_bp
from app.models.audit import OP_CONFIG_CHANGE
from app.models.setting import Setting
from app.utils.helpers import permission_required, audit_log
from app.plugin_system import plugin_enabled
from app.utils.i18n_content import get_default_locale

from flask_babel import gettext as _gettext

from . import service

AUDIT_MODULE = 'auto_translate'

# 可配置字段（密钥类留空 = 不修改）
_FIELDS = (
    'auto_translate_provider',
    'auto_translate_baidu_appid', 'auto_translate_baidu_secret',
    'auto_translate_youdao_key', 'auto_translate_youdao_secret',
    'auto_translate_google_key',
    'auto_translate_deepseek_key', 'auto_translate_deepseek_model',
    'auto_translate_deepseek_base_url',
)
_SECRET_FIELDS = {
    'auto_translate_baidu_secret', 'auto_translate_youdao_secret',
    'auto_translate_google_key', 'auto_translate_deepseek_key',
}
# 翻译字段白名单（防止前端提交任意内容，仅允许这些表单字段名）
_ALLOWED_FIELDS = {
    'title', 'summary', 'content', 'name', 'description', 'page_content',
    'value', 'seo_title', 'seo_keywords', 'seo_description',
    'success_message',
}
_MAX_TEXT_LEN = 200000  # 单字段原文长度上限


def _gate(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('auto_translate'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


@admin_bp.route('/auto-translate', methods=['GET', 'POST'])
@_gate
@permission_required('auto_translate:manage')
def auto_translate_index():
    if request.method == 'POST':
        action = request.form.get('action', 'save')
        if action == 'test':
            return _test_provider()
        return _save_settings()
    return render_template('auto_translate/settings.html',
                           settings=Setting.get_dict(),
                           providers=service.PROVIDERS,
                           current_provider=service.get_provider_code())


def _save_settings():
    changed = []
    for key in _FIELDS:
        val = request.form.get(key) or ''
        if key in _SECRET_FIELDS and not val:
            continue  # 密钥留空 = 不修改
        val = val.strip()
        if Setting.get(key) != val:
            Setting.set(key, val)
            changed.append(key)
    db.session.commit()
    if changed:
        audit_log(OP_CONFIG_CHANGE, AUDIT_MODULE, None, '一键翻译配置',
                  {'action': '保存配置', 'changed_keys': changed})
        flash(_gettext('翻译配置已保存，编辑页「一键翻译」即时生效'), 'success')
    else:
        flash(_gettext('未检测到改动'), 'info')
    return redirect(url_for('admin.auto_translate_index'))


def _test_provider():
    ok, msg = service.test_provider()
    flash(('✓ ' if ok else '✗ ') + msg, 'success' if ok else 'danger')
    return redirect(url_for('admin.auto_translate_index'))


@admin_bp.route('/auto-translate/translate', methods=['POST'])
@_gate
@permission_required('auto_translate:use')
def auto_translate_translate():
    """供后台编辑页调用的翻译接口。

    请求 JSON：{"target": "en", "fields": {"title": "...", "content": "..."},
                "html_fields": ["content"]}
    响应 JSON：{"ok": true, "data": {"title": "...", "content": "..."}}
                {"ok": false, "error": "原因"}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, error=_gettext('请求格式错误')), 400

    target = (data.get('target') or '').strip()
    fields = data.get('fields') or {}
    html_fields = set(data.get('html_fields') or [])
    if not target:
        return jsonify(ok=False, error=_gettext('缺少目标语言')), 400
    if not isinstance(fields, dict) or not fields:
        return jsonify(ok=False, error=_gettext('没有需要翻译的内容')), 400

    # 字段白名单 + 长度限制
    clean = {}
    for name, value in fields.items():
        if name not in _ALLOWED_FIELDS:
            continue
        text = str(value or '')
        if len(text) > _MAX_TEXT_LEN:
            text = text[:_MAX_TEXT_LEN]
        clean[name] = text
    if not clean:
        return jsonify(ok=False, error=_gettext('没有需要翻译的内容')), 400

    source = get_default_locale()
    try:
        result = service.translate_fields(clean, source, target,
                                          html_fields=html_fields)
    except service.TranslationError as e:
        return jsonify(ok=False, error=str(e)), 200
    except Exception as e:  # noqa: BLE001  兜底，避免编辑页收到 500
        return jsonify(ok=False, error=_gettext('翻译服务异常：{0}').format(e)), 200

    return jsonify(ok=True, data=result, source=source, target=target)
