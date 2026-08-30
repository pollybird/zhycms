"""v2.2.0 插件管理：列表展示 + 启用/禁用（即时生效）。"""
from flask import render_template, redirect, url_for, request, flash

from ..models.audit import OP_UPDATE, MODULE_PLUGIN
from ..utils.helpers import permission_required, audit_log
from .. import plugin_system
from . import admin_bp


@admin_bp.route('/plugins')
@permission_required('system:settings')
def plugin_index():
    return render_template('admin/plugin/index.html', plugins=plugin_system.get_plugin_records())


@admin_bp.route('/plugins/<slug>/toggle', methods=['POST'])
@permission_required('system:settings')
def plugin_toggle(slug):
    rec = plugin_system.get_record(slug)
    if rec is None:
        flash('插件不存在', 'danger')
        return redirect(url_for('admin.plugin_index'))

    name = rec.name
    if plugin_system.plugin_enabled(slug):
        plugin_system.disable_plugin(slug)
        action = 'disable'
        flash(f'插件「{name}」已禁用', 'success')
    else:
        err = plugin_system.enable_plugin(slug)
        if err:
            flash(f'插件「{name}」启用失败：{err}', 'danger')
            return redirect(url_for('admin.plugin_index'))
        action = 'enable'
        flash(f'插件「{name}」已启用', 'success')

    audit_log(OP_UPDATE, MODULE_PLUGIN, target_id=slug, target_name=name,
              detail={'action': '启用' if action == 'enable' else '禁用',
                      'version': rec.version})
    return redirect(url_for('admin.plugin_index'))
