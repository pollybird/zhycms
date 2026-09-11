"""文件上传（模块6 升级 / v2.4 接入存储驱动层）：
- 后缀 + MIME 双重校验
- 单文件最大尺寸（后台配置 upload_single_max_size_mb）
- 图片自动压缩（Pillow）+ 生成缩略图
- 基于内容 SHA-256 自动去重（重复文件直接复用已有 URL，引用计数 +1）
- v2.4：文件发布走存储抽象层（app/utils/storage.py），支持本地磁盘与
  云端对象存储（阿里云 OSS / 腾讯云 COS / 七牛云，由 oss_storage 插件注册）；
  校验/压缩/缩略图仍在本地临时文件上完成，发布后云驱动自动清理本地副本。
"""
import os
import io
import hashlib
import uuid
from datetime import datetime

from flask import current_app, url_for

from ..extensions import db
from .storage import (
    LocalStorageDriver, get_driver, StorageError,
)


from ..constants import Upload as _U

IMAGE_EXTS = set(_U.IMAGE_EXTS)


def _detect_mime(file_stream, original_name=''):
    """MIME 类型二次校验：优先 python-magic，失败用 Pillow 对图片 sniffing + 内置 mimetypes。"""
    file_stream.seek(0)
    head = file_stream.read(4096)
    file_stream.seek(0)
    ext = original_name.rsplit('.', 1)[1].lower() if '.' in (original_name or '') else ''

    # 1. python-magic
    try:
        import magic
        mime = magic.from_buffer(head, mime=True) or ''
        return mime
    except Exception:
        pass
    # 2. 文件头硬匹配（常见恶意文件：php/asp/aspx/exe/dll/sh 等脚本 / elf）
    if head.startswith(b'<?php') or b'<script' in head[:1024].lower() or head.startswith(b'#!'):
        return 'text/x-script'
    if head.startswith(b'MZ'):
        return 'application/x-executable'
    if head.startswith(b'\x7fELF'):
        return 'application/x-executable'
    # 3. 图片：Pillow 验证
    if ext in IMAGE_EXTS:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(head))
            img.verify()
            # verify 之后文件指针失效，再开一次
            img2 = Image.open(io.BytesIO(head))
            return f'image/{img2.format.lower()}'
        except Exception:
            return 'application/octet-stream'
    # 4. PDF
    if head.startswith(b'%PDF-'):
        return 'application/pdf'
    # 5. ZIP/RAR
    if head[:2] == b'PK':
        return 'application/zip'
    if head.startswith(b'Rar!\x1a\x07'):
        return 'application/x-rar-compressed'
    # 默认
    return 'application/octet-stream'


def allowed_file(filename, allowed_exts=None):
    """检查文件后缀是否被允许（保留原接口，兼容）。"""
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    if allowed_exts is None:
        return True
    if isinstance(allowed_exts, str):
        allowed_exts = [e.strip().lower() for e in allowed_exts.split(',') if e.strip()]
    return ext in allowed_exts


