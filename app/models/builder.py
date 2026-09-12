"""v3.0.0 可视化页面构建器数据模型。

- BuilderPage：一个页面作用域对应一条记录（首页全局唯一；栏目页绑定 column_id）。
  draft_json 为编辑器草稿，published_json 为前台实际渲染的已发布布局。
- BuilderRevision：每次发布生成一个不可变快照，支持回滚。

布局 JSON 结构见 docs/PAGE_BUILDER.md，校验逻辑在 app/builder/schema.py。
"""
from datetime import datetime

from ..constants import Builder as _B
from ..extensions import db


class BuilderPage(db.Model):
    """构建器页面。"""
    __tablename__ = 'builder_pages'

    id = db.Column(db.Integer, primary_key=True)
    # 作用域：home/page/list/article
    scope = db.Column(db.String(16), nullable=False, index=True)
    # 绑定栏目：home 恒为 NULL；article 为 NULL 表示全局默认详情布局
    column_id = db.Column(
        db.Integer, db.ForeignKey('columns.id'),
        nullable=True, index=True
    )
    name = db.Column(db.String(100), nullable=False, default='')

    # draft=从未发布或有未发布改动；published=线上为最新
    status = db.Column(
        db.String(16), nullable=False, default=_B.STATUS_DRAFT
    )

    draft_json = db.Column(db.Text, nullable=True)
    published_json = db.Column(db.Text, nullable=True)
    published_at = db.Column(db.DateTime, nullable=True)

    author_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=True
    )

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    column = db.relationship('Column', foreign_keys=[column_id])
    revisions = db.relationship(
        'BuilderRevision', backref='page',
        cascade='all, delete-orphan',
        order_by='BuilderRevision.id.desc()',
        lazy='dynamic',
    )

    __table_args__ = (
        db.UniqueConstraint('scope', 'column_id', name='uq_builder_page_scope_column'),
    )

    @property
    def has_published(self):
        return bool(self.published_json)

    def __repr__(self):
        return f'<BuilderPage {self.scope}:{self.column_id} #{self.id}>'


class BuilderRevision(db.Model):
    """页面发布修订快照。"""
    __tablename__ = 'builder_revisions'

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(
        db.Integer, db.ForeignKey('builder_pages.id', ondelete='CASCADE'),
        nullable=False, index=True
    )
    data_json = db.Column(db.Text, nullable=False)
    note = db.Column(db.String(255), default='')
    author_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=True
    )
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    def __repr__(self):
        return f'<BuilderRevision page={self.page_id} #{self.id}>'
