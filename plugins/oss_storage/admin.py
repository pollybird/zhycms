"""对象存储插件：后台配置页 / 连接测试 / 一键迁移路由。

挂在核心 admin_bp 上（endpoint 归入 admin.*，自动获得后台地址前缀即时
生效机制），路径 /oss-storage（实际 /<后台前缀>/oss-storage）；
未启用插件时 404。
"""
import importlib
from functools import wraps

from flask import render_template, redirect, url_for, request, flash, abort

from app.extensions import db
from app.admin import admin_bp
from app.models.audit import OP_CONFIG_CHANGE, OP_UPDATE
from app.models.setting import Setting
from app.utils.helpers import permission_required, audit_log
from app.plugin_system import plugin_enabled
from app.utils import storage as storage_mod

from . import migrate as migrate_tool

from flask_babel import gettext as _gettext

AUDIT_MODULE = 'oss_storage'

# 可配置字段（凭证 + 桶配置）
_FIELDS = (
    'oss_aliyun_access_key_id', 'oss_aliyun_access_key_secret',
    'oss_aliyun_endpoint', 'oss_aliyun_bucket', 'oss_aliyun_cdn_domain',
    'oss_tencent_secret_id', 'oss_tencent_secret_key',
    'oss_tencent_region', 'oss_tencent_bucket', 'oss_tencent_cdn_domain',
    'oss_qiniu_access_key', 'oss_qiniu_secret_key',
    'oss_qiniu_bucket', 'oss_qiniu_cdn_domain',
)
# 密钥类字段：表单留空表示不修改（保留原值）
_SECRET_FIELDS = {
    'oss_aliyun_access_key_secret',
    'oss_tencent_secret_key',
    'oss_qiniu_secret_key',
}

# 云厂商 SDK 信息（配置页展示安装状态）
_SDK_INFO = (
    ('aliyun', '阿里云 OSS', 'oss2', 'oss2'),
    ('tencent', '腾讯云 COS', 'qcloud_cos', 'cos-python-sdk-v5'),
    ('qiniu', '七牛云 Kodo', 'qiniu', 'qiniu'),
)


