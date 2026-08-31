"""招聘插件：前台模板函数（注册为 Jinja 全局，核心自动包裹启停守卫）。

- recruit_jobs(limit, only_open)  岗位卡片数据（首页/侧栏调用）
- recruit_job_url(job)            岗位详情 URL（伪静态开 → /job-{id}.html，
                                  关 → 动态 URL /jobs/<id>）
"""
from datetime import datetime

from flask import url_for
from flask import current_app  # noqa: F401

from app.models.setting import Setting


def recruit_job_url(job):
    """岗位详情 URL：伪静态开启用 /job-{id}.html，否则动态 URL。"""
    if Setting.get('seo_rewrite_enable') == 'on':
        return f'/job-{job.id}.html'
    try:
        return url_for('recruit_frontend.job_detail', jid=job.id)
    except Exception:
        return f'/jobs/{job.id}'


def recruit_jobs(limit=10, only_open=False):
    """岗位卡片数据（按 sort_order、发布时间倒序）。

    返回 [{id,title,department,location,headcount,salary,url,
           is_expired,deadline}]；插件未启用时守卫返回 []。
    """
    from .models import RecruitJob

    q = RecruitJob.query.filter(RecruitJob.is_deleted == False,  # noqa: E712
                                RecruitJob.is_enabled == True)   # noqa: E712
    if only_open:
        q = q.filter((RecruitJob.deadline.is_(None))
                     | (RecruitJob.deadline > datetime.now()))
    jobs = q.order_by(RecruitJob.sort_order.desc(),
                      RecruitJob.id.desc()) \
        .limit(max(int(limit or 10), 1)).all()
    return [{
        'id': j.id,
        'title': j.title,
        'department': j.department or '',
        'location': j.location or '',
        'headcount': j.headcount or 1,
        'salary': j.salary or '',
        'is_expired': j.is_expired(),
        'deadline': j.deadline.strftime('%Y-%m-%d') if j.deadline else '',
        'url': recruit_job_url(j),
    } for j in jobs]
