from datetime import datetime

from ..extensions import db


class Column(db.Model):
    """栏目：三种类型 page/list/link，树形结构。

    type: page=单页栏目, list=列表栏目, link=链接栏目
    parent_mode: first_child=跳转第一个子栏目, list_children=展示子栏目列表
    """
    __tablename__ = 'columns'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('columns.id'), nullable=True, index=True)
    type = db.Column(db.String(16), default='page', nullable=False)  # page/list/link
    summary = db.Column(db.Text)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    # 单页内容（仅 type=page 且为叶子栏目时使用）
    page_content = db.Column(db.Text)

    # 列表栏目：每页条数
    page_size = db.Column(db.Integer, default=10)

    # 链接栏目
    link_url = db.Column(db.String(255))
    link_target = db.Column(db.String(16), default='_self')  # _self / _blank

    # 父栏目前台访问模式
    parent_mode = db.Column(db.String(16), default='first_child')  # first_child / list_children

    # 模板选择（留空则使用默认模板）
    # list 类型栏目：list_template=列表页模板，detail_template=文章详情页模板
    # page 类型栏目：page_template=单页模板
    list_template = db.Column(db.String(64))
    detail_template = db.Column(db.String(64))
    page_template = db.Column(db.String(64))

    # SEO
    seo_title = db.Column(db.String(255))
    seo_keywords = db.Column(db.String(255))
    seo_description = db.Column(db.String(500))

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    parent = db.relationship(
        'Column', remote_side=[id], backref=db.backref('children', lazy='dynamic')
    )
    fields = db.relationship(
        'ColumnField', backref='column', lazy='dynamic',
        cascade='all, delete-orphan'
    )

    @property
    def is_parent(self):
        """是否为父栏目（有未删除的子栏目）。"""
        return self.children.filter_by(is_deleted=False).count() > 0

    @property
    def is_leaf(self):
        return not self.is_parent

    @property
    def can_have_content(self):
        """是否可添加自有内容：必须是叶子栏目，且类型为 page 或 list。"""
        return self.is_leaf and self.type in ('page', 'list')

    def get_field_value(self, field_id):
        """取本栏目自身某自定义字段的值（仅单页栏目使用）。

        与 Article.get_field_value 对称：单页栏目的字段值存于 ColumnFieldValue。
        """
        for v in self.field_values:
            if v.field_id == field_id:
                return v.value
        return ''

    @classmethod
    def get_tree(cls, enabled_only=False, include_deleted=False):
        """返回排好序的栏目列表（按 parent_id + sort_order + created_at 倒序）。"""
        query = cls.query
        if not include_deleted:
            query = query.filter_by(is_deleted=False)
        if enabled_only:
            query = query.filter_by(is_enabled=True)
        columns = query.order_by(cls.parent_id.asc(), cls.sort_order.desc(), cls.created_at.desc()).all()
        return columns

    @classmethod
    def build_nested(cls, columns, parent_id=None):
        """构建嵌套树。"""
        result = []
        for col in columns:
            if col.parent_id == parent_id:
                children = cls.build_nested(columns, col.id)
                result.append({'node': col, 'children': children})
        return result

    def get_descendant_ids(self):
        """获取所有后代栏目 id（用于校验循环引用）。"""
        ids = []
        stack = [self.id]
        while stack:
            current = stack.pop()
            children_ids = [
                c.id for c in Column.query.filter_by(parent_id=current, is_deleted=False).all()
            ]
            for cid in children_ids:
                if cid not in ids:
                    ids.append(cid)
                    stack.append(cid)
        return ids

    def __repr__(self):
        return f'<Column {self.slug}>'


class ColumnField(db.Model):
    """栏目自定义字段配置。"""
    __tablename__ = 'column_fields'

    id = db.Column(db.Integer, primary_key=True)
    column_id = db.Column(db.Integer, db.ForeignKey('columns.id'), nullable=False, index=True)
    label = db.Column(db.String(100), nullable=False)
    field_key = db.Column(db.String(100), nullable=False)
    field_type = db.Column(db.String(32), nullable=False)  # text/textarea/richtext/image/url/number/file
    is_required = db.Column(db.Boolean, default=False, nullable=False)
    is_frontend_visible = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    # 文件上传字段额外配置
    allowed_exts = db.Column(db.String(255))  # 逗号分隔，如 pdf,doc,docx
    max_size = db.Column(db.Integer)  # 单位字节

    # 默认值
    default_value = db.Column(db.Text)

    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __table_args__ = (db.UniqueConstraint('column_id', 'field_key', name='uq_column_field_key'),)


class ColumnFieldValue(db.Model):
    """栏目自身自定义字段值（仅叶子栏目自身）。"""
    __tablename__ = 'column_field_values'

    id = db.Column(db.Integer, primary_key=True)
    column_id = db.Column(db.Integer, db.ForeignKey('columns.id'), nullable=False, index=True)
    field_id = db.Column(db.Integer, db.ForeignKey('column_fields.id'), nullable=False)
    value = db.Column(db.Text)

    field = db.relationship('ColumnField')
    column = db.relationship('Column', backref=db.backref('field_values', cascade='all, delete-orphan'))

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __table_args__ = (db.UniqueConstraint('column_id', 'field_id', name='uq_column_field_value'),)
