"""站点克隆与回收站服务。

克隆在同一数据库内把源站点的内容与展示配置复制到新站点；目标站默认
关闭，检查后再开放。上传资产、会员、提交记录、日志与版本历史不复制。

回收站只做站点软删除，内容行保留；到期后先自动备份再彻底删除。
"""
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models.article import Article, ArticleFieldValue, ArticleTranslation
from ..models.audit import (
    AuditLog, MODULE_SITE, OP_CREATE, OP_UPDATE, OP_DELETE,
)
from ..models.builder import BuilderPage
from ..models.column import (
    Column, ColumnField, ColumnFieldValue, ColumnTranslation,
)
from ..models.fragment import Fragment, FragmentTranslation
from ..models.setting import Setting
from ..models.site import Site, DEFAULT_SITE_ID
from ..models.site_recycle import SiteRecycleBin

logger = logging.getLogger(__name__)

# 克隆时只复制展示类设置；凭据、通知、备份、登录与上传策略不跨站复制
SETTINGS_ALLOWLIST = (
    'site_name', 'site_subtitle', 'site_logo', 'footer_copyright',
    'site_theme',
    'seo_title', 'seo_keywords', 'seo_description',
    'seo_sitemap_changefreq_column', 'seo_sitemap_changefreq_article',
    'seo_sitemap_priority_column', 'seo_sitemap_priority_article',
    'seo_rewrite_enable', 'seo_robots_custom', 'seo_image_alt_default',
    'editor_default_mode',
    'cache_enable', 'cache_ttl_index', 'cache_ttl_column', 'cache_ttl_article',
)

DEFAULT_OPTIONS = {'plugins': True, 'builder': True}
RECYCLE_DAYS = 30
BATCH_SIZE = 200


class CloneError(Exception):
    """站点克隆失败（入口层转成表单错误或任务失败信息）。"""


def estimate_clone_size(source_site_id):
    """估算源站内容量，用于选择同步/异步克隆。"""
    counts = {
        'columns': Column.query.filter_by(site_id=source_site_id).count(),
        'articles': Article.query.filter_by(site_id=source_site_id).count(),
        'fragments': Fragment.query.filter_by(site_id=source_site_id).count(),
        'plugin_rows': 0,
        'settings': Setting.query.filter(
            Setting.site_id == source_site_id,
            Setting.key.in_(SETTINGS_ALLOWLIST)).count(),
    }
    try:
        insp = inspect(db.engine)
        for _label, table in _PLUGIN_SITE_TABLES:
            if insp.has_table(table):
                try:
                    counts['plugin_rows'] += db.session.execute(
                        text(f'SELECT COUNT(*) FROM {table} WHERE site_id = :sid'),
                        {'sid': source_site_id}).scalar() or 0
                except SQLAlchemyError:
                    continue
    except SQLAlchemyError as e:
        logger.warning('估算站点 %s 插件内容失败：%s', source_site_id, e)
    counts['total'] = sum(counts.values())
    return counts


# ============================================================
# 克隆
# ============================================================

class _Bulker:
    """按批次提交，避免 SQLite 长事务锁库。"""

    def __init__(self, every=BATCH_SIZE):
        self.every = every
        self.count = 0

    def add(self, obj):
        db.session.add(obj)
        self.count += 1
        if self.count % self.every == 0:
            db.session.commit()

    def flush(self):
        db.session.commit()


def _copy_fields(src, dst, skip=('id',)):
    for name in src.__table__.columns.keys():
        if name in skip:
            continue
        setattr(dst, name, getattr(src, name))
    return dst


def _unique_slug(model, site_id, slug):
    existing = {row[0] for row in db.session.query(model.slug).filter(
        model.site_id == site_id).all()}
    candidate = slug
    n = 1
    while candidate in existing:
        candidate = f'{slug}_copy{n}'
        n += 1
    return candidate


def _notify(progress, percent, message):
    if progress is None:
        return
    try:
        progress(percent, message)
    except Exception as e:
        logger.debug('克隆进度回调失败：%s', e)


