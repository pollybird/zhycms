"""通用文件上传接口（供后台富文本编辑器、图片选择等使用）。
升级：权限（permission_required + upload:模块审计日志）。
v3.1.2 M2/M3（GitCode issue #2）：子目录白名单 + CKEditorFuncNum 反射 XSS 防护。
"""
import html
import re

from flask import request, jsonify, current_app

from ..models.setting import Setting
from ..utils.uploads import save_upload_file, _safe_sub_dir
from ..utils.helpers import admin_required, audit_log
from ..models.audit import OP_UPLOAD, MODULE_UPLOAD
from . import admin_bp


# v3.1.2 M3：CKEditorFuncNum 仅允许 1-6 位纯数字，杜绝反射型 XSS
_CKEDITOR_FUNC_NUM_RE = re.compile(r'^\d{1,6}$')


@admin_bp.route('/upload', methods=['POST'])
@admin_required
def upload_file():
    """通用上传接口，按 type 参数决定子目录。"""
    file_storage = request.files.get('file') or request.files.get('upload')
    if not file_storage or not file_storage.filename:
        return jsonify({'error': '未选择文件'}), 400

    # v3.1.2 M2：子目录白名单（前端入口处先归一化，save_upload_file 内再二次校验）
    sub_dir = _safe_sub_dir(request.form.get('type') or 'common')
    allowed_exts = Setting.get_allowed_exts()
    max_size = Setting.get_upload_max_size()

    # 富文本编辑器 CKEditor 的 CKEditorFuncNum
    # v3.1.2 M3：func_num 仅接受 1-6 位纯数字，非法直接 400；
    # file_url / err 经 html.escape(..., quote=True) 防反射型 XSS。
    func_num = (request.args.get('CKEditorFuncNum')
                or request.form.get('CKEditorFuncNum') or '').strip()
    if func_num and not _CKEDITOR_FUNC_NUM_RE.match(func_num):
        return jsonify({'error': '参数无效'}), 400

    rel_path, file_url, err = save_upload_file(
        file_storage, sub_dir=sub_dir,
        allowed_exts=allowed_exts, max_size=max_size
    )
    if err:
        if func_num:
            return (
                f'<script>window.parent.CKEDITOR.tools.callFunction('
                f'{func_num}, "", "{html.escape(err, quote=True)}");</script>'
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
            f'{func_num}, "{html.escape(file_url, quote=True)}", '
            f'"{html.escape("上传成功", quote=True)}");</script>'
        ), 200

    return jsonify({
        'url': file_url,
        'path': rel_path,
        'filename': file_storage.filename,
    })
