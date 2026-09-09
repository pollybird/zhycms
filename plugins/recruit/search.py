"""招聘插件：全站搜索内容提供者（v2.5.2）。

把 recruit_jobs / recruit_job_translations 的内容接入核心全站搜索：
  - 重建索引时产出全部启用岗位（各语言）
  - 岗位保存/删除/上下架时由 admin.py 调用核心 reindex_object/unindex_object
  - 索引后端零命中/故障时，SQL 兜底检索同样覆盖岗位
"""
from app.extensions import db
from app.utils.search import SearchProvider, _search_locale
from app.utils.i18n_content import t_field, get_default_locale


RECRUIT_TYPE = 'recruit_job'

# 搜索结果分类徽标文案（文档按 locale 生成，直接映射）
_TYPE_LABELS = {'zh': '招聘岗位'}


def _type_label(locale):
    return _TYPE_LABELS.get(locale, 'Jobs')


def _job_summary(job, locale):
    """岗位摘要：结构化字段拼接（部门 · 地点 · 薪资）。"""
    parts = [t_field(job, 'department', locale) or job.department,
             job.location, job.salary]
    return ' · '.join(p for p in parts if p)


def _job_doc(job, locale):
    """构造岗位在指定语言下的索引文档 dict（无标题返回 None）。"""
    title = t_field(job, 'title', locale) or job.title or ''
    if not title:
        return None
    return {
        'id': job.id,
        'title': title,
        'summary': _job_summary(job, locale),
        'content': t_field(job, 'description', locale) or job.description or '',
        'column_id': None,
        'column_name': _type_label(locale),
        'column_slug': '',
        'published_at': job.updated_at or job.created_at,
    }


def _job_item(job, loc):
    """构造 SQL 兜底搜索结果项。"""
    return {
        'id': job.id,
        'uid': f'{RECRUIT_TYPE}:{job.id}',
        'type': RECRUIT_TYPE,
        'title': t_field(job, 'title', loc) or job.title or '',
        'summary': _job_summary(job, loc),
        'column_id': None,
        'column_name': _type_label(loc),
        'column_slug': '',
        'published_at': job.updated_at or job.created_at,
        'url': None,
    }


class RecruitSearchProvider(SearchProvider):
    """岗位搜索提供者：索引文档产出 + SQL 兜底检索 + 结果 URL。"""

    type = RECRUIT_TYPE

    # ---- 索引 ----

    def iter_docs(self, locale):
        """重建索引：产出全部启用且未删除岗位在指定语言下的文档。"""
        from .models import RecruitJob
        jobs = RecruitJob.query.filter_by(
            is_enabled=True, is_deleted=False).all()
        for j in jobs:
            doc = _job_doc(j, locale)
            if doc:
                yield doc

    def get_doc(self, obj_id, locale):
        """单条岗位文档（实时索引用）；不存在/下架/删除返回 None。"""
        from .models import RecruitJob
        j = RecruitJob.query.filter_by(
            id=obj_id, is_enabled=True, is_deleted=False).first()
        if j is None:
            return None
        return _job_doc(j, locale)

    # ---- SQL 兜底 ----

    def sql_search(self, keyword, locale, page=1, per_page=20):
        """岗位 LIKE 检索（非默认语言同时匹配 recruit_job_translations）。"""
        from .models import RecruitJob, RecruitJobTranslation
        like = f'%{keyword}%'
        loc = _search_locale(locale)
        q = RecruitJob.query.filter(
            RecruitJob.is_deleted == False,  # noqa: E712
            RecruitJob.is_enabled == True,   # noqa: E712
        )
        main_match = db.or_(
            RecruitJob.title.like(like),
            RecruitJob.description.like(like),
            RecruitJob.department.like(like),
            RecruitJob.location.like(like),
            RecruitJob.salary.like(like),
        )
        if loc != get_default_locale():
            trans_ids = db.session.query(RecruitJobTranslation.job_id).filter(
                RecruitJobTranslation.locale == loc,
                db.or_(
                    RecruitJobTranslation.title.like(like),
                    RecruitJobTranslation.description.like(like),
                    RecruitJobTranslation.department.like(like),
                    RecruitJobTranslation.location.like(like),
                    RecruitJobTranslation.salary.like(like),
                )
            )
            q = q.filter(db.or_(RecruitJob.id.in_(trans_ids), main_match))
        else:
            q = q.filter(main_match)
        pagination = q.order_by(RecruitJob.updated_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        items = [_job_item(j, loc) for j in pagination.items]
        return items, pagination.total

    # ---- 结果 URL ----

    def build_url(self, item):
        """岗位详情 URL：伪静态开 → /job-{id}.html，否则动态路由。"""
        from flask import url_for
        from app.models.setting import Setting
        jid = item.get('id')
        if Setting.get('seo_rewrite_enable') == 'on':
            return f'/job-{jid}.html'
        try:
            return url_for('recruit_frontend.job_detail', jid=jid)
        except Exception:
            return f'/jobs/{jid}'