def clone_site(source_site_id, target, options=None, progress=None, job_id=None):
    """克隆站点，返回 {site_id, counts, elapsed_ms}；失败抛 CloneError。

    target 必须是包含 name/slug/domain 等字段的字典；传入 site_id 等
    其他类型时直接报错，避免误用。
    """
    if not isinstance(target, dict):
        raise TypeError('target 必须为包含站点字段的字典')
    started = datetime.now()
    source = db.session.get(Site, source_site_id)
    if source is None or source.is_deleted:
        raise CloneError('源站点不存在或已删除')

    opts = dict(DEFAULT_OPTIONS)
    opts.update(options or {})

    site = Site(
        name=target.get('name') or f'{source.name} 副本',
        slug=target['slug'],
        domain=target.get('domain') or None,
        subdomain=target.get('subdomain') or None,
        status='closed',
        theme=target.get('theme') or source.theme,
        is_default=False,
        seo_title=target.get('seo_title') or source.seo_title,
        seo_keywords=target.get('seo_keywords') or source.seo_keywords,
        seo_description=target.get('seo_description') or source.seo_description,
        sort_order=int(target.get('sort_order') or 0),
    )
    db.session.add(site)
    db.session.commit()
    _notify(progress, 5, '已创建目标站点')

    if job_id:
        try:
            from .site_jobs import set_progress
            set_progress(job_id, progress=5, message='已创建目标站点',
                         site_id=site.id)
        except Exception as e:
            logger.debug('更新克隆任务进度失败：%s', e)

    try:
        counts = _copy_content(source, site, opts, progress)
    except Exception as e:
        try:
            cleanup_partial_clone(site.id)
        except Exception:
            logger.exception('克隆失败后清理目标站点 %s 失败', site.id)
        raise CloneError(str(e)) from e

    elapsed = int((datetime.now() - started).total_seconds() * 1000)
    AuditLog.record(
        OP_CREATE, MODULE_SITE, target_id=site.id, target_name=site.name,
        detail={
            'action': 'clone',
            'source_site_id': source.id,
            'target_site_id': site.id,
            'counts': counts,
        },
        site_id=site.id,
    )
    _notify(progress, 100, '克隆完成')
    return {'site_id': site.id, 'counts': counts, 'elapsed_ms': elapsed}


def run_clone_job(job_id, source_site_id, target, options):
    """后台线程入口：执行克隆并把进度/结果写回任务记录。"""
    from .site_jobs import set_progress, fail_job
    from ..models.site_job import JOB_RUNNING, JOB_SUCCESS

    def _progress(percent, message):
        set_progress(job_id, progress=percent, message=message)

    set_progress(job_id, status=JOB_RUNNING, progress=0, message='开始克隆')
    try:
        clone_site(source_site_id, target, options=options,
                   progress=_progress, job_id=job_id)
        set_progress(job_id, status=JOB_SUCCESS, progress=100,
                     message='克隆完成')
    except CloneError as e:
        fail_job(job_id, str(e))
    except Exception as e:
        logger.exception('站点克隆任务失败：%s', e)
        fail_job(job_id, f'克隆失败：{e}')


def _copy_content(source, site, options, progress):
    counts = {}

    # 1. settings 白名单
    counts['settings'] = _copy_settings(source.id, site.id)
    _notify(progress, 10, '已复制站点设置')

    # 2. 栏目：按父级拓扑排序，父栏目先写
    column_map = _copy_columns(source.id, site.id)
    counts['columns'] = len(column_map)
    _notify(progress, 30, f'已复制栏目 {len(column_map)} 个')

    # 3. 栏目字段、字段值、翻译
    field_map = _copy_column_fields(column_map)
    counts['column_fields'] = len(field_map)
    counts['column_field_values'] = _copy_column_field_values(column_map, field_map)
    counts['column_translations'] = _copy_column_translations(column_map)
    _notify(progress, 40, '已复制栏目字段与翻译')

    # 4. 碎片（分组跨站共享，不新增 FragmentGroup）
    counts['fragments'] = _copy_fragments(source.id, site.id)
    _notify(progress, 45, '已复制碎片')

    # 5. 文章与字段值、翻译（不复制版本历史）
    article_map = _copy_articles(source.id, site.id, column_map)
    counts['articles'] = len(article_map)
    counts['article_field_values'] = _copy_article_field_values(
        article_map, field_map)
    counts['article_translations'] = _copy_article_translations(article_map)
    _notify(progress, 65, f'已复制文章 {len(article_map)} 篇')

    # 6. 页面构建（不复制修订历史）
    if options.get('builder', True):
        counts['builder_pages'] = _copy_builder_pages(
            source.id, site.id, column_map)
    else:
        counts['builder_pages'] = 0
    _notify(progress, 75, '已复制页面构建')

    # 7. 插件内容
    if options.get('plugins', True):
        counts.update(_copy_plugins(source.id, site.id, column_map))
    _notify(progress, 95, '已复制插件内容')
    return counts


