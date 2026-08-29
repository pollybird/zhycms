"""内容发布工作流：状态 + 审核 + 版本快照。"""
from datetime import datetime

from ..extensions import db


# ========== 内容状态 ==========
STATUS_DRAFT = 'draft'          # 草稿
STATUS_REVIEW = 'review'        # 待审核
STATUS_PUBLISHED = 'published'  # 已发布
STATUS_ARCHIVED = 'archived'    # 已归档

STATUS_CHOICES = [
    (STATUS_DRAFT, '草稿'),
    (STATUS_REVIEW, '待审核'),
    (STATUS_PUBLISHED, '已发布'),
    (STATUS_ARCHIVED, '已归档'),
]

# 发布态 <-> 原 is_enabled 映射：STATUS_PUBLISHED → is_enabled=True，其他 → False
STATUSES_ENABLED = {STATUS_PUBLISHED}


class ArticleVersion(db.Model):
    """文章版本快照：每次保存/发布都记录一份，用于查看历史与回滚。"""
    __tablename__ = 'article_versions'

    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('articles.id'), nullable=False, index=True)
    version_no = db.Column(db.Integer, nullable=False)  # 同一文章内自增

    # 快照字段（与 Article 同名字段保持一致，方便 diff 与回滚）
    title = db.Column(db.String(255), nullable=False)
    summary = db.Column(db.Text)
    cover = db.Column(db.String(255))
    content = db.Column(db.Text)
    author = db.Column(db.String(64))
    source = db.Column(db.String(128))
    seo_title = db.Column(db.String(255))
    seo_keywords = db.Column(db.String(255))
    seo_description = db.Column(db.String(500))

    # 版本快照专属
    status_snapshot = db.Column(db.String(16))           # 保存时的状态
    custom_fields_json = db.Column(db.Text)              # 自定义字段快照（JSON）
    note = db.Column(db.String(255))                     # 备注/驳回原因

    # 操作人
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)

    article = db.relationship('Article', backref=db.backref('versions', lazy='dynamic',
                                                             order_by='ArticleVersion.version_no.desc(), '
                                                                      'ArticleVersion.id.desc()',
                                                             cascade='all, delete-orphan'))
    creator = db.relationship('User')

    __table_args__ = (
        db.UniqueConstraint('article_id', 'version_no', name='uq_article_version'),
    )

    @classmethod
    def next_version_no(cls, article_id):
        last = cls.query.filter_by(article_id=article_id).order_by(cls.version_no.desc()).first()
        return (last.version_no + 1) if last else 1

    @classmethod
    def snapshot(cls, article, status_snapshot=None, note=None, created_by=None):
        """对当前 Article 做一次版本快照；自定义字段值一并序列化为 JSON。

        created_by 可传 User 对象或用户 ID（int），统一归一化为 int 存储。
        """
        import json as _json
        from ..models.article import ArticleFieldValue

        if created_by is not None and hasattr(created_by, 'id'):
            created_by = created_by.id

        version = cls(
            article_id=article.id,
            version_no=cls.next_version_no(article.id),
            title=article.title or '',
            summary=article.summary or '',
            cover=article.cover or '',
            content=article.content or '',
            author=article.author or '',
            source=article.source or '',
            seo_title=article.seo_title or '',
            seo_keywords=article.seo_keywords or '',
            seo_description=article.seo_description or '',
            status_snapshot=status_snapshot or getattr(article, 'status', None),
            note=note or '',
            created_by=created_by,
        )
        # 自定义字段快照
        fvs = ArticleFieldValue.query.filter_by(article_id=article.id).all()
        payload = {
            str(fv.field_id): {
                'field_key': fv.field.field_key if fv.field else '',
                'label': fv.field.label if fv.field else '',
                'value': fv.value or '',
            } for fv in fvs
        }
        version.custom_fields_json = _json.dumps(payload, ensure_ascii=False)
        db.session.add(version)
        return version

    def restore_to(self, article):
        """把本版本快照字段写回 article 对象（不提交事务，由调用方 commit）。

        注意：自定义字段值由调用方另行基于 custom_fields_json 重建 ArticleFieldValue。
        """
        import json as _json
        from ..models.article import ArticleFieldValue

        article.title = self.title
        article.summary = self.summary
        article.cover = self.cover or None
        article.content = self.content
        article.author = self.author
        article.source = self.source
        article.seo_title = self.seo_title
        article.seo_keywords = self.seo_keywords
        article.seo_description = self.seo_description

        # 自定义字段值：清空当前，按快照重建
        ArticleFieldValue.query.filter_by(article_id=article.id).delete()
        try:
            payload = _json.loads(self.custom_fields_json or '{}')
        except Exception:
            payload = {}
        for f_id_str, info in payload.items():
            try:
                f_id = int(f_id_str)
            except (TypeError, ValueError):
                continue
            db.session.add(ArticleFieldValue(
                article_id=article.id, field_id=f_id, value=info.get('value', '')
            ))
        return article
