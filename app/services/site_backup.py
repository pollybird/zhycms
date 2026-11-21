"""站点级备份：跨数据库一致的 ZIP 导出与导入。

ZIP 结构：manifest.json + data/{table}.jsonl + uploads/site{sid}/...
导出逐行写入，不一次性加载全站数据；导入按「父表 → 子表」重映射主键，
并重建上传文件索引。会员、提交记录、日志、版本历史与用户/角色表不导出。
"""
import hashlib
import io
import json
import logging
import mimetypes
import os
import re
import stat
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import current_app
from sqlalchemy import Date, DateTime, MetaData, Table, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models.audit import (
    AuditLog, MODULE_BACKUP, OP_BACKUP_RESTORE, OP_DELETE, OP_EXPORT, OP_OTHER,
)
from ..models.setting import Setting
from ..models.site import Site, DEFAULT_SITE_ID
from ..models.upload import UploadedFile

logger = logging.getLogger(__name__)

FORMAT_NAME = 'zhycms-site-backup'
FORMAT_VERSION = 1
FILENAME_RE = re.compile(r'^site\d+-[a-z0-9_-]+-\d{8}_\d{6}\.zip$')
MAX_ARCHIVE_MB = 4096
DOWNLOAD_MAX_AGE = 30 * 60  # 签名下载 30 分钟有效

# 表清单显式维护：父表在前，子表通过父 ID 关联；排除会员/提交/日志/版本/用户角色
BACKUP_TABLES = (
    {'name': 'settings', 'site': True, 'where': 'site_id = :sid', 'fks': {}},
    {'name': 'fragments', 'site': True, 'where': 'site_id = :sid', 'fks': {}},
    {'name': 'fragment_translations', 'site': False,
     'where': 'fragment_id IN (SELECT id FROM fragments WHERE site_id = :sid)',
     'fks': {'fragment_id': 'fragments'}},
    {'name': 'columns', 'site': True, 'where': 'site_id = :sid',
     'fks': {'parent_id': 'columns'}},
    {'name': 'column_fields', 'site': False,
     'where': 'column_id IN (SELECT id FROM columns WHERE site_id = :sid)',
     'fks': {'column_id': 'columns'}},
    {'name': 'column_field_values', 'site': False,
     'where': 'column_id IN (SELECT id FROM columns WHERE site_id = :sid) '
              'AND field_id IN (SELECT id FROM column_fields WHERE column_id IN '
              '(SELECT id FROM columns WHERE site_id = :sid))',
     'fks': {'column_id': 'columns', 'field_id': 'column_fields'}},
    {'name': 'column_translations', 'site': False,
     'where': 'column_id IN (SELECT id FROM columns WHERE site_id = :sid)',
     'fks': {'column_id': 'columns'}},
    {'name': 'articles', 'site': True, 'where': 'site_id = :sid',
     'fks': {'column_id': 'columns'}},
    {'name': 'article_field_values', 'site': False,
     'where': 'article_id IN (SELECT id FROM articles WHERE site_id = :sid)',
     'fks': {'article_id': 'articles', 'field_id': 'column_fields'}},
    {'name': 'article_translations', 'site': False,
     'where': 'article_id IN (SELECT id FROM articles WHERE site_id = :sid)',
     'fks': {'article_id': 'articles'}},
    {'name': 'builder_pages', 'site': True, 'where': 'site_id = :sid',
     'fks': {'column_id': 'columns'}},
    {'name': 'forms', 'site': True, 'where': 'site_id = :sid', 'fks': {}},
    {'name': 'form_fields', 'site': False,
     'where': 'form_id IN (SELECT id FROM forms WHERE site_id = :sid)',
     'fks': {'form_id': 'forms'}},
    {'name': 'form_translations', 'site': False,
     'where': 'form_id IN (SELECT id FROM forms WHERE site_id = :sid)',
     'fks': {'form_id': 'forms'}},
    {'name': 'products', 'site': True, 'where': 'site_id = :sid',
     'fks': {'column_id': 'columns'}},
    {'name': 'product_translations', 'site': False,
     'where': 'product_id IN (SELECT id FROM products WHERE site_id = :sid)',
     'fks': {'product_id': 'products'}},
    {'name': 'recruit_jobs', 'site': True, 'where': 'site_id = :sid', 'fks': {}},
    {'name': 'recruit_job_translations', 'site': False,
     'where': 'job_id IN (SELECT id FROM recruit_jobs WHERE site_id = :sid)',
     'fks': {'job_id': 'recruit_jobs'}},
    {'name': 'friend_links', 'site': True, 'where': 'site_id = :sid', 'fks': {}},
    {'name': 'friend_link_translations', 'site': False,
     'where': 'link_id IN (SELECT id FROM friend_links WHERE site_id = :sid)',
     'fks': {'link_id': 'friend_links'}},
    {'name': 'banner_groups', 'site': True, 'where': 'site_id = :sid', 'fks': {}},
    {'name': 'banners', 'site': True, 'where': 'site_id = :sid',
     'fks': {'group_id': 'banner_groups'}},
    {'name': 'tutorial_categories', 'site': True, 'where': 'site_id = :sid',
     'fks': {}},
    {'name': 'tutorials', 'site': True, 'where': 'site_id = :sid',
     'fks': {'category_id': 'tutorial_categories'}},
)

