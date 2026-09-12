"""教程插件：数据模型。

TutorialCategory  教程分类
Tutorial          教程（含封面、难度、时长、浏览量）

启用插件时由 db.create_all() 兜底建表（表已存在则跳过）。
"""
from datetime import datetime

from app.extensions import db


class TutorialCategory(db.Model):
    """教程分类。"""
    __tablename__ = 'tutorial_categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    tutorials = db.relationship(
        'Tutorial', backref='category', lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='Tutorial.sort_order.desc(), Tutorial.created_at.desc()'
    )


class Tutorial(db.Model):
    """教程内容。

    difficulty: beginner / intermediate / advanced
    duration:   预计学习时长（分钟）
    """
    __tablename__ = 'tutorials'

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('tutorial_categories.id'),
                            nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    summary = db.Column(db.String(500))
    content = db.Column(db.Text, nullable=False)
    cover = db.Column(db.String(500))
    difficulty = db.Column(db.String(20), default='beginner', nullable=False)
    duration = db.Column(db.Integer, default=0, nullable=False)  # 分钟
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    view_count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    DIFFICULTY_LABELS = {
        'beginner': '入门',
        'intermediate': '进阶',
        'advanced': '高级',
    }

    @property
    def difficulty_label(self):
        return self.DIFFICULTY_LABELS.get(self.difficulty, '入门')
