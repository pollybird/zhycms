"""文章业务逻辑（service 层）。

从 app/admin/content/article.py 的 _save_article / _save_article_translations
抽离而来。视图层只负责 HTTP 协议转换，业务逻辑在此独立可测。
"""
from datetime import datetime

from flask import current_app
from flask_babel import gettext as _gettext

from ..extensions import db
from ..constants import Upload as _U
from ..models.article import Article, ArticleFieldValue, ArticleTranslation
from ..models.workflow import (
    STATUS_DRAFT, STATUS_REVIEW, STATUS_PUBLISHED, STATUS_ARCHIVED,
    ArticleVersion,
)
from ..utils.helpers import audit_log, clear_content_cache
from ..utils.uploads import save_upload_file
from ..utils.i18n_content import get_available_locales, get_default_locale
from ..models.audit import OP_CREATE, OP_UPDATE, MODULE_ARTICLE


def save_article(article, column, fields, *, form_data, files_data, current_user):
    """创建或更新文章，自动同步 enabled ↔ status，创建版本快照。

    :param article: Article 实例；为 None 表示新建
    :param column:  所属 Column 实例
    :param fields:  该栏目的自定义字段列表
    :param form_data:  表单数据（request.form）
    :param files_data: 文件数据（request.files）
    :param current_user: 当前登录用户
    :returns: (article_or_None, messages)
              messages 为 [(category, message), ...]，调用方负责 flash
    """
    messages = []

    def _flash(msg, category='info'):
        messages.append((category, msg))

    title = (form_data.get('title') or '').strip()
    if not title:
        _flash(_gettext('文章标题必填'), 'danger')
        return None, messages

    is_new = article is None
    if is_new:
        article = Article(column_id=column.id)
    else:
        # 清理旧的自定义字段值，重建
        ArticleFieldValue.query.filter_by(article_id=article.id).delete()

    article.title = title
    article.summary = (form_data.get('summary') or '').strip()
    article.content = form_data.get('content') or ''
    article.author = (form_data.get('author') or '').strip()
    article.source = (form_data.get('source') or '').strip()
    article.sort_order = int(form_data.get('sort_order') or 0)

    # 工作流状态（优先新的 status，兼容旧的 is_enabled）
    status = form_data.get('status') or ''
    if status in (STATUS_DRAFT, STATUS_REVIEW, STATUS_PUBLISHED, STATUS_ARCHIVED):
        # 无发布权限者不允许直接把内容置为「已发布」，自动改为待审核走流程
        if status == STATUS_PUBLISHED and not (
            current_user.is_super or current_user.has_permission('content:publish')):
            status = STATUS_REVIEW
            _flash(_gettext('您无「发布」权限，状态已自动改为「待审核」'), 'warning')
        article.status = status
    elif not is_new:
        # 编辑时保持原状态
        pass
    else:
        # 新建默认草稿
        article.status = STATUS_DRAFT
    # 同步 is_enabled 字段
    article.sync_enabled_from_status()

    # SEO
    article.seo_title = (form_data.get('seo_title') or '').strip()
    article.seo_keywords = (form_data.get('seo_keywords') or '').strip()
    article.seo_description = (form_data.get('seo_description') or '').strip()

    # 发布时间
    published_str = form_data.get('published_at') or ''
    if published_str:
        try:
            article.published_at = datetime.strptime(published_str, '%Y-%m-%d %H:%M')
        except ValueError:
            article.published_at = datetime.now()
    elif is_new:
        article.published_at = datetime.now()

    # 封面图
    cover_file = files_data.get('cover')
    if cover_file and cover_file.filename:
        rel, url, err = save_upload_file(cover_file, sub_dir='article',
                                         allowed_exts=list(_U.IMAGE_EXTS),
                                         max_size=10 * 1024 * 1024)
        if err:
            _flash(_gettext('封面图上传失败：{0}').format(err), 'danger')
            return None, messages
        article.cover = url
    elif form_data.get('cover_remove') == 'on':
        article.cover = None

    # created_by / updated_by
    now = datetime.now()
    uid = getattr(current_user, 'id', None)
    if is_new:
        article.created_by = uid
        db.session.add(article)
        db.session.flush()
    else:
        # 若编辑把待审核文章改回草稿，清除驳回原因
        if article.status == STATUS_DRAFT:
            article.reject_reason = None
    article.updated_by = uid
    article.updated_at = now

    # 自定义字段值
    for f in fields:
        value = None
        if f.field_type in ('image', 'file'):
            file_obj = files_data.get(f'field_{f.id}')
            if file_obj and file_obj.filename:
                allowed = None
                maxsize = None
                if f.field_type == 'file':
                    allowed = f.allowed_exts.split(',') if f.allowed_exts else None
                    maxsize = f.max_size
                else:
                    allowed = list(_U.IMAGE_EXTS)
                rel, url, err = save_upload_file(file_obj, sub_dir='article',
                                                 allowed_exts=allowed, max_size=maxsize)
                if err:
                    _flash(_gettext('字段 {0} 上传失败：{1}').format(f.label, err), 'danger')
                    return None, messages
                value = url
            elif form_data.get(f'field_{f.id}_remove') == 'on':
                value = ''
            else:
                value = (form_data.get(f'field_{f.id}_existing') or '')
        else:
            value = form_data.get(f'field_{f.id}') or ''

        if f.is_required and not value:
            _flash(_gettext('字段 {0} 为必填').format(f.label), 'danger')
            return None, messages

        if value is not None:
            v = ArticleFieldValue(article_id=article.id, field_id=f.id, value=value)
            db.session.add(v)

    # v2.5.0：保存各语种翻译（非默认语言）
    _save_article_translations(article, form_data)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        _flash(_gettext('文章保存失败（数据库错误）'), 'danger')
        current_app.logger.exception('article save DB error')
        return None, messages

    # 保存版本快照（必须在 commit 后 article.id 已存在且字段值已写库）
    note = '新建' if is_new else '编辑修改'
    try:
        ArticleVersion.snapshot(article, status_snapshot=article.status,
                                note=note, created_by=uid)
        db.session.commit()
    except Exception:
        current_app.logger.exception('article snapshot failed')
        # 快照失败不影响主事务
        try:
            db.session.rollback()
        except Exception:
            pass

    # 清缓存 + 审计日志
    clear_content_cache(column_id=column.id, article_id=article.id)
    if is_new:
        _flash(_gettext('文章创建成功'), 'success')
        audit_log(OP_CREATE, MODULE_ARTICLE, article.id, article.title,
                  {'column_id': column.id, 'status': article.status})
    else:
        _flash(_gettext('文章保存成功'), 'success')
        audit_log(OP_UPDATE, MODULE_ARTICLE, article.id, article.title,
                  {'column_id': column.id, 'status': article.status})
    return article, messages


def _save_article_translations(article, form_data):
    """保存文章各语种翻译（v2.5.0）。

    表单字段命名：{field}_{locale}，如 title_en / content_en。
    非默认语言且标题非空 → upsert 翻译记录；标题为空 → 删除该翻译（fallback 默认语言）。
    """
    default_locale = get_default_locale()
    locales = [l for l in get_available_locales() if l != default_locale]
    if not locales:
        return

    # 已有翻译记录（按 locale 索引）
    existing = {tr.locale: tr for tr in article.translations}

    trans_fields = ('title', 'summary', 'content', 'seo_title', 'seo_keywords', 'seo_description')
    for loc in locales:
        tr_title = (form_data.get(f'title_{loc}') or '').strip()
        if not tr_title:
            # 空标题：删除该翻译（fallback 默认语言）
            if loc in existing:
                db.session.delete(existing[loc])
            continue
        tr = existing.get(loc)
        if tr is None:
            tr = ArticleTranslation(article_id=article.id, locale=loc)
            db.session.add(tr)
        tr.title = tr_title
        for fld in trans_fields[1:]:
            setattr(tr, fld, (form_data.get(f'{fld}_{loc}') or '').strip()
                    if fld != 'content' else (form_data.get(f'{fld}_{loc}') or ''))