ALLOWED_TABLES = {spec['name'] for spec in BACKUP_TABLES}
# 允许为空的外键：源栏目/文章被删除时不阻断导入
NULLABLE_FKS = {('columns', 'parent_id'), ('builder_pages', 'column_id'),
                ('products', 'column_id'), ('banners', 'image_id')}

RECYCLE_BACKUP_MARK = 'recycle'


class BackupError(Exception):
    """站点备份或导入失败。"""


# ============================================================
# 序列化
# ============================================================

def _encode_value(value):
    if isinstance(value, datetime):
        return {'__t': 'datetime', 'v': value.isoformat()}
    if isinstance(value, date):
        return {'__t': 'date', 'v': value.isoformat()}
    if isinstance(value, Decimal):
        return {'__t': 'decimal', 'v': str(value)}
    if isinstance(value, bytes):
        return {'__t': 'bytes', 'v': value.hex()}
    return value


def _decode_value(value):
    if isinstance(value, dict) and '__t' in value:
        kind = value.get('__t')
        raw = value.get('v')
        if kind == 'datetime':
            return datetime.fromisoformat(raw)
        if kind == 'date':
            return date.fromisoformat(raw)
        if kind == 'decimal':
            return Decimal(raw)
        if kind == 'bytes':
            return bytes.fromhex(raw)
    if isinstance(value, list):
        return [_decode_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _decode_value(v) for k, v in value.items()}
    return value


def _json_line(row):
    return json.dumps({k: _encode_value(v) for k, v in row.items()},
                      ensure_ascii=False) + '\n'


# ============================================================
# 路径与文件
# ============================================================

def _upload_root():
    return os.path.abspath(current_app.config['UPLOAD_FOLDER'])


def _site_upload_dir(site_id):
    return os.path.join(_upload_root(), f'site{site_id}')


def _backup_root():
    base = current_app.config.get('BACKUP_FOLDER') or os.path.join(
        current_app.instance_path, 'backups')
    return os.path.join(base, 'sites')


def _site_backup_dir(site_id):
    return os.path.join(_backup_root(), str(site_id))


def _safe_slug(slug):
    cleaned = re.sub(r'[^a-z0-9_-]+', '-', (slug or 'site').lower()).strip('-')
    return cleaned or 'site'


def _max_unzip_bytes():
    try:
        mb = int(Setting.get('site_backup_max_unzip_mb', '2048') or 2048)
    except (TypeError, ValueError):
        mb = 2048
    return max(1, mb) * 1024 * 1024


