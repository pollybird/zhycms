"""工作流测试：草稿 → 待审核 → 发布/驳回 → 归档。"""
import pytest

from tests.factories import make_column, make_article


@pytest.mark.workflow
class TestArticleWorkflow:

    def test_published_article_visible_on_frontend(self, app, client, admin_client):
        """已发布文章在前台可见。"""
        from app.extensions import db
        from app.models.workflow import STATUS_PUBLISHED
        from app.models.setting import Setting

        with app.app_context():
            Setting.set('seo_rewrite_enable', 'on')
            col = make_column(name='新闻', slug='news')
            make_article(
                title='发布测试', column_id=col.id,
                status=STATUS_PUBLISHED, content='已发布内容')
            db.session.commit()
            col_slug = col.slug

        resp = client.get(f'/{col_slug}.html')
        assert resp.status_code == 200
        assert '发布测试'.encode() in resp.data

    def test_draft_article_not_on_frontend(self, app, client):
        """草稿文章不出现在前台。"""
        from app.extensions import db
        from app.models.workflow import STATUS_DRAFT
        from app.models.setting import Setting

        with app.app_context():
            Setting.set('seo_rewrite_enable', 'on')
            col = make_column(name='草稿栏', slug='draft-col')
            make_article(
                title='草稿文章', column_id=col.id,
                status=STATUS_DRAFT, content='草稿内容')
            db.session.commit()
            col_slug = col.slug

        resp = client.get(f'/{col_slug}.html')
        assert resp.status_code == 200
        # 草稿文章不应出现在列表页
        assert '草稿文章'.encode() not in resp.data


# ============================================================
# v3.1.7 工作流回归：状态机 / 权限 / 快照 / 审计 / 批量
# ============================================================

class _UserStub:
    """工作流 service 层的用户桩：仅需 id 与栏目级权限标志。

    id 返回真实超管 id，避免文章 updated_by/reviewed_by/版本 created_by
    写入不存在的用户，污染共享测试库的外键完整性（迁移用例会据此预检）。
    """

    @property
    def id(self):
        from app.models.user import User
        admin = User.query.filter_by(username='admin').first()
        return admin.id if admin else 1

    def __init__(self, can_review=True, can_publish=True):
        self.can_review = can_review
        self.can_publish = can_publish

    def column_flag(self, flag, column_id):
        return getattr(self, flag, True)


@pytest.mark.workflow
class TestWorkflowStateMachine:

    def test_can_transition_matrix(self):
        """状态机只允许表内组合，未知动作一律拒绝。"""
        from app.models.workflow import (
            STATUS_DRAFT, STATUS_REVIEW, STATUS_PUBLISHED, STATUS_ARCHIVED,
        )
        from app.services.workflow_service import (
            ACTION_SUBMIT_REVIEW, ACTION_REVIEW_PASS, ACTION_REVIEW_REJECT,
            ACTION_PUBLISH, ACTION_ARCHIVE, can_transition,
        )

        assert can_transition(STATUS_DRAFT, ACTION_SUBMIT_REVIEW)
        assert can_transition(STATUS_ARCHIVED, ACTION_SUBMIT_REVIEW)
        assert not can_transition(STATUS_REVIEW, ACTION_SUBMIT_REVIEW)
        assert not can_transition(STATUS_PUBLISHED, ACTION_SUBMIT_REVIEW)

        assert can_transition(STATUS_REVIEW, ACTION_REVIEW_PASS)
        assert can_transition(STATUS_REVIEW, ACTION_REVIEW_REJECT)
        assert not can_transition(STATUS_DRAFT, ACTION_REVIEW_PASS)

        # 直接发布/归档不限制来源状态
        for status in (STATUS_DRAFT, STATUS_REVIEW, STATUS_PUBLISHED, STATUS_ARCHIVED):
            assert can_transition(status, ACTION_PUBLISH)
            assert can_transition(status, ACTION_ARCHIVE)

        assert not can_transition(STATUS_DRAFT, 'not_exists')


