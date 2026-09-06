from datetime import datetime

from ..extensions import db


class FragmentGroup(db.Model):
    __tablename__ = 'fragment_groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    fragments = db.relationship('Fragment', backref='group', lazy='dynamic')


class Fragment(db.Model):
    """全站碎片字段，唯一 slug 用于模板调用。"""
    __tablename__ = 'fragments'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('fragment_groups.id'), nullable=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    field_type = db.Column(db.String(32), nullable=False)
    # text/textarea/richtext/image/url/number/file
    value = db.Column(db.Text)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # v2.5.0：多语言翻译（非默认语言的 name/value 存于此）
    translations = db.relationship(
        'FragmentTranslation', backref='fragment',
        cascade='all, delete-orphan', lazy='selectin'
    )

    @classmethod
    def get_dict(cls):
        """返回 {slug: value} 用于模板调用。"""
        result = {}
        for frag in cls.query.filter_by(is_deleted=False, is_enabled=True).all():
            result[frag.slug] = {
                'id': frag.id,
                'name': frag.name,
                'slug': frag.slug,
                'field_type': frag.field_type,
                'value': frag.value or '',
            }
        return result


class FragmentTranslation(db.Model):
    """碎片多语言翻译（v2.5.0）。

    主表 fragments 存默认语言的 name/value；非默认语言存于此表。
    value 为多类型字段（text/textarea/richtext/image/url/number/file），
    翻译表直接存文本值。
    """
    __tablename__ = 'fragment_translations'

    id = db.Column(db.Integer, primary_key=True)
    fragment_id = db.Column(db.Integer, db.ForeignKey('fragments.id', ondelete='CASCADE'), nullable=False, index=True)
    locale = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('fragment_id', 'locale', name='uq_fragment_locale'),
        db.Index('ix_fragment_trans_locale', 'locale'),
    )
