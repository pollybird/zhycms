"""轮播图插件：前台模板函数。

banner_items(slug, limit=None) 注册为 Jinja 全局函数（核心自动包裹「插件启用」
守卫，未启用返回 []，主题模板零改动不报错）。

缓存策略：页面缓存开启时按分组缓存结果；缓存键含分组 updated_at 时间戳，
后台任何保存动作（分组/图片）都会 touch 分组时间戳，自动失效，无需手动清理。
"""
from datetime import datetime


def banner_items(slug, limit=None):
    """分组内当前生效的轮播图（启用 + 时间窗内），按排序升序。

    返回 [{'title', 'image_url', 'link_url', 'link_target'}]；
    插件未启用 / 分组不存在或停用 / 无有效图片 → []。
    """
    from app.extensions import db
    from app.models.setting import Setting
    from .models import BannerGroup, Banner

    group = BannerGroup.query.filter_by(slug=slug, is_enabled=True).first()
    if group is None:
        return []

    def _query():
        now = datetime.now()
        q = group.items.filter_by(is_enabled=True).filter(
            db.or_(Banner.start_at.is_(None), Banner.start_at <= now),
            db.or_(Banner.end_at.is_(None), Banner.end_at >= now),
        )
        if limit:
            q = q.limit(max(int(limit), 1))
        return [
            {
                'title': b.title or '',
                'image_url': b.image_url(),
                'link_url': b.link_url or '',
                'link_target': b.link_target or '_self',
            }
            for b in q.all()
        ]

    # 页面缓存开启时走缓存（TTL 复用栏目页配置）
    if Setting.get('cache_enable') != 'on':
        return _query()
    try:
        ttl = int(Setting.get('cache_ttl_column', 1800))
    except (TypeError, ValueError):
        ttl = 1800
    if ttl <= 0:
        return _query()

    from app.extensions import cache
    stamp = group.updated_at.strftime('%Y%m%d%H%M%S') if group.updated_at else '0'
    key = f'plugin/banner/items/{slug}/{int(limit or 0)}/{stamp}'
    try:
        cached = cache.get(key)
        if cached is not None:
            return cached
    except Exception:
        pass
    result = _query()
    try:
        cache.set(key, result, timeout=ttl)
    except Exception:
        pass
    return result