@pytest.mark.workflow
class TestTransitionService:

    def _make_article(self, app, status, slug):
        from app.extensions import db
        from tests.factories import make_column, make_article

        col = make_column(name='工作流栏目', slug=slug)
        article = make_article(title='工作流文章-' + slug,
                               column_id=col.id, status=status)
        db.session.commit()
        return col, article

    def test_submit_review_success_writes_snapshot_and_audit(self, app):
        """草稿提交审核：状态变更 + 版本快照 + 清空驳回原因。"""
        from app.extensions import db
        from app.models.workflow import (
            STATUS_DRAFT, STATUS_REVIEW, ArticleVersion,
        )
        from app.models.audit import AuditLog, MODULE_ARTICLE, OP_UPDATE
        from app.services.workflow_service import (
            ACTION_SUBMIT_REVIEW, transition_article,
        )

        with app.app_context():
            col, article = self._make_article(app, STATUS_DRAFT, 'wf-submit')
            article.reject_reason = '旧驳回原因'
            db.session.commit()
            aid = article.id

            result = transition_article(article, ACTION_SUBMIT_REVIEW,
                                        user=_UserStub())
            assert result.ok and result.redirect == 'index'
            assert result.messages[0][0] == 'success'

            refreshed = db.session.get(type(article), aid)
            assert refreshed.status == STATUS_REVIEW
            assert refreshed.reject_reason is None
            assert not refreshed.is_enabled
            assert ArticleVersion.query.filter_by(article_id=aid).count() == 1
            log = AuditLog.query.filter_by(
                module=MODULE_ARTICLE, op_type=OP_UPDATE).order_by(
                AuditLog.id.desc()).first()
            assert log is not None and str(aid) == log.target_id

    def test_submit_review_invalid_status_rejected(self, app):
        """已发布文章不能再次提交审核，状态保持不变。"""
        from app.extensions import db
        from app.models.workflow import STATUS_PUBLISHED, ArticleVersion
        from app.services.workflow_service import (
            ACTION_SUBMIT_REVIEW, transition_article,
        )

        with app.app_context():
            col, article = self._make_article(app, STATUS_PUBLISHED, 'wf-submit-invalid')
            aid = article.id
            versions = ArticleVersion.query.filter_by(article_id=aid).count()
            result = transition_article(article, ACTION_SUBMIT_REVIEW,
                                        user=_UserStub())
            assert not result.ok
            assert result.messages[0][0] == 'warning'
            db.session.refresh(article)
            assert article.status == STATUS_PUBLISHED
            assert ArticleVersion.query.filter_by(article_id=aid).count() == versions

    def test_review_pass_requires_column_permission(self, app):
        """无栏目「审核」权限：拒绝流转且不写快照。"""
        from app.models.workflow import (
            STATUS_REVIEW, STATUS_PUBLISHED, ArticleVersion,
        )
        from app.services.workflow_service import (
            ACTION_REVIEW_PASS, transition_article,
        )

        with app.app_context():
            col, article = self._make_article(app, STATUS_REVIEW, 'wf-review-denied')
            aid = article.id
            result = transition_article(article, ACTION_REVIEW_PASS,
                                        user=_UserStub(can_review=False))
            assert not result.ok
            assert result.messages[0][0] == 'warning'
            assert article.status == STATUS_REVIEW
            assert ArticleVersion.query.filter_by(article_id=aid).count() == 0

    def test_review_pass_publishes_and_marks_reviewer(self, app):
        """审核通过：发布 + 审核人/时间 + 版本快照。"""
        from app.extensions import db
        from app.models.workflow import (
            STATUS_REVIEW, STATUS_PUBLISHED, ArticleVersion,
        )
        from app.services.workflow_service import (
            ACTION_REVIEW_PASS, transition_article,
        )

        with app.app_context():
            col, article = self._make_article(app, STATUS_REVIEW, 'wf-review-pass')
            aid = article.id
            reviewer = _UserStub()
            result = transition_article(article, ACTION_REVIEW_PASS,
                                        user=reviewer)
            assert result.ok
            refreshed = db.session.get(type(article), aid)
            assert refreshed.status == STATUS_PUBLISHED
            assert refreshed.is_enabled
            assert refreshed.reviewed_by == reviewer.id
            assert refreshed.reviewed_at is not None
            versions = ArticleVersion.query.filter_by(article_id=aid).all()
            assert len(versions) == 1
            assert versions[0].status_snapshot == STATUS_PUBLISHED

    def test_reject_without_reason_returns_edit(self, app):
        """驳回归因必填：缺失时回编辑页，状态不变。"""
        from app.extensions import db
        from app.models.workflow import STATUS_REVIEW
        from app.services.workflow_service import (
            ACTION_REVIEW_REJECT, transition_article,
        )

        with app.app_context():
            col, article = self._make_article(app, STATUS_REVIEW, 'wf-reject-empty')
            aid = article.id
            result = transition_article(article, ACTION_REVIEW_REJECT,
                                        user=_UserStub(), reject_reason='   ')
            assert not result.ok
            assert result.redirect == 'edit'
            assert result.messages[0][0] == 'danger'
            db.session.refresh(article)
            assert article.status == STATUS_REVIEW
            assert article.reject_reason is None

    def test_reject_records_reason_and_truncates(self, app):
        """驳回归因写入文章并截断到 500，快照备注体现原因。"""
        from app.extensions import db
        from app.models.workflow import STATUS_REVIEW, STATUS_DRAFT, ArticleVersion
        from app.services.workflow_service import (
            ACTION_REVIEW_REJECT, transition_article,
        )

        with app.app_context():
            col, article = self._make_article(app, STATUS_REVIEW, 'wf-reject-long')
            aid = article.id
            long_reason = '原' * 600
            result = transition_article(article, ACTION_REVIEW_REJECT,
                                        user=_UserStub(),
                                        reject_reason=long_reason)
            assert result.ok
            refreshed = db.session.get(type(article), aid)
            assert refreshed.status == STATUS_DRAFT
            assert refreshed.reject_reason == '原' * 500
            version = ArticleVersion.query.filter_by(article_id=aid).one()
            assert version.note.startswith('审核驳回：')

    def test_direct_publish_without_permission(self, app):
        """直接发布受 can_publish 栏目权限约束。"""
        from app.models.workflow import STATUS_DRAFT
        from app.services.workflow_service import (
            ACTION_PUBLISH, transition_article,
        )

        with app.app_context():
            col, article = self._make_article(app, STATUS_DRAFT, 'wf-publish-denied')
            result = transition_article(article, ACTION_PUBLISH,
                                        user=_UserStub(can_publish=False))
            assert not result.ok
            assert article.status == STATUS_DRAFT

    def test_archive_disables_and_hides_frontend(self, app, client):
        """归档：状态改变 + 前台列表/详情不可见。"""
        from app.extensions import db
        from app.models.workflow import STATUS_PUBLISHED, STATUS_ARCHIVED
        from app.models.setting import Setting
        from app.services.workflow_service import (
            ACTION_ARCHIVE, transition_article,
        )

        with app.app_context():
            Setting.set('seo_rewrite_enable', 'on')
            col, article = self._make_article(app, STATUS_PUBLISHED, 'wf-archive')
            aid = article.id
            assert client.get(f'/article-{aid}.html').status_code == 200

            result = transition_article(article, ACTION_ARCHIVE,
                                        user=_UserStub())
            assert result.ok
            refreshed = db.session.get(type(article), aid)
            assert refreshed.status == STATUS_ARCHIVED
            assert not refreshed.is_enabled

            resp_list = client.get(f'/{col.slug}.html')
            assert resp_list.status_code == 200
            assert refreshed.title.encode() not in resp_list.data
            resp_detail = client.get(f'/article-{aid}.html')
            assert resp_detail.status_code == 404

    def test_snapshot_failure_rolls_back_status(self, app, monkeypatch):
        """快照失败时整体回滚，避免「状态已改但无版本记录」。"""
        from app.extensions import db
        from app.models.workflow import STATUS_DRAFT, STATUS_REVIEW, ArticleVersion
        from app.services.workflow_service import (
            ACTION_SUBMIT_REVIEW, transition_article,
        )

        def boom(*args, **kwargs):
            raise RuntimeError('模拟快照失败')

        with app.app_context():
            col, article = self._make_article(app, STATUS_DRAFT, 'wf-rollback')
            aid = article.id
            monkeypatch.setattr(ArticleVersion, 'snapshot', staticmethod(boom))
            result = transition_article(article, ACTION_SUBMIT_REVIEW,
                                        user=_UserStub())
            assert not result.ok
            assert result.messages[0][0] == 'danger'
            refreshed = db.session.get(type(article), aid)
            assert refreshed.status == STATUS_DRAFT
            assert ArticleVersion.query.filter_by(article_id=aid).count() == 0

    def test_unknown_action(self, app):
        """未知动作不应改任何状态。"""
        from app.extensions import db
        from app.models.workflow import STATUS_DRAFT
        from app.services.workflow_service import transition_article

        with app.app_context():
            col, article = self._make_article(app, STATUS_DRAFT, 'wf-unknown')
            result = transition_article(article, 'not_exists', user=_UserStub())
            assert not result.ok
            assert article.status == STATUS_DRAFT