def _max_archive_bytes():
    limit = _max_unzip_bytes() / 2
    try:
        upload_mb = int(Setting.get('upload_single_max_size_mb', '0') or 0)
    except (TypeError, ValueError):
        upload_mb = 0
    limit = max(limit, upload_mb * 1024 * 1024)
    return int(min(limit, MAX_ARCHIVE_MB * 1024 * 1024))


def backup_path(site_id, filename):
    """校验文件名并返回绝对路径；非法路径抛 ValueError。"""
    if not filename or not FILENAME_RE.match(filename):
        raise ValueError('备份文件名不合法')
    if os.path.basename(filename) != filename:
        raise ValueError('备份文件名不合法')
    site_dir = os.path.abspath(_site_backup_dir(site_id))
    path = os.path.abspath(os.path.join(site_dir, filename))
    if os.path.commonpath([site_dir, path]) != site_dir:
        raise ValueError('备份路径越界')
    return path


INCOMING_RE = re.compile(r'^[0-9a-f]{32}\.zip$')


def incoming_dir():
    """导入暂存目录（位于备份根目录下的 _incoming）。"""
    path = os.path.join(_backup_root(), '_incoming')
    os.makedirs(path, exist_ok=True)
    return path


def save_incoming(file_storage):
    """把上传的 ZIP 暂存到 _incoming，返回文件名。"""
    import uuid
    filename = f'{uuid.uuid4().hex}.zip'
    path = os.path.join(incoming_dir(), filename)
    file_storage.save(path)
    return filename


def incoming_path(filename):
    if not INCOMING_RE.match(filename or ''):
        raise BackupError('导入文件标识不合法')
    path = os.path.abspath(os.path.join(incoming_dir(), filename))
    if os.path.commonpath([incoming_dir(), path]) != incoming_dir():
        raise BackupError('导入路径越界')
    return path


def discard_incoming(filename):
    try:
        path = incoming_path(filename)
    except BackupError:
        return
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


# ============================================================
# 导出
# ============================================================

def _table_exists(name):
    try:
        return inspect(db.engine).has_table(name)
    except SQLAlchemyError:
        return False


def _write_table(zf, spec, site_id):
    name = spec['name']
    if not _table_exists(name):
        return 0
    stmt = text(f'SELECT * FROM {name} WHERE {spec["where"]}').execution_options(
        yield_per=500)
    rows = db.session.execute(stmt, {'sid': site_id}).mappings()
    count = 0
    with zf.open(f'data/{name}.jsonl', 'w') as raw:
        wrapper = io.TextIOWrapper(raw, encoding='utf-8', newline='\n')
        try:
            for row in rows:
                wrapper.write(_json_line(dict(row)))
                count += 1
        finally:
            wrapper.flush()
            wrapper.detach()
    return count


def _write_uploads(zf, site_id):
    root = _site_upload_dir(site_id)
    if not os.path.isdir(root):
        return 0, 0
    files = 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # 跳过符号链接目录，避免打包到站点目录之外
        dirnames[:] = [d for d in dirnames
                       if not os.path.islink(os.path.join(dirpath, d))]
        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            if os.path.islink(abs_path) or not os.path.isfile(abs_path):
                continue
            rel = os.path.relpath(abs_path, root)
            arcname = f'uploads/site{site_id}/{rel}'.replace('\\', '/')
            zf.write(abs_path, arcname)
            files += 1
            total += os.path.getsize(abs_path)
    return files, total


