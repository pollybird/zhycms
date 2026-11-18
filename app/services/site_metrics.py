"""站点资源指标采集：文章/浏览量/缓存条目/磁盘用量。

所有统计都在服务层完成，模板只负责渲染。缓存后端不可用时返回 None，
由页面显示 `--`，绝不让指标页因为统计失败而 500。
"""
import logging
import os
from datetime import date as date_cls
from datetime import datetime

from flask import current_app, g, has_app_context
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import cache, db
from ..models.article import Article
from ..models.site import Site

logger = logging.getLogger(__name__)

# 插件内容表：按站点计数，与站点删除检查的统计口径保持一致
_PLUGIN_MODELS = (
    ('product', 'plugins.product.models', 'Product'),
    ('form', 'plugins.form.models', 'Form'),
    ('friend_link', 'plugins.friend_link.models', 'FriendLink'),
    ('banner', 'plugins.banner.models', 'Banner'),
    ('tutorial', 'plugins.tutorial.models', 'Tutorial'),
    ('recruit', 'plugins.recruit.models', 'RecruitJob'),
)

# 单次遍历 SimpleCache 的上限，超过则视为不可统计
_SIMPLE_CACHE_SCAN_LIMIT = 50000


def _count_model(model, site_id):
    """按站点统计模型行数；模型没有 site_id 时返回 0。"""
    if not hasattr(model, 'site_id'):
        return 0
    query = db.session.query(func.count(model.id)).filter(
        model.site_id == site_id)
    if hasattr(model, 'is_deleted'):
        query = query.filter(model.is_deleted == False)  # noqa: E712
    return int(query.scalar() or 0)


def _plugin_counts(site_id):
    """统计各插件内容数量；单个插件异常不影响其他插件。"""
    counts = {}
    for key, module_name, class_name in _PLUGIN_MODELS:
        try:
            module = __import__(module_name, fromlist=[class_name])
            model = getattr(module, class_name)
            counts[key] = _count_model(model, site_id)
        except (ImportError, AttributeError, SQLAlchemyError) as e:
            logger.warning('统计站点 %s 的 %s 数量失败：%s', site_id, key, e)
    return counts


def _cache_entry_count(site_id):
    """统计包含 `site{sid}` 的缓存键数量；后端不支持时返回 None。"""
    try:
        backend = getattr(cache, 'cache', None)
        if backend is None:
            return None

        if hasattr(backend, 'scan_iter'):
            total = 0
            for _ in backend.scan_iter(match=f'*site{site_id}*', count=1000):
                total += 1
            return total

        store = getattr(backend, '_cache', None)
        if store is None:
            return None
        if len(store) > _SIMPLE_CACHE_SCAN_LIMIT:
            return None
        marker = f'site{site_id}'
        return sum(1 for key in list(store.keys()) if marker in str(key))
    except Exception as e:  # 缓存客户端可能抛出连接类异常，统一降级
        logger.warning('统计站点 %s 缓存条目失败：%s', site_id, e)
        return None


def _upload_root():
    try:
        configured = current_app.config.get('UPLOAD_FOLDER')
    except RuntimeError:
        return None
    if configured:
        return configured
    try:
        return os.path.join(current_app.root_path, 'static', 'uploads')
    except RuntimeError:
        return None


def _disk_usage_bytes(site_id):
    """扫描 `uploads/site{sid}` 累加文件大小；目录不存在返回 0。"""
    root = _upload_root()
    if not root:
        return 0
    path = os.path.join(root, f'site{site_id}')
    if not os.path.isdir(path):
        return 0

    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames[:] = [
            d for d in dirnames
            if not os.path.islink(os.path.join(dirpath, d))]
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            if os.path.islink(file_path):
                continue
            try:
                total += os.path.getsize(file_path)
            except OSError as e:
                logger.warning('读取文件大小失败 %s：%s', file_path, e)
    return total


def collect_site_metrics(site_id, refresh=False):
    """采集单个站点的指标。

    同一请求内默认复用 `g` 上的结果；`refresh=True` 或 `?refresh=1`
    时重新采集。站点不存在时返回全 0，不抛异常。
    """
    try:
        sid = int(site_id)
    except (TypeError, ValueError):
        sid = 0

    cache_key = f'_site_metrics_{sid}'
    if has_app_context() and not refresh:
        cached = g.get(cache_key)
        if cached is not None:
            return cached

    try:
        article_count = int(db.session.query(func.count(Article.id)).filter(
            Article.site_id == sid, Article.is_deleted == False).scalar() or 0)  # noqa: E712
        view_count = int(db.session.query(
            func.coalesce(func.sum(Article.viewed), 0)).filter(
            Article.site_id == sid, Article.is_deleted == False).scalar() or 0)  # noqa: E712
    except SQLAlchemyError as e:
        logger.warning('统计站点 %s 文章指标失败：%s', sid, e)
        article_count = 0
        view_count = 0

    counts = _plugin_counts(sid)
    counts['article'] = article_count
    result = {
        'site_id': sid,
        'article_count': article_count,
        'view_count': view_count,
        'cache_entries': _cache_entry_count(sid),
        'disk_bytes': _disk_usage_bytes(sid),
        'counts': counts,
    }

    if has_app_context():
        setattr(g, cache_key, result)
    return result


def collect_all_sites(refresh=False):
    """采集全部启用站点的指标，附带站点展示字段。"""
    rows = []
    for site in Site.active_sites():
        metrics = collect_site_metrics(site.id, refresh=refresh)
        row = dict(metrics)
        row.update({
            'site': site,
            'name': site.name,
            'slug': site.slug,
            'domain': site.domain,
            'subdomain': site.subdomain,
            'status': site.status,
            'is_default': site.is_default,
        })
        rows.append(row)
    return rows


def snapshot_daily(date=None):
    """把当天指标写入快照表，返回成功处理的站点数。

    同一站点同一天重复执行只更新不新增；单个站点失败会回滚该站点的
    写入并继续处理其他站点。
    """
    from ..extensions import db as _db
    from ..models.site_metric import SiteMetricSnapshot

    target = date or date_cls.today()
    written = 0
    for site in Site.active_sites():
        try:
            metrics = collect_site_metrics(site.id, refresh=True)
            row = SiteMetricSnapshot.query.filter_by(
                site_id=site.id, date=target).first()
            if row is None:
                row = SiteMetricSnapshot(site_id=site.id, date=target)
                _db.session.add(row)
            row.article_count = metrics['article_count']
            row.view_count = metrics['view_count']
            row.cache_entries = metrics['cache_entries']
            row.disk_bytes = metrics['disk_bytes']
            row.created_at = datetime.now()
            _db.session.commit()
            written += 1
        except Exception as e:
            _db.session.rollback()
            logger.warning('站点 %s 指标快照写入失败：%s', site.id, e)
    return written


def format_bytes(value):
    """把字节数格式化为 B/KB/MB/GB/TB；None 返回 `--`。"""
    if value is None:
        return '--'
    try:
        number = float(value)
    except (TypeError, ValueError):
        return '--'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if number < 1024 or unit == 'TB':
            if unit == 'B':
                return f'{int(number)} B'
            return f'{number:.1f} {unit}'
        number /= 1024
    return '--'


def format_number(value):
    """把数字格式化为千分位；None 返回 `--`。"""
    if value is None:
        return '--'
    try:
        return f'{int(value):,}'
    except (TypeError, ValueError):
        return '--'