def _copy_settings(source_id, target_id):
    rows = Setting.query.filter(
        Setting.site_id == source_id,
        Setting.key.in_(SETTINGS_ALLOWLIST)).all()
    for row in rows:
        Setting.set_site_override(row.key, row.value, target_id)
    db.session.commit()
    return len(rows)


def _copy_columns(source_id, target_id):
    """复制栏目树，返回 {旧 id: 新 id}。"""
    columns = Column.query.filter_by(site_id=source_id).all()
    mapping = {}
    remaining = list(columns)
    bulker = _Bulker()
    while remaining:
        progressed = False
        for col in list(remaining):
            if col.parent_id is not None and col.parent_id not in mapping:
                continue
            new_col = Column(
                site_id=target_id,
                parent_id=mapping.get(col.parent_id),
                slug=_unique_slug(Column, target_id, col.slug),
            )
            _copy_fields(col, new_col, skip=('id', 'site_id', 'parent_id', 'slug'))
            bulker.add(new_col)
            db.session.flush()
            mapping[col.id] = new_col.id
            remaining.remove(col)
            progressed = True
        if not progressed:
            # 源数据存在循环引用：剩余栏目按根栏目写入，避免死循环
            logger.warning('站点 %s 栏目树存在循环引用，剩余 %s 个按根栏目复制',
                           source_id, len(remaining))
            for col in remaining:
                new_col = Column(
                    site_id=target_id, parent_id=None,
                    slug=_unique_slug(Column, target_id, col.slug))
                _copy_fields(col, new_col,
                             skip=('id', 'site_id', 'parent_id', 'slug'))
                bulker.add(new_col)
                db.session.flush()
                mapping[col.id] = new_col.id
            remaining = []
    bulker.flush()
    return mapping


def _copy_column_fields(column_map):
    source_ids = list(column_map)
    if not source_ids:
        return {}
    fields = ColumnField.query.filter(
        ColumnField.column_id.in_(source_ids)).all()
    mapping = {}
    bulker = _Bulker()
    for field in fields:
        new_field = ColumnField(column_id=column_map[field.column_id])
        _copy_fields(field, new_field, skip=('id', 'column_id'))
        bulker.add(new_field)
        db.session.flush()
        mapping[field.id] = new_field.id
    bulker.flush()
    return mapping


def _copy_column_field_values(column_map, field_map):
    if not column_map:
        return 0
    rows = ColumnFieldValue.query.filter(
        ColumnFieldValue.column_id.in_(list(column_map))).all()
    bulker = _Bulker()
    count = 0
    for row in rows:
        new_field_id = field_map.get(row.field_id)
        if new_field_id is None:
            continue
        new_row = ColumnFieldValue(
            column_id=column_map[row.column_id], field_id=new_field_id,
            value=row.value)
        bulker.add(new_row)
        count += 1
    bulker.flush()
    return count


def _copy_column_translations(column_map):
    if not column_map:
        return 0
    rows = ColumnTranslation.query.filter(
        ColumnTranslation.column_id.in_(list(column_map))).all()
    bulker = _Bulker()
    for row in rows:
        new_row = ColumnTranslation(column_id=column_map[row.column_id])
        _copy_fields(row, new_row, skip=('id', 'column_id'))
        bulker.add(new_row)
    bulker.flush()
    return len(rows)


