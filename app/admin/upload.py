"""通用文件上传接口（供后台富文本编辑器、图片选择等使用）。
升级：权限（permission_required + upload:模块审计日志）。
"""
from flask import request, jsonify, current_app

from ..models.setting import Setting
from ..utils.uploads import save_upload_file
from ..utils.helpers import admin_required, audit_log
from ..models.audit import OP_UPLOAD, MODULE_UPLOAD
from . import admin_bp


@admin_bp.route('/upload', methods=['POST'])
@admin_required
def upload_file():
    """通用上传接口，按 type 参数决定子目录。"""
    file_storage = request.files.get('file') or request.files.get('upload')
    if not file_storage or not file_storage.filename:
        return jsonify({'error': '未选择文件'}), 400

    sub_dir = (request.form.get('type') or 'common').strip()
    allowed_exts = Setting.get_allowed_exts()
    max_size = Setting.get_upload_max_size()

    # 富文本编辑器 CKEditor 的 CKEditorFuncNum
    func_num = request.args.get('CKEditorFuncNum') or request.form.get('CKEditorFuncNum')

    rel_path, file_url, err = save_upload_file(
        file_storage, sub_dir=sub_dir,
        allowed_exts=allowed_exts, max_size=max_size
    )
    if err:
        if func_num:
            return (
                f'<script>window.parent.CKEDITOR.tools.callFunction('
                f'"{func_num}", "", "{err}");</script>'
            ), 200
        return jsonify({'error': err}), 400

    # 上传成功审计日志（忽略失败，不影响上传）
    try:
        audit_log(OP_UPLOAD, MODULE_UPLOAD, None, file_storage.filename,
                  {'sub_dir': sub_dir, 'url': file_url, 'path': rel_path})
    except Exception:
        current_app.logger.exception('upload audit failed')

    if func_num:
        return (
            f'<script>window.parent.CKEDITOR.tools.callFunction('
            f'"{func_num}", "{file_url}", "上传成功");</script>'
        ), 200

    return jsonify({
        'url': file_url,
        'path': rel_path,
        'filename': file_storage.filename,
    })