def _mime_matches_ext(mime, ext):
    """粗粒度判定 MIME 是否与后缀匹配。"""
    ext = (ext or '').lower()
    mime = (mime or '').lower()
    if ext in ('jpg', 'jpeg'):
        return mime in ('image/jpeg', 'image/jpg', 'image/pjpeg')
    if ext == 'png':
        return mime == 'image/png'
    if ext == 'gif':
        return mime == 'image/gif'
    if ext == 'webp':
        return mime in ('image/webp', 'application/octet-stream')  # Pillow 有时认不出来 webp 新格式
    if ext == 'bmp':
        return mime == 'image/bmp'
    if ext == 'pdf':
        return mime == 'application/pdf'
    if ext in ('doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'zip'):
        return mime in ('application/zip', 'application/msword',
                        'application/vnd.ms-excel',
                        'application/vnd.openxmlformats-officedocument',
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        'application/octet-stream')
    if ext == 'rar':
        return 'rar' in mime or mime == 'application/octet-stream'
    if ext == 'txt':
        return mime.startswith('text/') or mime == 'application/octet-stream'
    return True  # 未知后缀宽松放行（后缀校验已限制）


def _sha256_of_stream(stream):
    stream.seek(0)
    h = hashlib.sha256()
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        h.update(chunk)
    stream.seek(0)
    return h.hexdigest()


def _compress_and_thumb(src_path, ext, quality=80, thumb_width=300):
    """对 src_path 的图片执行压缩 + 生成缩略图；返回 (compressed_size, thumb_url, thumb_rel_path) 或 (None, None, None)。"""
    try:
        from PIL import Image
    except ImportError:
        return None, None, None
    if ext.lower() not in IMAGE_EXTS:
        return None, None, None
    try:
        img = Image.open(src_path)
        # 压缩：用 Pillow save(quality=...) 覆盖原文件
        original_size = os.path.getsize(src_path)
        fmt = 'JPEG' if ext.lower() in ('jpg', 'jpeg') else (ext.upper() if ext.upper() in ('PNG', 'GIF', 'BMP', 'WEBP') else None)
        if fmt:
            if fmt == 'JPEG' and img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            save_kwargs = {}
            if fmt in ('JPEG', 'WEBP'):
                save_kwargs['quality'] = int(quality) if quality else 80
                save_kwargs['optimize'] = True
            elif fmt == 'PNG':
                save_kwargs['optimize'] = True
            img.save(src_path, format=fmt, **save_kwargs)
        compressed_size = os.path.getsize(src_path)

        # 生成缩略图（固定宽度，等比缩放），保存到 <src>.thumb.<ext>
        try:
            tw = max(int(thumb_width or 300), 40)
            ratio = tw / float(img.size[0]) if img.size[0] > 0 else 1
            th = int(img.size[1] * ratio)
            img2 = Image.open(src_path)
            img2.thumbnail((tw, th), Image.LANCZOS)
            thumb_dir = os.path.dirname(src_path)
            base = os.path.basename(src_path)
            thumb_name = f'thumb_{base}'
            thumb_path = os.path.join(thumb_dir, thumb_name)
            tfmt = fmt
            if tfmt == 'JPEG' and img2.mode not in ('RGB', 'L'):
                img2 = img2.convert('RGB')
            img2.save(thumb_path, format=tfmt or 'JPEG', quality=80, optimize=True)
            # 计算相对路径 / url
            upload_root = current_app.config['UPLOAD_FOLDER']
            rel = os.path.relpath(thumb_path, upload_root).replace(os.sep, '/')
            rel_full = f'uploads/{rel}' if not rel.startswith('uploads/') else rel
            thumb_rel = rel_full
            thumb_url = url_for('static', filename=rel_full)
        except Exception:
            thumb_rel, thumb_url = None, None
        return compressed_size, thumb_url, thumb_rel
    except Exception:
        return None, None, None


def _file_still_exists(dup):
    """去重复用前确认文件在其归属存储上仍存在（本地查磁盘，云端查对象）。

    云端校验异常或插件禁用时信任历史记录（CDN URL 仍可访问），不阻断复用。
    """
    from . import storage as _storage
    key = dup.stored_name or ''
    if not key:
        return False
    storage_name = getattr(dup, 'storage', None) or 'local'
    try:
        if storage_name == 'local':
            return LocalStorageDriver().exists(key)
        if _storage._driver_allowed(storage_name):
            try:
                return get_driver(storage_name).exists(key)
            except Exception:
                return True
        return True
    except Exception:
        return True


def save_upload_file(file_storage, sub_dir='', allowed_exts=None, max_size=None,
                     storage_scope='auto'):
    """保存上传文件（升级版）：返回 (相对路径/对象key, 文件URL, 错误信息)。

    storage_scope:
      - 'auto'（默认）：使用当前存储驱动（后台配置，可为云端 OSS）
      - 'local'：强制本地磁盘（备份恢复等必须留本地的场景使用）
    """
    from ..models.setting import Setting
    from ..models.upload import UploadedFile
    from ..models.user import User as _U  # noqa 仅保证模型可导入
    from flask_login import current_user

    # 1. 大小限制（优先级：参数 > 后台配置单文件MB > Setting.upload_max_size）
    try:
        cfg_mb = int(Setting.get('upload_single_max_size_mb', '0') or 0)
    except ValueError:
        cfg_mb = 0
    if max_size is None:
        if cfg_mb > 0:
            max_size = cfg_mb * 1024 * 1024
        else:
            max_size = Setting.get_upload_max_size()

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > max_size:
        return None, None, f'文件大小超过限制（最大 {max_size // 1024} KB）'

    # 2. 后缀校验（从原始文件名提取）
    original_name = file_storage.filename or ''
    if '.' not in original_name:
        return None, None, '文件名无效'
    ext = original_name.rsplit('.', 1)[1].lower()

    if allowed_exts is None:
        allowed_exts = Setting.get_allowed_exts()
    if not allowed_file(original_name, allowed_exts):
        return None, None, f'文件类型不允许，仅支持：{", ".join(allowed_exts)}'

    # 3. MIME 二次校验（模块6）
    if Setting.get('upload_enable_mime_check') == 'on':
        try:
            mime = _detect_mime(file_storage.stream, original_name)
        except Exception:
            mime = ''
        mime_l = (mime or '').lower()
        # 明显危险的 MIME 直接拒绝：脚本 / 可执行 / 服务端页面（含 text/x-php 等 libmagic 变体）
        danger_tokens = ('x-script', 'x-executable', 'x-sh', 'x-httpd-php', 'x-php',
                         'x-asp', 'x-msdos', 'javascript', 'html')
        if mime_l in ('text/x-script', 'application/x-executable',
                      'application/x-sh', 'text/html', 'application/x-httpd-php') \
                or any(t in mime_l for t in danger_tokens):
            return None, None, '检测到该文件为脚本或可执行文件，已拒绝上传'
        # 图片后缀要求内容确实是图片（拦截伪装成图片的任意文件）
        if ext in IMAGE_EXTS and not mime_l.startswith('image/'):
            return None, None, '文件内容与图片格式不符，已拒绝上传'
        if not _mime_matches_ext(mime, ext):
            # 非图片类的 MIME/后缀不一致暂不硬拒（docx/zip 等容器格式 libmagic 识别差异大），
            # 危险内容已被上面两条规则拦截
            pass
    else:
        mime = ''

    # 4. 内容去重（模块6）：SHA-256 查找已上传同内容文件
    content_hash = _sha256_of_stream(file_storage.stream) if Setting.get('upload_enable_dedup') == 'on' else ''
    if content_hash:
        dup = UploadedFile.find_by_hash(content_hash)
        if dup and _file_still_exists(dup):
            # 复用已有文件：引用计数+1，返回原 URL（云端文件 URL 不随驱动切换失效）
            try:
                dup.ref_count = (dup.ref_count or 0) + 1
                db.session.commit()
            except Exception:
                db.session.rollback()
            # stored_name 存的是相对 static 的路径/对象 key，如 uploads/... 直接用
            return dup.stored_name, dup.url, None

    # 5. 按日期分子目录，UUID 命名保存
    now = datetime.now()
    date_dir = now.strftime('%Y%m%d')
    save_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], sub_dir, date_dir)
    os.makedirs(save_dir, exist_ok=True)

    new_name = f'{uuid.uuid4().hex}.{ext}'
    save_path = os.path.join(save_dir, new_name)
    file_storage.save(save_path)

    # 6. 图片压缩 + 缩略图（模块6；本地临时文件上处理）
    compressed_size = 0
    thumb_rel = None
    width = height = None
    kind = 'image' if ext in IMAGE_EXTS else ('document' if ext in ('pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt') else 'file')
    if kind == 'image' and Setting.get('upload_image_auto_compress') == 'on':
        try:
            q = int(Setting.get('upload_image_compress_quality', '80'))
        except ValueError:
            q = 80
        try:
            tw = int(Setting.get('upload_image_thumb_width', '300'))
        except ValueError:
            tw = 300
        do_thumb = Setting.get('upload_image_thumb_enable') == 'on'
        res = _compress_and_thumb(save_path, ext, quality=q, thumb_width=tw if do_thumb else None)
        compressed_size = res[0] or os.path.getsize(save_path)
        thumb_rel = res[2]  # res[1] 是本地 URL，发布后按驱动重新生成
        try:
            from PIL import Image as _Image
            with _Image.open(save_path) as _img:
                width, height = _img.size
        except Exception:
            pass

    # 7. 发布到存储驱动（本地 no-op；云驱动上传，失败显式报错不静默回退）
    rel_path = f'uploads/{sub_dir}/{date_dir}/{new_name}'.replace('//', '/')
    thumb_abs = os.path.join(save_dir, f'thumb_{new_name}') if thumb_rel else None
    driver = LocalStorageDriver() if storage_scope == 'local' else get_driver()
    try:
        file_url = driver.save(save_path, rel_path)
        thumb_url = None
        if thumb_rel:
            try:
                thumb_url = driver.save(thumb_abs, thumb_rel)
            except StorageError as e:
                # 缩略图发布失败不阻断主文件
                current_app.logger.warning('缩略图发布失败（不影响主文件）： %s', e)
                thumb_rel, thumb_abs = None, None
    except StorageError as e:
        for p in (save_path, thumb_abs):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        return None, None, f'文件存储失败：{e}'

    # 云驱动发布成功后清理本地临时副本（本地驱动保留原位）
    if not driver.keeps_local_copy:
        for p in (save_path, thumb_abs):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

    # 8. 写入 UploadedFile 索引
    try:
        u = UploadedFile(
            original_name=original_name,
            stored_name=rel_path,
            storage=driver.name,
            url=file_url,
            file_size=size,
            compressed_size=compressed_size or size,
            mime_type=mime or '',
            ext=ext,
            content_hash=content_hash or None,
            kind=kind,
            width=width,
            height=height,
            thumb_url=thumb_url,
            thumb_path=thumb_rel,
            uploader_id=current_user.id if current_user and current_user.is_authenticated else None,
            ref_count=1,
        )
        db.session.add(u)
        db.session.commit()
    except Exception:
        db.session.rollback()  # 索引写入失败不影响上传本身返回

    return rel_path, file_url, None