def _copy_fragments(source_id, target_id):
    rows = Fragment.query.filter_by(site_id=source_id).all()
    bulker = _Bulker()
    for row in rows:
        new_row = Fragment(
            site_id=target_id,
            slug=_unique_slug(Fragment, target_id, row.slug),
        )
        _copy_fields(row, new_row, skip=('id', 'site_id', 'slug'))
        bulker.add(new_row)
        db.session.flush()
        translations = FragmentTranslation.query.filter_by(
            fragment_id=row.id).all()
        for trans in translations:
            new_trans = FragmentTranslation(fragment_id=new_row.id)
            _copy_fields(trans, new_trans, skip=('id', 'fragment_id'))
            bulker.add(new_trans)
    bulker.flush()
    return len(rows)


def _copy_articles(source_id, target_id, column_map):
    articles = Article.query.filter_by(site_id=source_id).all()
    mapping = {}
    bulker = _Bulker()
    for article in articles:
        new_col_id = column_map.get(article.column_id)
        if new_col_id is None:
            logger.warning('文章 %s 所属栏目 %s 未映射，跳过',
                           article.id, article.column_id)
            continue
        new_article = Article(site_id=target_id, column_id=new_col_id)
        _copy_fields(article, new_article,
                     skip=('id', 'site_id', 'column_id'))
        bulker.add(new_article)
        db.session.flush()
        mapping[article.id] = new_article.id
    bulker.flush()
    return mapping


def _copy_article_field_values(article_map, field_map):
    if not article_map:
        return 0
    rows = ArticleFieldValue.query.filter(
        ArticleFieldValue.article_id.in_(list(article_map))).all()
    bulker = _Bulker()
    count = 0
    for row in rows:
        new_field_id = field_map.get(row.field_id)
        if new_field_id is None:
            continue
        new_row = ArticleFieldValue(
            article_id=article_map[row.article_id], field_id=new_field_id,
            value=row.value)
        bulker.add(new_row)
        count += 1
    bulker.flush()
    return count


def _copy_article_translations(article_map):
    if not article_map:
        return 0
    rows = ArticleTranslation.query.filter(
        ArticleTranslation.article_id.in_(list(article_map))).all()
    bulker = _Bulker()
    for row in rows:
        new_row = ArticleTranslation(article_id=article_map[row.article_id])
        _copy_fields(row, new_row, skip=('id', 'article_id'))
        bulker.add(new_row)
    bulker.flush()
    return len(rows)


def _copy_builder_pages(source_id, target_id, column_map):
    pages = BuilderPage.query.filter_by(site_id=source_id).all()
    bulker = _Bulker()
    count = 0
    for page in pages:
        new_col_id = column_map.get(page.column_id) if page.column_id else None
        if page.column_id is not None and new_col_id is None:
            continue
        new_page = BuilderPage(
            site_id=target_id, scope=page.scope, column_id=new_col_id,
            name=page.name, status=page.status,
            draft_json=page.draft_json, published_json=page.published_json,
            published_at=page.published_at, author_id=page.author_id)
        bulker.add(new_page)
        count += 1
    bulker.flush()
    return count


# 直接含 site_id 的插件表，用于估算与删除
_PLUGIN_SITE_TABLES = (
    ('表单', 'forms'), ('产品', 'products'), ('招聘', 'recruit_jobs'),
    ('友情链接', 'friend_links'), ('轮播组', 'banner_groups'),
    ('轮播图', 'banners'), ('教程分类', 'tutorial_categories'),
    ('教程', 'tutorials'),
)


def _has_table(name):
    try:
        return inspect(db.engine).has_table(name)
    except SQLAlchemyError:
        return False


def _copy_plugins(source_id, target_id, column_map):
    """按「父表 → 子表」顺序复制插件内容，未安装的表直接跳过。"""
    counts = {}
    counts.update(_copy_forms(source_id, target_id))
    counts.update(_copy_products(source_id, target_id, column_map))
    counts.update(_copy_recruit(source_id, target_id))
    counts.update(_copy_friend_links(source_id, target_id))
    counts.update(_copy_banners(source_id, target_id))
    counts.update(_copy_tutorials(source_id, target_id))
    return counts