def _gate(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('oss_storage'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def _sdk_status():
    result = []
    for driver, label, module_name, pip_name in _SDK_INFO:
        try:
            importlib.import_module(module_name)
            installed = True
        except ImportError:
            installed = False
        result.append({'driver': driver, 'label': label,
                       'module': module_name, 'pip': pip_name,
                       'installed': installed})
    return result


@admin_bp.route('/oss-storage', methods=['GET', 'POST'])
@_gate
@permission_required('oss_storage:manage')
def oss_storage_index():
    migrate_plan = None
    if request.method == 'POST':
        action = request.form.get('action', 'save')
        if action == 'migrate_preview':
            return _migrate_preview()
        if action == 'migrate_run':
            return _migrate_run()
        return _save_settings()

    return render_template('oss_storage/settings.html',
                           settings=Setting.get_dict(),
                           current_driver=Setting.get('storage_driver', 'local'),
                           sdk_status=_sdk_status(),
                           migrate_plan=migrate_plan)


def _save_settings():
    changed = []
    for key in _FIELDS:
        val = request.form.get(key) or ''
        if key in _SECRET_FIELDS and not val:
            continue  # 密钥留空 = 不修改
        if Setting.get(key) != val:
            Setting.set(key, val)
            changed.append(key)

    new_driver = (request.form.get('storage_driver') or 'local').strip()
    if new_driver not in ('local', 'aliyun', 'tencent', 'qiniu'):
        new_driver = 'local'

    db.session.commit()

    # 切换到云端驱动前强制健康检查，失败则回退 local（凭证已保存，不丢）
    if new_driver != 'local':
        try:
            driver = storage_mod.get_driver(new_driver)
            ok, msg = driver.health_check()
        except Exception as e:
            ok, msg = False, str(e)
        if not ok:
            Setting.set('storage_driver', 'local')
            db.session.commit()
            audit_log(OP_CONFIG_CHANGE, AUDIT_MODULE, None, '对象存储配置',
                      {'action': '保存配置', 'changed_keys': changed,
                       'driver_switch_failed': new_driver})
            flash(_gettext('凭证已保存，但切换到云端驱动失败（已保持本地存储）：{0}').format(msg),
                  'danger')
            return redirect(url_for('admin.oss_storage_index'))

    if Setting.get('storage_driver', 'local') != new_driver:
        Setting.set('storage_driver', new_driver)
        db.session.commit()
        changed.append('storage_driver')

    if changed:
        audit_log(OP_CONFIG_CHANGE, AUDIT_MODULE, None, '对象存储配置',
                  {'action': '保存配置', 'changed_keys': changed,
                   'driver': new_driver})
        flash(_gettext('对象存储配置已保存，当前存储驱动：{0}').format(
            {'local': '本地磁盘', 'aliyun': '阿里云 OSS',
             'tencent': '腾讯云 COS', 'qiniu': '七牛云'}.get(new_driver, new_driver)),
            'success')
    else:
        flash(_gettext('未检测到改动'), 'info')
    return redirect(url_for('admin.oss_storage_index'))


@admin_bp.route('/oss-storage/test', methods=['POST'])
@_gate
@permission_required('oss_storage:manage')
def oss_storage_test():
    driver_name = (request.form.get('driver') or '').strip()
    if driver_name not in ('aliyun', 'tencent', 'qiniu'):
        flash(_gettext('请选择要测试的云厂商'), 'warning')
        return redirect(url_for('admin.oss_storage_index'))
    try:
        driver = storage_mod.get_driver(driver_name)
        ok, msg = driver.health_check()
    except Exception as e:
        ok, msg = False, str(e)
    flash(('✓ ' if ok else '✗ ') + msg, 'success' if ok else 'danger')
    return redirect(url_for('admin.oss_storage_index'))


def _migrate_preview():
    plan = migrate_tool.dry_run()
    audit_log(OP_UPDATE, AUDIT_MODULE, None, '迁移预览',
              {'files_total': plan['files_total'], 'url_hits': plan['url_hits']})
    return render_template('oss_storage/settings.html',
                           settings=Setting.get_dict(),
                           current_driver=Setting.get('storage_driver', 'local'),
                           sdk_status=_sdk_status(),
                           migrate_plan=plan)


def _migrate_run():
    driver_name = Setting.get('storage_driver', 'local')
    if driver_name == 'local':
        flash(_gettext('当前为本地存储驱动，请先在上方选择并保存云端驱动后再迁移'), 'warning')
        return redirect(url_for('admin.oss_storage_index'))
    try:
        driver = storage_mod.get_driver(driver_name)
        ok, msg = driver.health_check()
        if not ok:
            flash(_gettext('云端连接失败，迁移已中止：{0}').format(msg), 'danger')
            return redirect(url_for('admin.oss_storage_index'))
        stats, err = migrate_tool.run(driver)
    except Exception as e:
        stats, err = {'uploaded': 0, 'skipped': 0, 'url_rewritten': 0}, str(e)
    if err:
        audit_log(OP_UPDATE, AUDIT_MODULE, None, '本地文件迁移云端',
                  {'result': '中断', 'stats': stats, 'error': err})
        flash(_gettext('迁移中断（已上传 {0} 个文件，可修复后重新执行，已上传文件自动跳过）：{1}')
              .format(stats.get('uploaded', 0), err), 'danger')
    else:
        audit_log(OP_UPDATE, AUDIT_MODULE, None, '本地文件迁移云端',
                  {'result': '完成', 'stats': stats})
        flash(_gettext('迁移完成：上传 {0} 个文件（跳过 {1} 个本地缺失），改写 {2} 处内容 URL。'
                       '本地文件已保留，确认无误后可手工清理 uploads/ 下的日期目录（demo 目录勿删）')
              .format(stats['uploaded'], stats['skipped'], stats['url_rewritten']),
              'success')
    return redirect(url_for('admin.oss_storage_index'))
