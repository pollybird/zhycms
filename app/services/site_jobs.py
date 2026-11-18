"""站点异步任务的创建、后台执行与清理。

进度持久化在 `site_jobs` 表，多 worker 部署时任意进程都能响应轮询；
后台线程只在接收请求的进程内执行，随进程退出而结束。
"""
import json
import logging
import threading
from datetime import datetime, timedelta

from flask import current_app

from ..extensions import db
from ..models.site_job import (
    SiteJob, JOB_PENDING, JOB_RUNNING, JOB_SUCCESS, JOB_FAILED, JOB_CLONE,
)

logger = logging.getLogger(__name__)

STALE_HOURS = 1
KEEP_DAYS = 7


def create_job(job_type, site_id=0, payload=None, created_by=None):
    """创建一条 pending 任务并提交。"""
    job = SiteJob(
        site_id=site_id or 0,
        job_type=job_type,
        status=JOB_PENDING,
        progress=0,
        message='等待执行',
        payload_json=json.dumps(payload or {}, ensure_ascii=False, default=str),
        created_by=created_by,
    )
    db.session.add(job)
    db.session.commit()
    return job


def set_progress(job_id, progress=None, message=None, status=None, site_id=None):
    """更新任务进度（独立提交，供后台线程与请求线程使用）。"""
    job = db.session.get(SiteJob, job_id)
    if job is None:
        return None
    if progress is not None:
        job.progress = max(0, min(100, int(progress)))
    if message is not None:
        job.message = str(message)[:255]
    if status is not None:
        job.status = status
    if site_id is not None:
        job.site_id = site_id
    job.updated_at = datetime.now()
    db.session.commit()
    return job


def fail_job(job_id, message):
    return set_progress(job_id, status=JOB_FAILED, message=message)


def start_background(app, func, *args, **kwargs):
    """在守护线程中带应用上下文执行 func。"""
    def _runner():
        with app.app_context():
            try:
                func(*args, **kwargs)
            except Exception:
                logger.exception('站点后台任务执行失败')
            finally:
                # 线程内会话独立，结束前显式移除，避免连接泄漏
                db.session.remove()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return thread


def job_to_dict(job):
    payload = {}
    if job.payload_json:
        try:
            payload = json.loads(job.payload_json)
        except (TypeError, ValueError):
            payload = {}
    return {
        'id': job.id,
        'site_id': job.site_id,
        'job_type': job.job_type,
        'status': job.status,
        'progress': job.progress,
        'message': job.message or '',
        'created_by': job.created_by,
        'error': payload.get('error'),
        'target_site_id': payload.get('target_site_id'),
    }


def recover_stale_jobs(hours=STALE_HOURS):
    """启动时把长期未更新的运行中任务标记为失败，并清理半成品站点。"""
    cutoff = datetime.now() - timedelta(hours=hours)
    stale = SiteJob.query.filter(
        SiteJob.status.in_((JOB_PENDING, JOB_RUNNING)),
        SiteJob.updated_at < cutoff,
    ).all()
    if not stale:
        return 0

    from .site_clone import cleanup_partial_clone

    recovered = 0
    for job in stale:
        # 只有克隆任务会留下半成品站点；目标 id 优先取载荷，缺失时回落到
        # 任务记录上的站点 id（克隆过程中会写入目标站点）
        target_site_id = 0
        if job.job_type == JOB_CLONE:
            if job.payload_json:
                try:
                    target_site_id = int(
                        json.loads(job.payload_json).get('target_site_id') or 0)
                except (TypeError, ValueError):
                    target_site_id = 0
            target_site_id = target_site_id or job.site_id or 0
        if target_site_id:
            try:
                cleanup_partial_clone(target_site_id)
            except Exception as e:
                logger.warning('清理半成品站点 %s 失败：%s', target_site_id, e)
        job.status = JOB_FAILED
        job.message = '任务因进程重启或超时被标记为失败'
        job.updated_at = datetime.now()
        recovered += 1
    db.session.commit()
    if recovered:
        current_app.logger.warning('已恢复 %s 个超时的站点任务', recovered)
    return recovered


def cleanup_old_jobs(days=KEEP_DAYS):
    """清理已完成且超过保留期的任务记录。"""
    cutoff = datetime.now() - timedelta(days=days)
    count = SiteJob.query.filter(
        SiteJob.created_at < cutoff,
        SiteJob.status.in_((JOB_SUCCESS, JOB_FAILED)),
    ).delete(synchronize_session=False)
    db.session.commit()
    return count