def _copy_forms(source_id, target_id):
    if not _has_table('forms'):
        return {'forms': 0, 'form_fields': 0, 'form_translations': 0}
    from plugins.form.models import Form, FormField, FormTranslation

    forms = Form.query.filter_by(site_id=source_id).all()
    bulker = _Bulker()
    form_map = {}
    for form in forms:
        new_form = Form(
            site_id=target_id,
            slug=_unique_slug(Form, target_id, form.slug))
        _copy_fields(form, new_form, skip=('id', 'site_id', 'slug'))
        bulker.add(new_form)
        db.session.flush()
        form_map[form.id] = new_form.id
    field_count = 0
    trans_count = 0
    for old_id, new_id in form_map.items():
        fields = FormField.query.filter_by(form_id=old_id).all()
        for field in fields:
            new_field = FormField(form_id=new_id)
            _copy_fields(field, new_field, skip=('id', 'form_id'))
            bulker.add(new_field)
            field_count += 1
        translations = FormTranslation.query.filter_by(form_id=old_id).all()
        for trans in translations:
            new_trans = FormTranslation(form_id=new_id)
            _copy_fields(trans, new_trans, skip=('id', 'form_id'))
            bulker.add(new_trans)
            trans_count += 1
    bulker.flush()
    return {'forms': len(forms), 'form_fields': field_count,
            'form_translations': trans_count}


def _copy_products(source_id, target_id, column_map):
    if not _has_table('products'):
        return {'products': 0, 'product_translations': 0}
    from plugins.product.models import Product, ProductTranslation

    products = Product.query.filter_by(site_id=source_id).all()
    bulker = _Bulker()
    product_map = {}
    for product in products:
        new_col_id = column_map.get(product.column_id)
        if new_col_id is None:
            continue
        new_product = Product(site_id=target_id, column_id=new_col_id)
        _copy_fields(product, new_product,
                     skip=('id', 'site_id', 'column_id'))
        bulker.add(new_product)
        db.session.flush()
        product_map[product.id] = new_product.id
    trans_count = 0
    for old_id, new_id in product_map.items():
        translations = ProductTranslation.query.filter_by(
            product_id=old_id).all()
        for trans in translations:
            new_trans = ProductTranslation(product_id=new_id)
            _copy_fields(trans, new_trans, skip=('id', 'product_id'))
            bulker.add(new_trans)
            trans_count += 1
    bulker.flush()
    return {'products': len(product_map),
            'product_translations': trans_count}


def _copy_recruit(source_id, target_id):
    if not _has_table('recruit_jobs'):
        return {'recruit_jobs': 0, 'recruit_job_translations': 0}
    from plugins.recruit.models import RecruitJob, RecruitJobTranslation

    jobs = RecruitJob.query.filter_by(site_id=source_id).all()
    bulker = _Bulker()
    job_map = {}
    for job in jobs:
        new_job = RecruitJob(site_id=target_id)
        _copy_fields(job, new_job, skip=('id', 'site_id'))
        bulker.add(new_job)
        db.session.flush()
        job_map[job.id] = new_job.id
    trans_count = 0
    for old_id, new_id in job_map.items():
        translations = RecruitJobTranslation.query.filter_by(
            job_id=old_id).all()
        for trans in translations:
            new_trans = RecruitJobTranslation(job_id=new_id)
            _copy_fields(trans, new_trans, skip=('id', 'job_id'))
            bulker.add(new_trans)
            trans_count += 1
    bulker.flush()
    return {'recruit_jobs': len(job_map),
            'recruit_job_translations': trans_count}


def _copy_friend_links(source_id, target_id):
    if not _has_table('friend_links'):
        return {'friend_links': 0, 'friend_link_translations': 0}
    from plugins.friend_link.models import FriendLink, FriendLinkTranslation

    links = FriendLink.query.filter_by(site_id=source_id).all()
    bulker = _Bulker()
    link_map = {}
    for link in links:
        new_link = FriendLink(site_id=target_id)
        _copy_fields(link, new_link, skip=('id', 'site_id'))
        bulker.add(new_link)
        db.session.flush()
        link_map[link.id] = new_link.id
    trans_count = 0
    for old_id, new_id in link_map.items():
        translations = FriendLinkTranslation.query.filter_by(
            link_id=old_id).all()
        for trans in translations:
            new_trans = FriendLinkTranslation(link_id=new_id)
            _copy_fields(trans, new_trans, skip=('id', 'link_id'))
            bulker.add(new_trans)
            trans_count += 1
    bulker.flush()
    return {'friend_links': len(link_map),
            'friend_link_translations': trans_count}