@pytest.mark.workflow
class TestWorkflowAdminRoutes:

    def _mk(self, app, status, slug):
        from app.extensions import db
        from tests.factories import make_column, make_article

        col = make_column(name='批量栏目', slug=slug)
        a1 = make_article(title='批量文章A-' + slug, column_id=col.id, status=status)
        a2 = make_article(title='批量文章B-' + slug, column_id=col.id, status=status)
        db.session.commit()
        return col, a1, a2

    def test_batch_archive_and_delete(self, app, admin_client):
        """批量归档 / 批量删除：状态、软删标记一次生效。"""
        from app.extensions import db
        from app.models.article import Article
        from app.models.workflow import STATUS_DRAFT, STATUS_ARCHIVED

        with app.app_context():
            col, a1, a2 = self._mk(app, STATUS_DRAFT, 'wf-batch-1')
            cid, ids = col.id, [a1.id, a2.id]

        resp = admin_client.post(
            f'/admin/columns/{cid}/articles/batch',
            data={'action': 'archive', 'ids[]': [str(i) for i in ids]})
        assert resp.status_code == 302

        with app.app_context():
            rows = Article.query.filter(Article.id.in_(ids)).all()
            assert all(r.status == STATUS_ARCHIVED and not r.is_enabled for r in rows)

        resp = admin_client.post(
            f'/admin/columns/{cid}/articles/batch',
            data={'action': 'delete', 'ids[]': [str(i) for i in ids]})
        assert resp.status_code == 302

        with app.app_context():
            rows = Article.query.filter(Article.id.in_(ids)).all()
            assert all(r.is_deleted for r in rows)

    def test_batch_publish_then_frontend_visible(self, app, admin_client, client):
        """批量发布后前台列表立即可见（含缓存失效）。"""
        from app.extensions import db
        from app.models.article import Article
        from app.models.setting import Setting
        from app.models.workflow import STATUS_DRAFT, STATUS_PUBLISHED

        with app.app_context():
            Setting.set('seo_rewrite_enable', 'on')
            col, a1, a2 = self._mk(app, STATUS_DRAFT, 'wf-batch-pub')
            cid, ids, slug = col.id, [a1.id, a2.id], col.slug
            titles = [a1.title, a2.title]

        resp = admin_client.post(
            f'/admin/columns/{cid}/articles/batch',
            data={'action': 'publish', 'ids[]': [str(i) for i in ids]})
        assert resp.status_code == 302

        with app.app_context():
            rows = Article.query.filter(Article.id.in_(ids)).all()
            assert all(r.status == STATUS_PUBLISHED and r.is_enabled for r in rows)

        resp = client.get(f'/{slug}.html')
        assert resp.status_code == 200
        for title in titles:
            assert title.encode() in resp.data

    def test_batch_without_ids_warns(self, app, admin_client):
        """未勾选任何行：不执行动作，仅提示。"""
        from app.extensions import db
        from app.models.article import Article
        from app.models.workflow import STATUS_DRAFT

        with app.app_context():
            col, a1, a2 = self._mk(app, STATUS_DRAFT, 'wf-batch-empty')
            cid, aid = col.id, a1.id

        resp = admin_client.post(
            f'/admin/columns/{cid}/articles/batch', data={'action': 'delete'})
        assert resp.status_code == 302
        with app.app_context():
            assert not db.session.get(Article, aid).is_deleted

