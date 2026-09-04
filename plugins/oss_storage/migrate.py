"""本地文件 → 云端对象存储一键迁移（v2.4.0 oss_storage 插件）。

特点：
- dry-run 预览：统计待上传文件数（含本地缺失明细）与待改写 URL 数；
- 幂等可重入：云端已存在的对象（driver.exists）跳过，中断后重跑安全；
- 本地文件保留不删（迁移确认无误后由管理员手工清理，uploads/demo 不动）；
- 内容 URL 改写：文章正文/封面、碎片、自定义字段值、设置项中的
  /static/uploads/ 前缀统一替换为云域名（REPLACE() 函数，三种库通用）。
"""
import os

import sqlalchemy as sa
from sqlalchemy import func, select

from flask import current_app

from app.extensions import db
from app.models.upload import UploadedFile
from app.models.setting import Setting

LOCAL_URL_PREFIX = '/static/uploads/'

# 含上传文件 URL 的内容列（表名, 列名）
_CONTENT_COLUMNS = [
    ('articles', 'content'),
    ('articles', 'cover'),
    ('article_versions', 'content'),
    ('article_versions', 'cover'),
    ('fragments', 'value'),
    ('column_field_values', 'value'),
    ('article_field_values', 'value'),
]


def _existing_content_columns():
    """按实际数据库 schema 过滤内容列，避免某张表/列不存在导致语句失败
    回滚连累其他表的更新。"""
    from sqlalchemy import inspect
    try:
        insp = inspect(db.engine)
        result = []
        for table, col in _CONTENT_COLUMNS:
            try:
                cols = [c['name'] for c in insp.get_columns(table)]
                if col in cols:
                    result.append((table, col))
            except Exception:
                continue
        return result
    except Exception:
        return list(_CONTENT_COLUMNS)


def _local_abs_path(stored_name):
    """stored_name 形如 uploads/article/.../x.jpg → 本地绝对路径。"""
    return os.path.join(
        current_app.static_folder,
        (stored_name or '').replace('/', os.sep))


def _local_files():
    """待迁移的上传记录：storage=local 且非演示图片。"""
    records = UploadedFile.query.filter_by(storage='local').all()
    return [r for r in records
            if r.stored_name and not r.stored_name.startswith('uploads/demo/')]


def dry_run():
    """预览：返回统计 dict（不写任何数据）。"""
    records = _local_files()
    on_disk, missing = [], []
    for r in records:
        (on_disk if os.path.exists(_local_abs_path(r.stored_name)) else missing).append(r)

    url_hits = 0
    for table, col in _existing_content_columns():
        try:
            tbl = sa.table(table, sa.column(col, sa.Text))
            n = db.session.execute(
                select(func.count()).select_from(tbl)
                .where(tbl.c[col].like('%{0}%'.format(LOCAL_URL_PREFIX)))
            ).scalar()
            url_hits += int(n or 0)
        except Exception:
            pass
    try:
        n = db.session.execute(
            select(func.count()).select_from(sa.table('settings', sa.column('value', sa.Text)))
            .where(sa.text('value LIKE :p')),
            {'p': '%{0}%'.format(LOCAL_URL_PREFIX)}
        ).scalar()
        url_hits += int(n or 0)
    except Exception:
        pass

    return {
        'files_total': len(records),
        'files_on_disk': len(on_disk),
        'files_missing': len(missing),
        'missing_names': [r.original_name for r in missing[:50]],
        'url_hits': url_hits,
    }


def run(driver):
    """执行迁移。返回 (stats, error)；error 非 None 表示中断（可重入重跑）。"""
    records = _local_files()
    uploaded, skipped = [], []

    for r in records:
        local_path = _local_abs_path(r.stored_name)
        if not os.path.exists(local_path):
            skipped.append(r.original_name)
            continue
        try:
            key = r.stored_name
            if not driver.exists(key):
                driver.save(local_path, key)
            r.url = driver.public_url(key)
            # 缩略图
            if r.thumb_path:
                tpath = _local_abs_path(r.thumb_path)
                if os.path.exists(tpath):
                    if not driver.exists(r.thumb_path):
                        driver.save(tpath, r.thumb_path)
                    r.thumb_url = driver.public_url(r.thumb_path)
            r.storage = driver.name
            uploaded.append(r.original_name)
        except Exception as e:
            db.session.rollback()
            return {
                'uploaded': len(uploaded), 'skipped': len(skipped),
                'url_rewritten': 0,
            }, '{0}：{1}'.format(r.original_name, e)

    db.session.commit()

    # 内容 URL 前缀改写
    new_prefix = driver.public_url('uploads/')  # https://cdn.example.com/uploads/
    url_rewritten = _rewrite_urls(LOCAL_URL_PREFIX, new_prefix)

    return {
        'uploaded': len(uploaded),
        'skipped': len(skipped),
        'url_rewritten': url_rewritten,
    }, None


def _rewrite_urls(old_prefix, new_prefix):
    """把内容列与设置项中的 old_prefix 替换为 new_prefix（跨库通用 REPLACE 函数）。

    统一通过 db.session.execute 执行，连接生命周期由 Session 管理，
    避免手工获取连接在 commit 后失效。
    """
    changed = 0
    for table, col in _existing_content_columns():
        try:
            tbl = sa.table(table, sa.column(col, sa.Text))
            n = db.session.execute(
                select(func.count()).select_from(tbl)
                .where(tbl.c[col].like('%{0}%'.format(old_prefix)))
            ).scalar()
            if n:
                result = db.session.execute(
                    tbl.update()
                    .where(tbl.c[col].like('%{0}%'.format(old_prefix)))
                    .values(**{col: func.replace(tbl.c[col], old_prefix, new_prefix)})
                )
                changed += int(result.rowcount or n)
        except Exception:
            db.session.rollback()
    try:
        for s in Setting.query.filter(Setting.value.like('%{0}%'.format(old_prefix))).all():
            s.value = s.value.replace(old_prefix, new_prefix)
            changed += 1
    except Exception:
        db.session.rollback()
    db.session.commit()
    return changed