def _copy_banners(source_id, target_id):
    if not _has_table('banner_groups'):
        return {'banner_groups': 0, 'banners': 0}
    from plugins.banner.models import BannerGroup, Banner

    groups = BannerGroup.query.filter_by(site_id=source_id).all()
    bulker = _Bulker()
    group_map = {}
    for group in groups:
        new_group = BannerGroup(
            site_id=target_id,
            slug=_unique_slug(BannerGroup, target_id, group.slug))
        _copy_fields(group, new_group, skip=('id', 'site_id', 'slug'))
        bulker.add(new_group)
        db.session.flush()
        group_map[group.id] = new_group.id
    banner_count = 0
    for old_id, new_id in group_map.items():
        for banner in Banner.query.filter_by(group_id=old_id).all():
            new_banner = Banner(site_id=target_id, group_id=new_id)
            _copy_fields(banner, new_banner,
                         skip=('id', 'site_id', 'group_id', 'image_id'))
            # 上传资产不随克隆复制，避免引用源站文件索引
            new_banner.image_id = None
            bulker.add(new_banner)
            banner_count += 1
    bulker.flush()
    return {'banner_groups': len(group_map), 'banners': banner_count}


def _copy_tutorials(source_id, target_id):
    if not _has_table('tutorial_categories'):
        return {'tutorial_categories': 0, 'tutorials': 0}
    from plugins.tutorial.models import TutorialCategory, Tutorial

    categories = TutorialCategory.query.filter_by(site_id=source_id).all()
    bulker = _Bulker()
    category_map = {}
    for category in categories:
        new_category = TutorialCategory(
            site_id=target_id,
            slug=_unique_slug(TutorialCategory, target_id, category.slug))
        _copy_fields(category, new_category,
                     skip=('id', 'site_id', 'slug'))
        bulker.add(new_category)
        db.session.flush()
        category_map[category.id] = new_category.id
    tutorial_count = 0
    for old_id, new_id in category_map.items():
        for tutorial in Tutorial.query.filter_by(category_id=old_id).all():
            new_tutorial = Tutorial(
                site_id=target_id, category_id=new_id,
                slug=_unique_slug(Tutorial, target_id, tutorial.slug))
            _copy_fields(tutorial, new_tutorial,
                         skip=('id', 'site_id', 'category_id', 'slug'))
            bulker.add(new_tutorial)
            tutorial_count += 1
    bulker.flush()
    return {'tutorial_categories': len(category_map),
            'tutorials': tutorial_count}


# ============================================================
# 清理与回收站
# ============================================================

