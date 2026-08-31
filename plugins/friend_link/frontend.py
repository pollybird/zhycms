"""友情链接插件：前台模板函数。

friend_links(limit=None) 注册为 Jinja 全局函数（核心自动包裹「插件启用」
守卫，未启用返回 []，主题模板零改动不报错）。

返回字典列表（键与核心版模型属性一致），主题模板中的 l.name / l.url /
l.logo / l.target 属性访问写法无需调整。
"""


def friend_links(limit=None):
    """当前生效的友情链接（启用 + 未删除），按排序降序、创建时间降序。

    返回 [{'name', 'url', 'logo', 'target'}]；
    插件未启用 / 无有效链接 → []。
    """
    from .models import FriendLink

    q = FriendLink.query.filter_by(is_enabled=True, is_deleted=False).order_by(
        FriendLink.sort_order.desc(), FriendLink.created_at.desc()
    )
    if limit:
        q = q.limit(max(int(limit), 1))
    return [
        {
            'name': l.name,
            'url': l.url,
            'logo': l.logo or '',
            'target': l.target or '_blank',
        }
        for l in q.all()
    ]
