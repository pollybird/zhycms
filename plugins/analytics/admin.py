"""第三方统计代码插件：后台配置页。

路由挂在核心 admin_bp 上（endpoint 归入 admin.*，自动获得后台地址前缀
即时生效机制），蓝图相对路径 /analytics（实际访问 /<后台前缀>/analytics）；
未启用插件时 404（不暴露存在性）。

保存即写 Setting 并记审计，前台下一次请求即读到新值（Setting 无服务级
缓存，符合「保存即生效」语义）。
"""
from functools import wraps

from flask import render_template, redirect, url_for, request, flash, abort

from app.extensions import db
from app.admin import admin_bp
from app.models.audit import OP_CONFIG_CHANGE
from app.models.setting import Setting
from app.utils.helpers import permission_required, audit_log
from app.plugin_system import plugin_enabled

from flask_babel import gettext as _gettext
AUDIT_MODULE = 'analytics'

# 可配置的代码字段（总开关 analytics_enable 单独处理）
_FIELDS = (
    'analytics_baidu',
    'analytics_google',
    'analytics_webmaster',
    'analytics_custom_head',
    'analytics_custom_body',
)
_MAX_LEN = 20000  # 单字段长度上限（防滥用）


def _gate(view):
    """插件启用守卫：未启用 → 404。"""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('analytics'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


@admin_bp.route('/analytics', methods=['GET', 'POST'])
@_gate
@permission_required('analytics:manage')
def analytics_index():
    if request.method == 'POST':
        changed = {}
        # 总开关（on → '1'，否则 '0'）
        enable = '1' if request.form.get('analytics_enable') == 'on' else '0'
        if Setting.get('analytics_enable') != enable:
            Setting.set('analytics_enable', enable)
            changed['analytics_enable'] = enable
        # 各服务商 / 自定义代码
        for key in _FIELDS:
            val = request.form.get(key) or ''
            if len(val) > _MAX_LEN:
                flash(_gettext('{0} 长度超过上限（{1} 字符），已截断').format(key, _MAX_LEN), 'warning')
                val = val[:_MAX_LEN]
            if Setting.get(key) != val:
                Setting.set(key, val)
                changed[key] = '(代码已更新)'
        db.session.commit()
        if changed:
            audit_log(OP_CONFIG_CHANGE, AUDIT_MODULE, None, '统计代码配置',
                      {'action': '更新', 'changed_keys': list(changed.keys())})
            flash(_gettext('统计代码配置已保存，前台即时生效'), 'success')
        else:
            flash(_gettext('未检测到改动'), 'info')
        return redirect(url_for('admin.analytics_index'))
    return render_template('analytics/settings.html', settings=Setting.get_dict())