def _delete_plugin_content(site_id):
    """删除站点插件内容（含提交记录），表不存在时跳过。"""
    insp = inspect(db.engine)

    def _exec(sql):
        try:
            db.session.execute(text(sql), {'sid': site_id})
        except SQLAlchemyError as e:
            logger.warning('清理站点 %s 数据失败：%s', site_id, e)

    if insp.has_table('form_submission_values'):
        _exec('DELETE FROM form_submission_values WHERE submission_id IN '
              '(SELECT id FROM form_submissions WHERE form_id IN '
              '(SELECT id FROM forms WHERE site_id = :sid))')
    if insp.has_table('form_submissions'):
        _exec('DELETE FROM form_submissions WHERE form_id IN '
              '(SELECT id FROM forms WHERE site_id = :sid)')
    if insp.has_table('form_translations'):
        _exec('DELETE FROM form_translations WHERE form_id IN '
              '(SELECT id FROM forms WHERE site_id = :sid)')
    if insp.has_table('form_fields'):
        _exec('DELETE FROM form_fields WHERE form_id IN '
              '(SELECT id FROM forms WHERE site_id = :sid)')
    if insp.has_table('forms'):
        _exec('DELETE FROM forms WHERE site_id = :sid')

    if insp.has_table('product_translations'):
        _exec('DELETE FROM product_translations WHERE product_id IN '
              '(SELECT id FROM products WHERE site_id = :sid)')
    if insp.has_table('products'):
        _exec('DELETE FROM products WHERE site_id = :sid')

    if insp.has_table('recruit_applications'):
        _exec('DELETE FROM recruit_applications WHERE job_id IN '
              '(SELECT id FROM recruit_jobs WHERE site_id = :sid)')
    if insp.has_table('recruit_job_translations'):
        _exec('DELETE FROM recruit_job_translations WHERE job_id IN '
              '(SELECT id FROM recruit_jobs WHERE site_id = :sid)')
    if insp.has_table('recruit_jobs'):
        _exec('DELETE FROM recruit_jobs WHERE site_id = :sid')

    if insp.has_table('friend_link_translations'):
        _exec('DELETE FROM friend_link_translations WHERE link_id IN '
              '(SELECT id FROM friend_links WHERE site_id = :sid)')
    if insp.has_table('friend_links'):
        _exec('DELETE FROM friend_links WHERE site_id = :sid')

    if insp.has_table('banners'):
        _exec('DELETE FROM banners WHERE site_id = :sid')
    if insp.has_table('banner_groups'):
        _exec('DELETE FROM banner_groups WHERE site_id = :sid')

    if insp.has_table('tutorials'):
        _exec('DELETE FROM tutorials WHERE site_id = :sid')
    if insp.has_table('tutorial_categories'):
        _exec('DELETE FROM tutorial_categories WHERE site_id = :sid')


def delete_all_site_content(site_id, commit=True):
    """删除站点全部内容，返回受影响表数。

    commit=True 时立即提交；commit=False 时仅 flush，由调用方统一提交，
    任一步骤抛出异常都会回滚本次删除，避免留下部分清空的数据。
    """
    if site_id == DEFAULT_SITE_ID:
        raise ValueError('默认站点内容不可批量删除')
    try:
        tables = _delete_site_content(site_id)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return tables
    except Exception:
        db.session.rollback()
        raise


def _delete_site_content(site_id):
    """按「子表 → 父表」顺序删除站点内容，不负责提交事务。"""
    tables = 0

    _delete_plugin_content(site_id)
    tables += 1

    page_ids = [row[0] for row in db.session.query(BuilderPage.id).filter_by(
        site_id=site_id).all()]
    if page_ids:
        from ..models.builder import BuilderRevision
        BuilderRevision.query.filter(
            BuilderRevision.page_id.in_(page_ids)).delete(
            synchronize_session=False)
    BuilderPage.query.filter_by(site_id=site_id).delete(
        synchronize_session=False)
    tables += 1

    article_ids = [row[0] for row in db.session.query(Article.id).filter_by(
        site_id=site_id).all()]
    if article_ids:
        from ..models.workflow import ArticleVersion
        ArticleVersion.query.filter(
            ArticleVersion.article_id.in_(article_ids)).delete(
            synchronize_session=False)
    ArticleFieldValue.query.filter(
        ArticleFieldValue.article_id.in_(article_ids)).delete(
        synchronize_session=False) if article_ids else None
    ArticleTranslation.query.filter(
        ArticleTranslation.article_id.in_(article_ids)).delete(
        synchronize_session=False) if article_ids else None
    Article.query.filter_by(site_id=site_id).delete(
        synchronize_session=False)
    tables += 1

    column_ids = [row[0] for row in db.session.query(Column.id).filter_by(
        site_id=site_id).all()]
    if column_ids:
        ColumnFieldValue.query.filter(
            ColumnFieldValue.column_id.in_(column_ids)).delete(
            synchronize_session=False)
        ColumnTranslation.query.filter(
            ColumnTranslation.column_id.in_(column_ids)).delete(
            synchronize_session=False)
        ColumnField.query.filter(
            ColumnField.column_id.in_(column_ids)).delete(
            synchronize_session=False)
    # 先解除自引用，避免 MySQL 外键阻止删除父栏目
    Column.query.filter_by(site_id=site_id).update(
        {'parent_id': None}, synchronize_session=False)
    Column.query.filter_by(site_id=site_id).delete(synchronize_session=False)
    tables += 1

    fragment_ids = [row[0] for row in db.session.query(Fragment.id).filter_by(
        site_id=site_id).all()]
    if fragment_ids:
        FragmentTranslation.query.filter(
            FragmentTranslation.fragment_id.in_(fragment_ids)).delete(
            synchronize_session=False)
    Fragment.query.filter_by(site_id=site_id).delete(
        synchronize_session=False)
    tables += 1

    Setting.query.filter(Setting.site_id == site_id).delete(
        synchronize_session=False)
    tables += 1
    return tables


