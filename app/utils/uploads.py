import os
import uuid
from datetime import datetime

from flask import current_app, url_for
from werkzeug.utils import secure_filename


def allowed_file(filename, allowed_exts=None):
    """检查文件后缀是否被允许。"""
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    if allowed_exts is None:
        return True
    if isinstance(allowed_exts, str):
        allowed_exts = [e.strip().lower() for e in allowed_exts.split(',') if e.strip()]
    return ext in allowed_exts


def save_upload_file(file_storage, sub_dir='', allowed_exts=None, max_size=None):
    """保存上传文件，返回 (相对路径, 文件URL, 错误信息)。

    参数：
        file_storage: werkzeug FileStorage
        sub_dir: 上传子目录，如 'column' / 'fragment' / 'form'
        allowed_exts: 允许后缀列表或逗号字符串；None 则使用全局配置
        max_size: 文件最大字节数；None 则使用全局配置
    """
    from ..models.setting import Setting

    if allowed_exts is None:
        allowed_exts = Setting.get_allowed_exts()
    if max_size is None:
        max_size = Setting.get_upload_max_size()

    # 检查文件大小
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > max_size:
        return None, None, f'文件大小超过限制（最大 {max_size // 1024} KB）'

    filename = secure_filename(file_storage.filename or '')
    if not filename:
        return None, None, '文件名无效'

    if not allowed_file(filename, allowed_exts):
        return None, None, f'文件类型不允许，仅支持：{", ".join(allowed_exts)}'

    # 按日期分子目录
    now = datetime.now()
    date_dir = now.strftime('%Y%m%d')
    save_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], sub_dir, date_dir)
    os.makedirs(save_dir, exist_ok=True)

    # 生成唯一文件名
    ext = filename.rsplit('.', 1)[1].lower()
    new_name = f'{uuid.uuid4().hex}.{ext}'
    save_path = os.path.join(save_dir, new_name)
    file_storage.save(save_path)

    # 相对路径用于 url_for('static', filename=...)
    rel_path = f'uploads/{sub_dir}/{date_dir}/{new_name}'
    return rel_path, url_for('static', filename=rel_path), None
