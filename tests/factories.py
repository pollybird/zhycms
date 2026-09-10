"""测试数据工厂（v2.6.0）。

轻量工厂函数，不引入 factory_boy 依赖。
所有工厂函数返回已 db.session.add 但未 commit 的对象（由调用方 commit）。
"""
from app.extensions import db
from app.models.user import User
from app.models.column import Column
from app.models.article import Article
from app.models.workflow import STATUS_PUBLISHED


def make_user(username='testuser', password='testpass', is_super=False,
              role=None):
    """创建普通用户。"""
    user = User(username=username, is_super=is_super, is_deleted=False)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    if role:
        user.roles.append(role)
    return user


def make_column(name='测试栏目', slug='test-col', col_type='list',
                parent_id=None, sort_order=0):
    """创建栏目。"""
    col = Column(name=name, slug=slug, type=col_type,
                 parent_id=parent_id, sort_order=sort_order,
                 is_enabled=True, is_deleted=False)
    db.session.add(col)
    db.session.flush()
    return col


def make_article(title='测试文章', column_id=1, status=STATUS_PUBLISHED,
                 content='文章正文内容', author='测试作者', is_deleted=False,
                 sort_order=0):
    """创建文章。"""
    article = Article(
        title=title,
        column_id=column_id,
        status=status,
        content=content,
        author=author,
        is_deleted=is_deleted,
        sort_order=sort_order,
        is_enabled=(status == STATUS_PUBLISHED),
    )
    db.session.add(article)
    db.session.flush()
    return article