def export_site(site_id, created_by=None, filename=None):
    """导出站点为 ZIP，返回 {filename, path, size, tables, uploads}。"""
    site = db.session.get(Site, site_id)
    if site is None:
        raise BackupError('站点不存在')

    out_dir = _site_backup_dir(site_id)
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    name = filename or f'site{site_id}-{_safe_slug(site.slug)}-{stamp}.zip'
    final_path = backup_path(site_id, name)
    tmp_path = final_path + '.part'

    manifest = {
        'format': FORMAT_NAME,
        'format_version': FORMAT_VERSION,
        'cms_version': Setting.CMS_VERSION,
        'created_at': datetime.now().isoformat(),
        'created_by': created_by,
        'site': {
            'id': site.id,
            'name': site.name,
            'slug': site.slug,
            'domain': site.domain,
            'subdomain': site.subdomain,
            'theme': site.theme,
            'seo_title': site.seo_title,
            'seo_keywords': site.seo_keywords,
            'seo_description': site.seo_description,
            'sort_order': site.sort_order,
        },
        'tables': {},
    }

    try:
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED,
                             allowZip64=True) as zf:
            for spec in BACKUP_TABLES:
                manifest['tables'][spec['name']] = _write_table(
                    zf, spec, site_id)
            files, total = _write_uploads(zf, site_id)
            manifest['uploads'] = files
            manifest['upload_bytes'] = total
            zf.writestr('manifest.json',
                        json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(tmp_path, final_path)
    except Exception as e:
        logger.warning('站点 %s 备份导出失败：%s', site_id, e)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        AuditLog.record(OP_OTHER, MODULE_BACKUP, target_id=site_id,
                        target_name=site.name,
                        detail={'action': 'site_export', 'error': str(e)},
                        site_id=site_id)
        raise BackupError(f'站点备份导出失败：{e}') from e

    size = os.path.getsize(final_path)
    AuditLog.record(OP_EXPORT, MODULE_BACKUP, target_id=site_id,
                    target_name=site.name,
                    detail={'action': 'site_export', 'filename': name,
                            'size': size, 'tables': manifest['tables']},
                    site_id=site_id)
    # v3.2.12：备份导出成功后发射 Webhook 事件（失败不影响导出结果）
    try:
        from .webhook import emit as webhook_emit
        webhook_emit('backup.completed', site_id, {
            'filename': name, 'size': size,
            'created_at': manifest['created_at'],
            'tables': manifest['tables'],
        })
    except Exception as e:
        logger.warning('Webhook 事件发射失败（backup.completed）：%s', e)
    return {'filename': name, 'path': final_path, 'size': size,
            'tables': manifest['tables'], 'uploads': manifest['uploads'],
            'manifest': manifest}

# ============================================================
# 导入
# ============================================================

def _read_manifest(zf):
    try:
        raw = zf.read('manifest.json')
    except KeyError:
        raise BackupError('备份包缺少 manifest.json')
    try:
        manifest = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as e:
        raise BackupError(f'manifest.json 解析失败：{e}')
    if manifest.get('format') != FORMAT_NAME:
        raise BackupError('备份格式不匹配')
    if int(manifest.get('format_version') or 0) != FORMAT_VERSION:
        raise BackupError('备份格式版本不兼容')
    tables = manifest.get('tables') or {}
    unknown = set(tables) - ALLOWED_TABLES
    if unknown:
        raise BackupError(f'备份包含未知数据表：{", ".join(sorted(unknown))}')
    return manifest


def _check_zip_safety(zf):
    limit = _max_unzip_bytes()
    total = 0
    for info in zf.infolist():
        name = info.filename
        if name.startswith('/') or '..' in name.split('/'):
            raise BackupError(f'备份包包含非法路径：{name}')
        mode = (info.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise BackupError(f'备份包包含符号链接：{name}')
        total += info.file_size
        if total > limit:
            raise BackupError('备份包解压后超过大小限制')
        if info.compress_size and info.file_size / max(info.compress_size, 1) > 200:
            raise BackupError('备份包压缩比异常')


def inspect_backup(zip_path):
    """读取备份摘要，供导入前确认；非法包抛 BackupError。"""
    if not os.path.isfile(zip_path):
        raise BackupError('备份文件不存在')
    if os.path.getsize(zip_path) > _max_archive_bytes():
        raise BackupError('备份文件超过大小限制')
    try:
        with zipfile.ZipFile(zip_path) as zf:
            _check_zip_safety(zf)
            manifest = _read_manifest(zf)
    except zipfile.BadZipFile:
        raise BackupError('不是有效的 ZIP 文件')
    return {
        'filename': os.path.basename(zip_path),
        'site': manifest.get('site') or {},
        'tables': manifest.get('tables') or {},
        'uploads': manifest.get('uploads') or 0,
        'upload_bytes': manifest.get('upload_bytes') or 0,
        'created_at': manifest.get('created_at'),
        'cms_version': manifest.get('cms_version'),
    }


def _existing_site_values():
    rows = db.session.query(
        Site.slug, Site.domain, Site.subdomain).all()
    slugs = {r[0] for r in rows if r[0]}
    domains = {r[1] for r in rows if r[1]}
    subdomains = {r[2] for r in rows if r[2]}
    return slugs, domains, subdomains


def _rename_domain(domain, n):
    if not domain:
        return None
    head, sep, tail = domain.partition('.')
    if not sep:
        return f'{head}-copy{n}'
    return f'{head}-copy{n}.{tail}'


def _create_site_from_manifest(meta):
    slugs, domains, subdomains = _existing_site_values()
    base_slug = (meta.get('slug') or 'site').lower()
    slug = base_slug
    n = 1
    while slug in slugs:
        slug = f'{base_slug}-copy{n}'
        n += 1

    domain = meta.get('domain') or None
    subdomain = meta.get('subdomain') or None
    if domain and domain in domains:
        # 唯一约束全局生效：冲突时改名而不是丢弃域名
        n = 1
        new_domain = _rename_domain(domain, n)
        while new_domain in domains:
            n += 1
            new_domain = _rename_domain(domain, n)
        domain = new_domain
    if subdomain and subdomain in subdomains:
        base = subdomain
        n = 1
        while f'{base}-copy{n}'[:63] in subdomains:
            n += 1
        subdomain = f'{base}-copy{n}'[:63]

    site = Site(
        name=meta.get('name') or slug,
        slug=slug,
        domain=domain,
        subdomain=subdomain,
        status='closed',
        theme=meta.get('theme'),
        is_default=False,
        seo_title=meta.get('seo_title'),
        seo_keywords=meta.get('seo_keywords'),
        seo_description=meta.get('seo_description'),
        sort_order=int(meta.get('sort_order') or 0),
    )
    db.session.add(site)
    db.session.commit()
    return site


def _rewrite_uploads(value, old_sid, new_sid):
    if not isinstance(value, str) or old_sid is None:
        return value
    return (value.replace(f'/uploads/site{old_sid}/', f'/uploads/site{new_sid}/')
            .replace(f'uploads/site{old_sid}/', f'uploads/site{new_sid}/'))


def _coerce_column_value(column, value):
    """SQLite 通过 text() 查询返回的时间值是字符串，导入前按反射类型还原。"""
    if value is None or not isinstance(value, str):
        return value
    if isinstance(column.type, DateTime):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(column.type, Date):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    return value


def _restore_table(zf, spec, site, old_sid, id_maps, warnings):
    name = spec['name']
    path = f'data/{name}.jsonl'
    if path not in zf.namelist():
        return 0

    metadata = MetaData()
    table = Table(name, metadata, autoload_with=db.engine)
    count = 0
    with zf.open(path) as raw:
        for line in io.TextIOWrapper(raw, encoding='utf-8'):
            if not line.strip():
                continue
            row = _decode_value(json.loads(line))
            old_id = row.pop('id', None)
            if name == 'banners':
                # 上传资产索引在导入后重建，先清空旧图片引用
                row['image_id'] = None
            for key in list(row):
                row[key] = _rewrite_uploads(row[key], old_sid, site.id)
            for key in list(row):
                column = table.c.get(key)
                if column is not None:
                    row[key] = _coerce_column_value(column, row[key])
            if spec['site']:
                row['site_id'] = site.id
            skip = False
            for fk, parent in spec['fks'].items():
                old_val = row.get(fk)
                if old_val is None:
                    continue
                new_val = id_maps.get(parent, {}).get(old_val)
                if new_val is None:
                    if (name, fk) in NULLABLE_FKS:
                        row[fk] = None
                        continue
                    warnings.append(
                        f'{name}.{fk}={old_val} 未找到映射，已跳过该行')
                    skip = True
                    break
                row[fk] = new_val
            if skip:
                continue
            try:
                result = db.session.execute(table.insert().values(**row))
                if old_id is not None:
                    id_maps.setdefault(name, {})[old_id] = \
                        result.inserted_primary_key[0]
            except SQLAlchemyError as e:
                warnings.append(f'{name} 插入失败：{e}')
                continue
            count += 1
            if count % 200 == 0:
                db.session.commit()
    db.session.commit()
    return count


def _restore_uploads(zf, old_sid, new_sid):
    """把 uploads/site{old}/ 内容解压到站点目录，返回文件数。"""
    root = _site_upload_dir(new_sid)
    os.makedirs(root, exist_ok=True)
    count = 0
    prefix = 'uploads/'
    expected = f'site{old_sid}'
    for info in zf.infolist():
        name = info.filename
        if not name.startswith(prefix) or name.endswith('/'):
            continue
        parts = name[len(prefix):].split('/')
        if len(parts) < 2 or parts[0] != expected:
            continue
        rel = '/'.join(parts[1:])
        target = os.path.abspath(os.path.join(root, rel))
        if os.path.commonpath([root, target]) != root:
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(info) as src, open(target, 'wb') as dst:
            while True:
                chunk = src.read(1024 * 256)
                if not chunk:
                    break
                dst.write(chunk)
        count += 1
    return count


def _rebuild_upload_index(site_id):
    """按站点物理文件重建 uploaded_files 索引。"""
    UploadedFile.query.filter_by(site_id=site_id).delete(
        synchronize_session=False)
    root = _site_upload_dir(site_id)
    if not os.path.isdir(root):
        db.session.commit()
        return 0
    count = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            if os.path.islink(abs_path) or not os.path.isfile(abs_path):
                continue
            rel = os.path.relpath(abs_path, _upload_root()).replace('\\', '/')
            stored_name = f'uploads/{rel}'
            size = os.path.getsize(abs_path)
            digest = hashlib.sha256()
            with open(abs_path, 'rb') as f:
                for chunk in iter(lambda: f.read(1024 * 256), b''):
                    digest.update(chunk)
            mime, _ = mimetypes.guess_type(filename)
            ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
            kind = 'image' if (mime or '').startswith('image/') else 'file'
            db.session.add(UploadedFile(
                site_id=site_id,
                original_name=filename,
                stored_name=stored_name,
                storage='local',
                url=f'/static/{stored_name}',
                file_size=size,
                compressed_size=size,
                mime_type=mime or '',
                ext=ext,
                content_hash=digest.hexdigest(),
                kind=kind,
                ref_count=1,
            ))
            count += 1
    db.session.commit()
    return count


def import_site_backup(zip_path, target_site_id=None, mode='new',
                       created_by=None):
    """导入站点备份，返回 {site_id, counts, warnings}。"""
    if mode not in ('new', 'overwrite', 'rename'):
        raise BackupError('导入模式不合法')
    summary = inspect_backup(zip_path)
    old_sid = (summary['site'] or {}).get('id')

    if mode == 'overwrite':
        site = db.session.get(Site, target_site_id) if target_site_id else None
        if site is None or site.is_deleted:
            raise BackupError('目标站点不存在')
        if site.id == DEFAULT_SITE_ID or site.is_default:
            raise BackupError('默认站点不允许覆盖导入')
        from .site_clone import delete_all_site_content
        # 覆盖前自动安全备份；失败则中止，避免不可恢复
        export_site(site.id, created_by=created_by)
        # 与后续恢复共用事务：恢复失败时回滚，目标站点不会被清空
        delete_all_site_content(site.id, commit=False)
    else:
        site = _create_site_from_manifest(summary['site'])

    id_maps = {}
    warnings = []
    counts = {}
    site_id = site.id
    site_name = site.name
    try:
        with zipfile.ZipFile(zip_path) as zf:
            _check_zip_safety(zf)
            for spec in BACKUP_TABLES:
                counts[spec['name']] = _restore_table(
                    zf, spec, site, old_sid, id_maps, warnings)
            _restore_uploads(zf, old_sid, site.id)
        counts['uploaded_files'] = _rebuild_upload_index(site.id)
    except Exception as e:
        db.session.rollback()
        if mode != 'overwrite':
            from .site_clone import cleanup_partial_clone
            try:
                cleanup_partial_clone(site_id)
            except Exception:
                logger.exception('导入失败后清理站点 %s 失败', site_id)
        AuditLog.record(OP_OTHER, MODULE_BACKUP, target_id=site_id,
                        target_name=site_name,
                        detail={'action': 'site_import', 'mode': mode,
                                'filename': os.path.basename(zip_path),
                                'error': str(e)},
                        site_id=site_id)
        raise BackupError(f'站点备份导入失败：{e}') from e

    AuditLog.record(OP_BACKUP_RESTORE, MODULE_BACKUP, target_id=site_id,
                    target_name=site_name,
                    detail={'action': 'site_import', 'mode': mode,
                            'filename': os.path.basename(zip_path),
                            'counts': counts, 'warnings': warnings[:20]},
                    site_id=site_id)
    return {'site_id': site_id, 'counts': counts, 'warnings': warnings}


# ============================================================
# 列表、删除与保留清理
# ============================================================

def list_site_backups(site_id):
    """列出站点备份文件，按创建时间倒序。"""
    site_dir = _site_backup_dir(site_id)
    if not os.path.isdir(site_dir):
        return []
    items = []
    for filename in os.listdir(site_dir):
        if not FILENAME_RE.match(filename):
            continue
        path = os.path.join(site_dir, filename)
        if not os.path.isfile(path):
            continue
        stat_info = os.stat(path)
        tables = None
        try:
            with zipfile.ZipFile(path) as zf:
                manifest = _read_manifest(zf)
                tables = len(manifest.get('tables') or {})
        except (zipfile.BadZipFile, BackupError, OSError) as e:
            logger.warning('读取备份 %s 摘要失败：%s', filename, e)
        items.append({
            'filename': filename,
            'size': stat_info.st_size,
            'created_at': datetime.fromtimestamp(stat_info.st_mtime),
            'tables': tables,
        })
    items.sort(key=lambda x: x['created_at'], reverse=True)
    return items


def delete_site_backup(site_id, filename, operator_id=None):
    """删除备份文件，写审计。"""
    path = backup_path(site_id, filename)
    if not os.path.isfile(path):
        raise BackupError('备份文件不存在')
    os.remove(path)
    site = db.session.get(Site, site_id)
    AuditLog.record(OP_DELETE, MODULE_BACKUP, target_id=site_id,
                    target_name=site.name if site else '',
                    detail={'action': 'site_backup_delete',
                            'filename': filename, 'operator_id': operator_id},
                    site_id=site_id)
    return True


def cleanup_expired_site_backups():
    """按 site_backup_keep_days 清理过期备份；0 表示不自动清理。"""
    try:
        keep_days = int(Setting.get('site_backup_keep_days', '30') or 0)
    except (TypeError, ValueError):
        keep_days = 30
    if keep_days <= 0:
        return 0
    cutoff = datetime.now() - timedelta(days=keep_days)
    root = _backup_root()
    if not os.path.isdir(root):
        return 0
    removed = 0
    for site_name in os.listdir(root):
        site_dir = os.path.join(root, site_name)
        if not os.path.isdir(site_dir):
            continue
        for filename in os.listdir(site_dir):
            path = os.path.join(site_dir, filename)
            if not os.path.isfile(path):
                continue
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(path))
            except OSError:
                continue
            if mtime < cutoff:
                try:
                    os.remove(path)
                    removed += 1
                except OSError as e:
                    logger.warning('删除过期备份 %s 失败：%s', path, e)
    return removed