def cleanup_partial_clone(target_site_id):
    """清理克隆失败留下的目标站点及其内容，返回清理表数。"""
    site = db.session.get(Site, target_site_id)
    if site is None:
        return 0
    if site.id == DEFAULT_SITE_ID or site.is_default:
        return 0
    try:
        tables = delete_all_site_content(target_site_id)
        db.session.delete(site)
        db.session.commit()
        return tables
    except Exception:
        db.session.rollback()
        raise


def move_site_to_recycle(site, deleted_by=None, days=RECYCLE_DAYS):
    """站点软删除并写入回收站，内容保留。"""
    if site.id == DEFAULT_SITE_ID or site.is_default:
        raise ValueError('默认站点不可删除')
    site.is_deleted = True
    site.status = 'closed'
    record = SiteRecycleBin.query.filter_by(
        site_id=site.id, restored_at=None).first()
    if record is None:
        record = SiteRecycleBin(
            site_id=site.id,
            slug=site.slug,
            name=site.name,
            deleted_by=deleted_by,
            deleted_at=datetime.now(),
            purge_at=datetime.now() + timedelta(days=days),
            snapshot_json=json.dumps({
                'slug': site.slug, 'domain': site.domain,
                'domains': [row.domain for row in (site.domain_entries or [])],
                'subdomain': site.subdomain, 'theme': site.theme,
                'status': site.status,
            }, ensure_ascii=False),
        )
        db.session.add(record)
    else:
        record.deleted_by = deleted_by
        record.deleted_at = datetime.now()
        record.purge_at = datetime.now() + timedelta(days=days)
    db.session.commit()
    AuditLog.record(OP_DELETE, MODULE_SITE, target_id=site.id,
                    target_name=site.name,
                    detail={'action': 'recycle', 'purge_at': str(record.purge_at)},
                    site_id=site.id)
    return record


def restore_site(record):
    """从回收站恢复站点；恢复后保持关闭，由管理员手动开放。"""
    site = db.session.get(Site, record.site_id)
    if site is None:
        raise ValueError('站点不存在，无法恢复')
    site.is_deleted = False
    site.status = 'closed'
    record.restored_at = datetime.now()
    db.session.commit()
    AuditLog.record(OP_UPDATE, MODULE_SITE, target_id=site.id,
                    target_name=site.name,
                    detail={'action': 'restore'}, site_id=site.id)
    return site


def purge_site(site_id, created_by=None, require_backup=True):
    """彻底删除站点：先自动导出备份，再删除内容与站点行。"""
    site = db.session.get(Site, site_id)
    if site is None:
        return False
    if site.id == DEFAULT_SITE_ID or site.is_default:
        raise ValueError('默认站点不可删除')

    if require_backup:
        from .site_backup import export_site
        export_site(site_id, created_by=created_by)

    delete_all_site_content(site_id)
    db.session.delete(site)
    db.session.commit()
    AuditLog.record(OP_DELETE, MODULE_SITE, target_id=site_id,
                    target_name=site.name,
                    detail={'action': 'purge'}, site_id=site_id)
    return True


def purge_expired_recycle_bin(now=None):
    """处理到期的回收站记录：自动备份 → 彻底删除；失败保留记录。"""
    now = now or datetime.now()
    records = SiteRecycleBin.query.filter(
        SiteRecycleBin.purge_at <= now,
        SiteRecycleBin.restored_at.is_(None),
    ).all()
    purged = 0
    for record in records:
        try:
            purge_site(record.site_id, require_backup=True)
        except Exception as e:
            db.session.rollback()
            logger.warning('回收站站点 %s 自动清理失败，保留记录：%s',
                           record.site_id, e)
            continue
        db.session.delete(record)
        db.session.commit()
        purged += 1
    return purged
