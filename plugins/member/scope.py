"""v3.2.1 站群：会员站点归属范围（shared / isolated）。

收口会员查询与登录态校验的站点口径，供 frontend_routes（登录/注册/找回）
与 security（会话校验）共用，避免两处规则漂移。
"""


def member_scope():
    """返回会员归属模式：'shared'（默认，全站共享）或 'isolated'。"""
    from app.models.setting import Setting
    return 'isolated' if Setting.get('member_scope') == 'isolated' else 'shared'


def scope_site_id():
    """返回会员查询应使用的 site_id。

    shared：返回 0 哨兵（全站共享，等价现网全局唯一）；
    isolated：返回当前站点 id（各站会员互不相通）。
    """
    if member_scope() == 'isolated':
        from app.sites import current_site_id
        return current_site_id()
    return 0


def check_session_member_scope(member):
    """已登录会员与会话所在站点是否匹配（仅 isolated 模式生效）。"""
    if member is None:
        return False
    if member_scope() != 'isolated':
        return True
    from app.sites import current_site_id
    return getattr(member, 'site_id', 0) == current_site_id()
