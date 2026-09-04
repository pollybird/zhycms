"""模块4：系统运维与备份 —— 手动备份、定时备份配置、恢复、下载、系统监控。"""
import os
from datetime import datetime

from flask import (
    render_template, redirect, url_for, request, flash, abort,
    send_file, current_app, jsonify
)
from flask_babel import gettext as _gettext
from flask_login import current_user

from ..extensions import db
from ..models.backup import BackupRecord, TRIGGER_MANUAL, TRIGGER_SCHEDULED
from ..models.setting import Setting
from ..utils.helpers import permission_required, audit_log
from ..utils.backup_utils import (
    create_backup, restore_backup, system_monitor_stats, run_scheduled_backup,
)
from ..utils.uploads import save_upload_file
from ..models.audit import (
    OP_BACKUP_CREATE, OP_BACKUP_RESTORE, OP_DELETE, OP_EXPORT, MODULE_BACKUP, OP_UPDATE,
)
from . import admin_bp


# ============================================================
# 备份列表与操作
# ============================================================

@admin_bp.route('/backups')
@permission_required('system:backup')
def backup_index():
    page = max(int(request.args.get('page', 1)), 1)
    status_filter = request.args.get('status', '')
    trigger_filter = request.args.get('trigger', '')

    query = BackupRecord.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    if trigger_filter:
        query = query.filter_by(trigger=trigger_filter)

    pagination = query.order_by(BackupRecord.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    stats = system_monitor_stats()

    settings = Setting.get_dict()
    # 尝试读取定时备份配置
    schedule_settings = {
        'backup_enable_scheduled': settings.get('backup_enable_scheduled', 'off'),
        'backup_schedule_mode': settings.get('backup_schedule_mode', 'daily'),
        'backup_schedule_time': settings.get('backup_schedule_time', '03:00'),
        'backup_keep_days': settings.get('backup_keep_days', '30'),
        'backup_auto_clean': settings.get('backup_auto_clean', 'on'),
    }
    return render_template(
        'admin/backup/index.html',
        backups=pagination.items, pagination=pagination,
        status_filter=status_filter, trigger_filter=trigger_filter,
        stats=stats, schedule_settings=schedule_settings,
    )


@admin_bp.route('/backup/manual', methods=['POST'])
@permission_required('system:backup')
def backup_manual():
    """一键手动备份。"""
    remark = (request.form.get('remark') or '').strip()
    record, err = create_backup(trigger=TRIGGER_MANUAL, remark=remark,
                                created_by=getattr(current_user, 'id', None))
    if err:
        flash(_gettext('备份失败：{0}').format(err), 'danger')
        audit_log(OP_BACKUP_CREATE, MODULE_BACKUP, None, None,
                  {'status': 'failed', 'error': str(err)})
    else:
        size_mb = (record.file_size or 0) / 1024 / 1024
        flash(_gettext('备份成功：{0}（{1:.2f} MB）').format(record.filename, size_mb), 'success')
        audit_log(OP_BACKUP_CREATE, MODULE_BACKUP, record.id, record.filename,
                  {'file_size_mb': round(size_mb, 2), 'remark': remark})
    return redirect(url_for('admin.backup_index'))


@admin_bp.route('/backups/<int:bid>/download')
@permission_required('system:backup')
def backup_download(bid):
    record = BackupRecord.query.get_or_404(bid)
    if record.status != 'ok':
        flash(_gettext('该备份文件状态异常，无法下载'), 'warning')
        return redirect(url_for('admin.backup_index'))
    path = record.abs_path
    if not os.path.isfile(path):
        flash(_gettext('备份文件不存在（可能已被清理或手动删除）'), 'danger')
        return redirect(url_for('admin.backup_index'))
    audit_log(OP_EXPORT, MODULE_BACKUP, record.id, record.filename,
              {'action': 'download'})
    return send_file(path, as_attachment=True, download_name=record.filename)


@admin_bp.route('/backups/<int:bid>/restore', methods=['POST'])
@permission_required('system:backup')
def backup_restore(bid):
    """一键恢复已有备份记录。"""
    if not current_user.is_super:
        abort(403)
    record = BackupRecord.query.get_or_404(bid)
    if record.status != 'ok':
        flash(_gettext('该备份文件状态异常，无法恢复'), 'danger')
        return redirect(url_for('admin.backup_index'))
    # 二次确认
    confirm = request.form.get('confirm') == 'YES_I_UNDERSTAND'
    if not confirm:
        flash(_gettext('请先勾选「我已清楚：恢复将覆盖现有数据库」再操作'), 'warning')
        return redirect(url_for('admin.backup_index'))
    # 恢复会 DROP 重建 backup_records 表：本条记录（及之后新增的记录）会随
    # 快照消失，恢复后访问 record.* 属性会抛 ObjectDeletedError，须提前取值
    rec_id = record.id
    rec_filename = record.filename
    try:
        ok, msg = restore_backup(record)
        if ok:
            flash(_gettext('恢复成功：{0}。{1}').format(rec_filename, msg), 'success')
            audit_log(OP_BACKUP_RESTORE, MODULE_BACKUP, rec_id, rec_filename,
                      {'status': 'success'})
        else:
            flash(_gettext('恢复失败：{0}').format(msg), 'danger')
            audit_log(OP_BACKUP_RESTORE, MODULE_BACKUP, rec_id, rec_filename,
                      {'status': 'failed', 'error': msg})
    except Exception as e:
        current_app.logger.exception('restore failed')
        flash(_gettext('恢复异常：{0}').format(e), 'danger')
        audit_log(OP_BACKUP_RESTORE, MODULE_BACKUP, rec_id, rec_filename,
                  {'status': 'error', 'error': str(e)})
    return redirect(url_for('admin.backup_index'))


@admin_bp.route('/backups/restore-upload', methods=['POST'])
@permission_required('system:backup')
def backup_restore_upload():
    """上传备份文件后恢复。"""
    if not current_user.is_super:
        abort(403)
    f = request.files.get('backup_file')
    confirm = request.form.get('confirm_upload') == 'YES_I_UNDERSTAND'
    if not f or not f.filename:
        flash(_gettext('请先选择备份文件（.sql.gz 或 .json.gz）'), 'warning')
        return redirect(url_for('admin.backup_index'))
    if not confirm:
        flash(_gettext('请先勾选「我已清楚：恢复将覆盖现有数据库」再操作'), 'warning')
        return redirect(url_for('admin.backup_index'))
    # 保存到 backups 临时目录
    name = f.filename.lower()
    allowed = ('.sql.gz', '.json.gz', '.gz', '.sql', '.json')
    if not any(name.endswith(ext) for ext in allowed):
        flash(_gettext('仅支持 .sql.gz / .json.gz / .gz / .sql / .json 备份文件'), 'danger')
        return redirect(url_for('admin.backup_index'))
    # 备份恢复文件必须留本地磁盘（恢复逻辑直接读本地路径），强制 local 驱动
    rel, url, err = save_upload_file(f, sub_dir='backup_temp', allowed_exts=['gz', 'sql', 'json'],
                                     storage_scope='local')
    if err:
        flash(_gettext('文件保存失败：{0}').format(err), 'danger')
        return redirect(url_for('admin.backup_index'))
    abs_path = os.path.join(current_app.config.get('UPLOAD_FOLDER') or
                            os.path.join(os.path.dirname(os.path.dirname(current_app.instance_path)),
                                         'app', 'static', 'uploads'),
                            'backup_temp', rel.split('/')[-1]) if not os.path.isabs(rel) else rel
    # save_upload_file 返回的 rel 是相对 URL，我们需要实际文件路径：简单处理——在备份目录中直接落一份副本
    import uuid
    backup_dir = current_app.config.get('BACKUP_FOLDER') or os.path.join(
        current_app.instance_path, 'backups'
    )
    os.makedirs(backup_dir, exist_ok=True)
    temp_name = f'uploaded_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{uuid.uuid4().hex[:6]}.{name.rsplit(".", 1)[-1]}'
    temp_path = os.path.join(backup_dir, temp_name)
    f.seek(0)
    with open(temp_path, 'wb') as out:
        out.write(f.read())
    try:
        ok, msg = restore_backup(temp_path)
        if ok:
            flash(_gettext('上传备份恢复成功。{0}').format(msg), 'success')
            audit_log(OP_BACKUP_RESTORE, MODULE_BACKUP, None, temp_name,
                      {'status': 'success', 'from': 'upload'})
        else:
            flash(_gettext('恢复失败：{0}').format(msg), 'danger')
            audit_log(OP_BACKUP_RESTORE, MODULE_BACKUP, None, temp_name,
                      {'status': 'failed', 'error': msg, 'from': 'upload'})
    except Exception as e:
        current_app.logger.exception('upload restore failed')
        flash(_gettext('恢复异常：{0}').format(e), 'danger')
    finally:
        # 清理临时文件
        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
    return redirect(url_for('admin.backup_index'))


@admin_bp.route('/backups/<int:bid>/delete', methods=['POST'])
@permission_required('system:backup')
def backup_delete(bid):
    """手动删除单条备份记录 + 物理文件。"""
    record = BackupRecord.query.get_or_404(bid)
    # 先删物理文件
    try:
        path = record.abs_path
        if os.path.isfile(path):
            os.remove(path)
    except Exception as e:
        current_app.logger.exception('backup file delete failed')
        flash(_gettext('物理文件删除失败：{0}').format(e), 'warning')
    db.session.delete(record)
    db.session.commit()
    flash(_gettext('备份记录已删除'), 'success')
    audit_log(OP_DELETE, MODULE_BACKUP, record.id, record.filename, {})
    return redirect(url_for('admin.backup_index'))


# ============================================================
# 定时备份配置保存
# ============================================================

@admin_bp.route('/settings/backup', methods=['POST'])
@permission_required('system:backup')
def setting_backup_save():
    """保存备份周期配置。"""
    Setting.set('backup_enable_scheduled', request.form.get('backup_enable_scheduled') or 'off')
    Setting.set('backup_schedule_mode', request.form.get('backup_schedule_mode') or 'daily')
    time_val = (request.form.get('backup_schedule_time') or '03:00').strip()
    try:
        # 校验格式 HH:MM
        hh, mm = time_val.split(':')
        if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            raise ValueError
        Setting.set('backup_schedule_time', time_val)
    except Exception:
        flash(_gettext('备份时间格式应为 HH:MM（00:00-23:59），已回退为 03:00'), 'warning')
        Setting.set('backup_schedule_time', '03:00')
    try:
        keep_days = int(request.form.get('backup_keep_days') or 30)
        if keep_days < 0:
            keep_days = 30
        Setting.set('backup_keep_days', str(keep_days))
    except ValueError:
        Setting.set('backup_keep_days', '30')
    Setting.set('backup_auto_clean', request.form.get('backup_auto_clean') or 'off')
    db.session.commit()

    # 尝试动态重设定时任务（如果调度器已启动）
    try:
        from ..extensions import get_scheduler
        sched = get_scheduler()
        if sched is not None:
            from apscheduler.triggers.cron import CronTrigger
            hh_mm = Setting.get('backup_schedule_time', '03:00').split(':')
            hh, mm = int(hh_mm[0]), int(hh_mm[1])
            job_id = 'zhycms_backup'
            if sched.get_job(job_id):
                sched.remove_job(job_id)
            if Setting.get('backup_enable_scheduled') == 'on':
                mode = Setting.get('backup_schedule_mode', 'daily')
                if mode == 'weekly':
                    trigger = CronTrigger(day_of_week='mon', hour=hh, minute=mm, timezone='Asia/Shanghai')
                else:
                    trigger = CronTrigger(hour=hh, minute=mm, timezone='Asia/Shanghai')
                sched.add_job(run_scheduled_backup, trigger, id=job_id, replace_existing=True,
                              misfire_grace_time=3600, coalesce=True, max_instances=1)
    except Exception:
        current_app.logger.exception('reschedule backup job failed')

    flash(_gettext('备份运维配置已保存，定时任务即时更新'), 'success')
    audit_log(OP_UPDATE, MODULE_BACKUP, None, None,
              {'action': 'update_schedule',
               'enable': Setting.get('backup_enable_scheduled'),
               'mode': Setting.get('backup_schedule_mode'),
               'time': Setting.get('backup_schedule_time')})
    return redirect(url_for('admin.backup_index'))


# ============================================================
# 系统监控（JSON接口 + 展示页）
# ============================================================

@admin_bp.route('/monitor')
@permission_required('system:backup')
def monitor_index():
    """系统监控页：服务器/磁盘/数据库状态。"""
    import platform, sys as _sys, time as _time, os as _os
    from ..config import BASE_DIR
    stats = system_monitor_stats()

    # 服务器信息
    sys_info = {
        'os': f"{platform.system()} {platform.release()}",
        'python': platform.python_version(),
        'timezone': getattr(_os, 'environ', {}).get('TZ', 'UTC'),
        'requests': getattr(_sys, '_zhy_request_count', 0),
        'server_software': _os.environ.get('SERVER_SOFTWARE', '-'),
        'wsgi': getattr(_sys, 'WSGI_SERVER', '-'),
        'pid': _os.getpid(),
    }

    # 运行时长
    uptime = stats.get('uptime_seconds', 0)
    runtime = type('Runtime', (), {
        'days': int(uptime // 86400),
        'hours': int((uptime % 86400) // 3600),
        'minutes': int((uptime % 3600) // 60),
    })()

    # 磁盘信息
    disk_info = {
        'project_path': BASE_DIR,
        'total': f"{stats.get('disk_total_gb', 0)} GB",
        'used': f"{stats.get('disk_used_gb', 0)} GB",
        'free': f"{stats.get('disk_free_gb', 0)} GB",
        'percent': stats.get('disk_used_pct', 0),
    }

    # 数据库信息
    from ..utils.backup_utils import _db_type_and_path
    try:
        db_type, db_name = _db_type_and_path()[:2]
    except Exception:
        db_type, db_name = 'unknown', '-'
    db_info = {
        'driver': db_type,
        'name': db_name,
        'size': f"{stats.get('db_size_mb', 0)} MB",
        'ok': stats.get('db_alive', False),
    }

    return render_template('admin/backup/monitor.html', stats=stats,
                           sys_info=sys_info, runtime=runtime,
                           disk_info=disk_info, db_info=db_info,
                           cms_version=Setting.CMS_VERSION)


@admin_bp.route('/api/monitor')
@permission_required('system:backup')
def monitor_api():
    return jsonify(system_monitor_stats())
