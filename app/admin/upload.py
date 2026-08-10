"""通用文件上传接口（供后台富文本编辑器、图片选择等使用）。"""
from flask import request, jsonify

from ..models.setting import Setting
from ..utils.uploads import save_upload_file
from . import admin_bp
from ..utils.helpers import admin_required


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
