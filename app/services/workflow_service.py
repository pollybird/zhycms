"""文章发布工作流状态机（service 层）。

从 app/admin/content/article.py 的五个状态流转视图
（submit_review / review_pass / review_reject / publish / archive）抽离而来：

  - 状态迁移规则、栏目级权限（can_review / can_publish）、驳回原因必填等
    业务规则集中在此，视图层不再散落判断；
  - 「原地改字段 → commit → 快照 → commit」的两段式提交收敛为单事务
    「改字段 → flush → 快照 → commit」，避免第一次提交成功后快照失败、
    导致状态已变更但版本记录缺失的不一致状态；
  - 视图层只负责取对象、flash 消息与重定向。
"""
from datetime import datetime
from typing import NamedTuple

from flask import current_app
from flask_babel import gettext as _gettext

from ..extensions import db
from ..models.workflow import (
    STATUS_DRAFT, STATUS_REVIEW, STATUS_PUBLISHED, STATUS_ARCHIVED,
    ArticleVersion,
)
from ..models.audit import (
    OP_UPDATE, OP_PUBLISH, OP_ARCHIVE, OP_REVIEW_PASS, OP_REVIEW_REJECT,
    MODULE_ARTICLE,
)
from ..utils.helpers import audit_log, clear_content_cache


# 工作流动作
ACTION_SUBMIT_REVIEW = 'submit_review'
ACTION_REVIEW_PASS = 'review_pass'
ACTION_REVIEW_REJECT = 'review_reject'
ACTION_PUBLISH = 'publish'
ACTION_ARCHIVE = 'archive'

# 状态迁移表：from_states 为空表示不限制来源状态
_TRANSITIONS = {
    ACTION_SUBMIT_REVIEW: {
        'from_states': (STATUS_DRAFT, STATUS_ARCHIVED),
        'to_state': STATUS_REVIEW,
        'clear_reject_reason': True,
        'mark_reviewed': False,
        'column_flag': None,
        'audit_op': OP_UPDATE,
        'audit_extra': {'action': 'submit_review', 'from_status': 'draft/archived'},
        'snapshot_note': '提交审核',
        'success': '已提交待审核，请等待审核员处理',
        'failure': '提交失败',
        'invalid_message': '只有草稿或已归档的内容可以提交审核',
    },
    ACTION_REVIEW_PASS: {
        'from_states': (STATUS_REVIEW,),
        'to_state': STATUS_PUBLISHED,
        'clear_reject_reason': True,
        'mark_reviewed': True,
        'column_flag': 'can_review',
        'flag_message': '您在该栏目没有「审核」权限',
        'audit_op': OP_REVIEW_PASS,
        'audit_extra': None,
        'snapshot_note': '审核通过',
        'success': '审核通过，内容已正式发布',
        'failure': '审核失败',
        'invalid_message': '只有「待审核」状态才能审核通过',
    },
    ACTION_REVIEW_REJECT: {
        'from_states': (STATUS_REVIEW,),
        'to_state': STATUS_DRAFT,
        'clear_reject_reason': False,
        'mark_reviewed': True,
        'column_flag': 'can_review',
        'flag_message': '您在该栏目没有「审核」权限',
        'audit_op': OP_REVIEW_REJECT,
        'audit_extra': None,
        'snapshot_note': None,
        'success': None,
        'failure': '驳回失败',
        'invalid_message': '只有「待审核」状态才能驳回',
    },
    ACTION_PUBLISH: {
        'from_states': (),
        'to_state': STATUS_PUBLISHED,
        'clear_reject_reason': True,
        'mark_reviewed': False,
        'column_flag': 'can_publish',
        'flag_message': '您在该栏目没有「发布」权限',
        'audit_op': OP_PUBLISH,
        'audit_extra': {'from': 'direct_publish'},
        'snapshot_note': '直接发布',
        'success': '已直接发布',
        'failure': '发布失败',
        'invalid_message': None,
    },
    ACTION_ARCHIVE: {
        'from_states': (),
        'to_state': STATUS_ARCHIVED,
        'clear_reject_reason': False,
        'mark_reviewed': False,
        'column_flag': None,
        'audit_op': OP_ARCHIVE,
        'audit_extra': None,
        'snapshot_note': '归档',
        'success': '已归档（前台不再展示）',
        'failure': '归档失败',
        'invalid_message': None,
    },
}


class TransitionResult(NamedTuple):
    """单个工作流动作的执行结果。

    redirect：'index' 回文章列表页，'edit' 回编辑页（如驳回原因缺失时）。
    """
    ok: bool
    messages: list
    redirect: str = 'index'


def can_transition(status, action):
    """判断某状态是否允许执行该动作（只看状态机，不含权限判断）。"""
    spec = _TRANSITIONS.get(action)
    if spec is None:
        return False
    return not spec['from_states'] or status in spec['from_states']


def transition_article(article, action, *, user, reject_reason=None):
    """执行一次文章状态流转（校验 → 改字段 → 快照 → 单次提交 → 审计）。

    :param article: 已持久化的 Article 实例
    :param action:  ACTION_* 常量之一
    :param user:    当前用户（用于栏目级权限与操作人记录）
    :param reject_reason: 驳回动作的驳回原因（表单原文，内部会 trim 截断）
    :returns: TransitionResult，messages 为 [(category, message), ...]，
              由调用方负责 flash
    """
    spec = _TRANSITIONS.get(action)
    if spec is None:
        return TransitionResult(False, [('warning', _gettext('未知的工作流动作：{0}').format(action))])

    column_id = article.column_id
    flag = spec['column_flag']
    if flag and not user.column_flag(flag, column_id):
        return TransitionResult(False, [('warning', _gettext(spec['flag_message']))])

    if not can_transition(article.status, action):
        return TransitionResult(False, [('warning', _gettext(spec['invalid_message']))])

    reason = None
    if action == ACTION_REVIEW_REJECT:
        reason = (reject_reason or '').strip()[:500]
        if not reason:
            return TransitionResult(False, [('danger', _gettext('驳回原因必填'))], redirect='edit')

    uid = getattr(user, 'id', None)
    article.status = spec['to_state']
    if spec['clear_reject_reason']:
        article.reject_reason = None
    if reason is not None:
        article.reject_reason = reason
    if spec['mark_reviewed']:
        article.reviewed_by = uid
        article.reviewed_at = datetime.now()
    article.sync_enabled_from_status()
    article.updated_by = uid

    if reason is not None:
        note = f'审核驳回：{reason[:50]}'
        success = _gettext('已驳回，原因已写入供编辑修改（{0}…）').format(reason[:30])
    else:
        note = spec['snapshot_note']
        success = _gettext(spec['success'])

    try:
        # 先 flush 让字段变更落到事务中（唯一约束/长度校验在此暴露），
        # 再写版本快照，最后一次性提交，保证状态与快照原子生效
        db.session.flush()
        ArticleVersion.snapshot(article, article.status, note=note, created_by=uid)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            '文章工作流流转失败：action=%s article_id=%s', action, article.id)
        return TransitionResult(False, [('danger', _gettext(spec['failure']))])

    clear_content_cache(column_id=column_id, article_id=article.id)
    detail = {'column_id': column_id}
    if spec['audit_extra']:
        detail.update(spec['audit_extra'])
    if reason is not None:
        detail['reason'] = reason
    audit_log(spec['audit_op'], MODULE_ARTICLE, article.id, article.title, detail)
    return TransitionResult(True, [('success', success)])
