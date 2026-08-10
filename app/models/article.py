from datetime import datetime

from ..extensions import db


class Article(db.Model):
    """列表栏目下的文章。"""
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
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    viewed = db.Column(db.Integer, default=0, nullable=False)

    seo_title = db.Column(db.String(255))
    seo_keywords = db.Column(db.String(255))
    seo_description = db.Column(db.String(500))

    published_at = db.Column(db.DateTime, default=datetime.now)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    column = db.relationship('Column', backref=db.backref('articles', lazy='dynamic'))
    field_values = db.relationship(
        'ArticleFieldValue', backref='article',
        cascade='all, delete-orphan', lazy='joined'
    )

    def get_field_value(self, field_id):
        for v in self.field_values:
            if v.field_id == field_id:
                return v.value
        return ''


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
