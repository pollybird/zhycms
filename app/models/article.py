from datetime import datetime

from ..extensions import db
from .workflow import STATUS_DRAFT, STATUS_PUBLISHED, STATUSES_ENABLED


class Article(db.Model):
    """列表栏目下的文章（含工作流四状态）。"""
    __tablename__ = 'articles'

    id = db.Column(db.Integer, primary_key=True)
    column_id = db.Column(db.Integer, db.ForeignKey('columns.id'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    summary = db.Column(db.Text)
    cover = db.Column(db.String(255))
    content = db.Column(db.Text)
    author = db.Column(db.String(64))
    source = db.Column(db.String(128))
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    # 兼容原字段：is_enabled 与新 status 联动；STATUS_PUBLISHED → True，其余 False
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    viewed = db.Column(db.Integer, default=0, nullable=False)

    seo_title = db.Column(db.String(255))
    seo_keywords = db.Column(db.String(255))
    seo_description = db.Column(db.String(500))

    # 模块3：内容发布工作流
    status = db.Column(db.String(16), default=STATUS_PUBLISHED, nullable=False, index=True)
    reject_reason = db.Column(db.String(500))       # 审核驳回原因（最近一次）
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))  # 最近一次审核人
    reviewed_at = db.Column(db.DateTime)            # 最近一次审核时间
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))   # 创建人
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))   # 最近编辑人

    published_at = db.Column(db.DateTime, default=datetime.now)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    column = db.relationship('Column', backref=db.backref('articles', lazy='dynamic'))
    field_values = db.relationship(
        'ArticleFieldValue', backref='article',
        cascade='all, delete-orphan', lazy='joined'
    )

    # 外键关联的用户对象（避免与 creator 等同名冲突，用外键字段+显式 relationship）
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])
    creator = db.relationship('User', foreign_keys=[created_by])
    updater = db.relationship('User', foreign_keys=[updated_by])

    def get_field_value(self, field_id):
        for v in self.field_values:
            if v.field_id == field_id:
                return v.value
        return ''

    # ===== status <-> is_enabled 同步工具 =====
    def sync_enabled_from_status(self):
        """根据 status 更新 is_enabled，保证前后台原有 is_enabled 查询仍可用。"""
        self.is_enabled = self.status in STATUSES_ENABLED

    @classmethod
    def ensure_status_column(cls):
        """兼容旧数据：迁移时，is_enabled=True 的文章置为 published，否则置为 draft。

        在首次运行 / 表创建后调用，避免历史数据 status 为空。
        """
        from sqlalchemy import text
        try:
            # 注意 OR/AND 优先级：必须用括号把 (status IS NULL OR status = '') 包起来，
            # 否则 is_enabled=0 且 status 为空的旧文章会被第一句误置为 published。
            db.session.execute(text(
                "UPDATE articles SET status = :pub WHERE (status IS NULL OR status = '') AND is_enabled = 1"
            ).bindparams(pub=STATUS_PUBLISHED))
            db.session.execute(text(
                "UPDATE articles SET status = :draft WHERE (status IS NULL OR status = '') AND is_enabled = 0"
            ).bindparams(draft=STATUS_DRAFT))
            db.session.commit()
        except Exception:
            db.session.rollback()


class ArticleFieldValue(db.Model):
    """文章自定义字段值（继承栏目字段）。"""
    __tablename__ = 'article_field_values'

    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('articles.id'), nullable=False, index=True)
    field_id = db.Column(db.Integer, db.ForeignKey('column_fields.id'), nullable=False)
    value = db.Column(db.Text)

    field = db.relationship('ColumnField')

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('article_id', 'field_id', name='uq_article_field_value'),
    )
