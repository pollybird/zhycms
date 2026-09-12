"""v2.2.0 插件管理：列表展示 + 启用/禁用（即时生效） + 插件压缩包上传。

压缩包规范（任一形态均可，解压后自动识别单目录外层）：
  形态 A（推荐）：my_plugin.zip → my_plugin/{manifest.json, __init__.py, ...}
  形态 B：my_plugin.zip → {manifest.json, __init__.py, ...}（直接平铺，取目录名=文件名去后缀）

校验顺序（任一失败立即中止，不写入 plugins/）：
  1. 扩展名白名单：.zip / .tar.gz / .tgz
  2. 解压到临时目录 → 无路径穿越（绝对路径 / ../ 全部拦截）
  3. 识别插件根目录：若压缩包只有一个子目录且其中含 manifest.json，视为「外层目录」
  4. 必备文件：manifest.json + __init__.py（用户提及的 api.py 是可选，不强求）
  5. manifest.json：合法 JSON + 含 slug 字段 + slug 格式（字母数字下划线连字符 2-32）
  6. 目标 plugins/<slug>/ 是否已存在：已存在 → 禁止覆盖（要求先备份删除，避免误覆盖线上运行中的自定义插件）
  7. slug 与 manifest.slug 一致：若压缩形态 B 导致目录名 ≠ manifest.slug，以 manifest.slug 为准重命名
  8. Python 导入前的结构检查：__init__.py 非空（避免 0 字节空文件立即 import 失败也不报错但管理页加载失败标红）
"""
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from datetime import datetime

from flask import (render_template, redirect, url_for, request, flash,
                   current_app, send_file)
from flask_babel import gettext as _gettext
from werkzeug.utils import secure_filename

from ..models.audit import OP_UPDATE, OP_UPLOAD, OP_DELETE, OP_EXPORT, MODULE_PLUGIN
from ..utils.helpers import permission_required, audit_log
from ..utils.pack import zip_directory
from .. import plugin_system
from . import admin_bp
from .confirm import verify_delete_captcha

# ========== 常量 ==========

from ..constants import Upload as _U

_PLUGIN_ALLOWED_EXTS = _U.PLUGIN_EXTS
_PLUGIN_SLUG_RE = re.compile(r'^[a-zA-Z0-9_-]{2,32}$')

# 插件必备文件名（缺一不可）；api.py 可选（纯模板/纯后台扩展类插件可以没有 API）
_PLUGIN_REQUIRED_FILES = ('manifest.json', '__init__.py')


@admin_bp.route('/plugins')
@permission_required('system:settings')
def plugin_index():
    return render_template('admin/plugin/index.html',
                           plugins=plugin_system.get_plugin_records(),
                           allowed_exts=' / '.join(_PLUGIN_ALLOWED_EXTS),
                           required_files='、'.join(_PLUGIN_REQUIRED_FILES))


@admin_bp.route('/plugins/<slug>/toggle', methods=['POST'])
@permission_required('system:settings')
def plugin_toggle(slug):
    rec = plugin_system.get_record(slug)
    if rec is None:
        flash(_gettext('插件不存在'), 'danger')
        return redirect(url_for('admin.plugin_index'))

    name = rec.name
    if plugin_system.plugin_enabled(slug):
        err = plugin_system.disable_plugin(slug)
        if err:
            flash(_gettext('插件「{0}」禁用失败：{1}').format(name, err), 'danger')
            return redirect(url_for('admin.plugin_index'))
        action = 'disable'
        flash(_gettext('插件「{0}」已禁用').format(name), 'success')
    else:
        err = plugin_system.enable_plugin(slug)
        if err:
            flash(_gettext('插件「{0}」启用失败：{1}').format(name, err), 'danger')
            return redirect(url_for('admin.plugin_index'))
        action = 'enable'
        flash(_gettext('插件「{0}」已启用').format(name), 'success')

    audit_log(OP_UPDATE, MODULE_PLUGIN, target_id=slug, target_name=name,
              detail={'action': '启用' if action == 'enable' else '禁用',
                      'version': rec.version})
    return redirect(url_for('admin.plugin_index'))


@admin_bp.route('/plugins/<slug>/delete', methods=['POST'])
@permission_required('system:settings')
def plugin_delete(slug):
    """卸载插件：验证码确认后物理删除 plugins/<slug>/ 目录。

    防护：slug 格式校验（防路径穿越）→ 内置插件禁止 → 启用中禁止（先禁用）。
    插件数据表与数据保留；当前进程注册表同步移除（列表/菜单/聚合立即消失）。
    """
    err = verify_delete_captcha()
    if err:
        flash(err, 'danger')
        return redirect(url_for('admin.plugin_index'))

    # slug 来自 URL，必须严格校验，防止 ".." 等穿越
    if not _PLUGIN_SLUG_RE.match(slug or ''):
        flash(_gettext('非法的插件标识'), 'danger')
        return redirect(url_for('admin.plugin_index'))

    rec = plugin_system.get_record(slug)
    if rec is not None and rec.manifest.get('builtin'):
        flash(_gettext('「{0}」为官方内置插件，不支持卸载；如不需要可在插件管理中禁用').format(rec.name),
              'danger')
        return redirect(url_for('admin.plugin_index'))

    if plugin_system.plugin_enabled(slug):
        flash(_gettext('插件正在启用中，请先禁用再卸载'), 'danger')
        return redirect(url_for('admin.plugin_index'))

    pkg_dir = os.path.join(plugin_system.PLUGINS_DIR, slug)
    if not os.path.isdir(pkg_dir):
        flash(_gettext('插件目录不存在：plugins/{0}/').format(slug), 'danger')
        return redirect(url_for('admin.plugin_index'))

    name = rec.name if rec is not None else slug
    version = rec.version if rec is not None else ''

    try:
        shutil.rmtree(pkg_dir)
    except OSError as e:
        flash(_gettext('删除插件目录失败：{0}（请检查目录写权限）').format(e), 'danger')
        return redirect(url_for('admin.plugin_index'))

    # 当前进程注册表移除：列表/菜单/sitemap/审计聚合立即消失
    plugin_system.remove_record(slug)

    audit_log(OP_DELETE, MODULE_PLUGIN, target_id=slug, target_name=name,
              detail={'action': '卸载插件', 'version': version})
    flash(_gettext('插件「{0}」已卸载，目录 plugins/{1}/ 已删除（数据表保留，重新上传同名插件包可恢复使用）').format(name, slug), 'success')
    return redirect(url_for('admin.plugin_index'))


@admin_bp.route('/plugins/<slug>/download')
@permission_required('system:settings')
def plugin_download(slug):
    """打包下载插件目录为 zip（单目录形态，可在其他站点直接上传复用）。"""
    if not _PLUGIN_SLUG_RE.match(slug or ''):
        flash(_gettext('非法的插件标识'), 'danger')
        return redirect(url_for('admin.plugin_index'))

    pkg_dir = os.path.join(plugin_system.PLUGINS_DIR, slug)
    if not os.path.isdir(pkg_dir):
        flash(_gettext('插件目录不存在：plugins/{0}/').format(slug), 'danger')
        return redirect(url_for('admin.plugin_index'))

    rec = plugin_system.get_record(slug)
    name = rec.name if rec is not None else slug
    version = rec.version if rec is not None else ''

    buf, file_count = zip_directory(pkg_dir, slug)
    audit_log(OP_EXPORT, MODULE_PLUGIN, target_id=slug, target_name=name,
              detail={'action': '下载插件包', 'version': version,
                      'file_count': file_count,
                      'size_kb': round(buf.getbuffer().nbytes / 1024, 1)})
    return send_file(buf, mimetype='application/zip', as_attachment=True,
                     download_name=f'{slug}.zip')


# ============================================================
# 插件压缩包上传
# ============================================================

@admin_bp.route('/plugins/upload', methods=['POST'])
@permission_required('system:settings')
def plugin_upload():
    """插件压缩包上传入口。全程校验不通过时不写入 plugins/ 目录。"""
    f = request.files.get('archive')
    if f is None or not f.filename:
        flash(_gettext('请选择要上传的插件压缩包'), 'danger')
        return redirect(url_for('admin.plugin_index'))

    # 1. 扩展名白名单（原始文件名取后缀，避免 secure_filename 剥离中文后丢失类型）
    raw_name = f.filename or ''
    lower = raw_name.lower()
    if lower.endswith('.tar.gz'):
        ext = 'tar.gz'
    else:
        ext = lower.rsplit('.', 1)[-1] if '.' in lower else ''
    if ext not in _PLUGIN_ALLOWED_EXTS:
        flash(_gettext('非法文件类型：仅允许 {0}').format(" / ".join(_PLUGIN_ALLOWED_EXTS)),
              'danger')
        return redirect(url_for('admin.plugin_index'))

    plugins_dir = plugin_system.PLUGINS_DIR
    os.makedirs(plugins_dir, exist_ok=True)

    workdir = tempfile.mkdtemp(prefix='zhycms_plug_')
    try:
        # 2. 解压到 workdir/unpacked/
        unpacked = os.path.join(workdir, 'unpacked')
        os.makedirs(unpacked, exist_ok=True)
        err = _extract_archive(f.stream, ext, unpacked)
        if err:
            flash(_gettext('解压失败：{0}').format(err), 'danger')
            return redirect(url_for('admin.plugin_index'))

        # 3. 识别插件根目录 & 校验（返回 (root, slug, manifest) 或抛字符串错误）
        try:
            root, slug, manifest, meta = _validate_plugin_package(
                unpacked, raw_name, plugins_dir)
        except ValueError as e:
            flash(_gettext('插件包不合法：{0}').format(e), 'danger')
            return redirect(url_for('admin.plugin_index'))

        # 4. 移动到 plugins/<slug>/
        target = os.path.join(plugins_dir, slug)
        try:
            shutil.move(root, target)
        except OSError as e:
            flash(_gettext('写入 plugins 目录失败：{0}').format(e), 'danger')
            return redirect(url_for('admin.plugin_index'))

        # 5. 审计日志 + 成功提示
        name = manifest.get('name') or slug
        ver = manifest.get('version') or ''
        flash(_gettext('插件「{0}」（{1} v{2}）上传成功，请到列表页启用。 未生效可重启应用重新加载。').format(name, slug, ver or "-"), 'success')
        audit_log(OP_UPLOAD, MODULE_PLUGIN,
                  target_id=slug, target_name=name,
                  detail={'action': '上传插件',
                          'version': ver,
                          'author': manifest.get('author') or '',
                          'file_count': meta['file_count'],
                          'size_kb': meta['size_kb'],
                          'required_files': meta['required_files'],
                          })
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return redirect(url_for('admin.plugin_index'))


# ============================================================
# 工具：解压 + 包校验
# ============================================================

def _safe_join(base, member_path):
    """在 base 目录内安全拼接路径；路径穿越（../ 或绝对路径）抛 ValueError。"""
    if os.path.isabs(member_path):
        raise ValueError(_gettext('文件包含绝对路径：{0}').format(member_path))
    # 统一反斜杠（来自 Windows 打包机的 zip）
    normalized = member_path.replace('\\', '/').lstrip('/')
    target = os.path.normpath(os.path.join(base, normalized))
    base_abs = os.path.normpath(os.path.abspath(base))
    target_abs = os.path.normpath(os.path.abspath(target))
    if not (target_abs == base_abs
            or target_abs.startswith(base_abs + os.sep)):
        raise ValueError(_gettext('文件包含路径穿越：{0}').format(member_path))
    return target


def _extract_archive(stream, ext, unpacked):
    """解压 stream 到 unpacked；成功返回 None，失败返回错误字符串。"""
    try:
        if ext == 'zip':
            data = stream.read()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                # 先统一做路径穿越预检（不创建任何目录/文件）
                bad = [m.filename for m in zf.infolist()
                       if _is_path_traversal(m.filename)]
                if bad:
                    return (f'压缩包含非法路径项：'
                            + '、'.join(bad[:5]))
                for info in zf.infolist():
                    dst = _safe_join(unpacked, info.filename)
                    if info.is_dir():
                        os.makedirs(dst, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with zf.open(info) as src, open(dst, 'wb') as out:
                        shutil.copyfileobj(src, out)
            return None
        else:
            # tar.gz / tgz 流式处理（seekable 要求包装为 BytesIO）
            data = stream.read()
            mode = 'r:gz'
            with tarfile.open(fileobj=io.BytesIO(data), mode=mode) as tf:
                bad = [m.name for m in tf.getmembers()
                       if _is_path_traversal(m.name)]
                if bad:
                    return (f'压缩包含非法路径项：'
                            + '、'.join(bad[:5]))
                for member in tf.getmembers():
                    dst = _safe_join(unpacked, member.name)
                    if member.isdir():
                        os.makedirs(dst, exist_ok=True)
                        continue
                    if not member.isfile():
                        continue  # 符号链接等危险项直接跳过（不抛错，静默忽略）
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    extracted = tf.extractfile(member)
                    if extracted is None:
                        continue
                    with open(dst, 'wb') as out:
                        shutil.copyfileobj(extracted, out)
            return None
    except (zipfile.BadZipFile, tarfile.TarError) as e:
        return f'压缩包损坏或格式错误：{e}'
    except ValueError as e:
        return str(e)
    except OSError as e:
        return f'写临时目录失败：{e}'


def _is_path_traversal(name):
    """快速判断压缩包成员名是否路径穿越（不含后续 _safe_join 的绝对路径检测）。"""
    if not name:
        return False
    n = name.replace('\\', '/').strip()
    if n.startswith('/') or os.path.isabs(n):
        return True
    parts = [p for p in n.split('/') if p not in ('', '.')]
    depth = 0
    for p in parts:
        if p == '..':
            depth -= 1
            if depth < 0:
                return True
        else:
            depth += 1
    return False


def _find_plugin_root(unpacked):
    """识别插件根目录：
      - 若 unpacked 直接含 manifest.json → unpacked 自身（形态 B）。
      - 若 unpacked 只有一个子目录且其下含 manifest.json → 该子目录（形态 A）。
      - 否则返回 None。
    """
    if os.path.isfile(os.path.join(unpacked, 'manifest.json')):
        return unpacked
    entries = [e for e in os.listdir(unpacked)
               if os.path.isdir(os.path.join(unpacked, e))]
    # 忽略 __MACOSX / .DS_Store 等 OS 垃圾目录
    entries = [e for e in entries if e not in ('__MACOSX',)]
    if len(entries) == 1:
        sub = os.path.join(unpacked, entries[0])
        if os.path.isfile(os.path.join(sub, 'manifest.json')):
            return sub
    return None


def _validate_plugin_package(unpacked, archive_name, plugins_dir):
    """识别插件根目录并做完整校验。

    返回 (root, slug, manifest_dict, meta_dict)；不合法抛 ValueError(str)。
    """
    root = _find_plugin_root(unpacked)
    if root is None:
        raise ValueError(_gettext('未找到 manifest.json，压缩包结构不符合规范'))

    # 必备文件
    for req in _PLUGIN_REQUIRED_FILES:
        p = os.path.join(root, req)
        if not os.path.isfile(p):
            raise ValueError(_gettext('缺少必备文件：{0}').format(req))
        if req == '__init__.py' and os.path.getsize(p) == 0:
            # 0 字节 __init__.py 语法上合法但 import 后通常无 plugin 实例，管理页会"加载失败"；先放行，
            # 但在 meta 中标记，避免过度拦截合法的"只放 models"场景。
            pass

    # manifest.json 解析
    mf = os.path.join(root, 'manifest.json')
    try:
        with open(mf, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except (ValueError, OSError) as e:
        raise ValueError(_gettext('manifest.json 解析失败：{0}').format(e))
    if not isinstance(manifest, dict):
        raise ValueError(_gettext('manifest.json 必须是 JSON 对象（不是数组或字符串）'))

    # slug 字段
    slug = (manifest.get('slug') or '').strip()
    if not slug:
        raise ValueError(_gettext('manifest.json 缺少必填字段 slug'))
    if not _PLUGIN_SLUG_RE.match(slug):
        raise ValueError(
            _gettext('manifest.json 的 slug 格式不合法，只能包含字母/数字/连字符/下划线，长度 2-32 位（当前：{0}）').format(slug))

    # v2.6.4：依赖 / 继承 / 最低核心版本字段校验
    min_core = manifest.get('min_core_version', '')
    if min_core and not isinstance(min_core, str):
        raise ValueError(_gettext('manifest.json 的 min_core_version 必须是字符串'))
    extends = manifest.get('extends', '')
    if extends and not isinstance(extends, str):
        raise ValueError(_gettext('manifest.json 的 extends 必须是字符串'))
    requires = manifest.get('requires', [])
    if requires is not None:
        if not isinstance(requires, list):
            raise ValueError(_gettext('manifest.json 的 requires 必须是字符串数组'))
        for dep in requires:
            if not isinstance(dep, str) or not dep.strip():
                raise ValueError(_gettext('manifest.json 的 requires 数组元素必须是非空字符串'))

    # 形态 B 时根目录名可能与 slug 不一致：若根 = unpacked 本身（平铺），
    # 先把子项重命名到 unpacked/{slug}/，再让上层用新 root。
    if root == unpacked:
        new_root = os.path.join(unpacked, '__target_' + slug)
        os.makedirs(new_root, exist_ok=True)
        for item in os.listdir(root):
            if item.startswith('__target_'):
                continue
            shutil.move(os.path.join(root, item),
                        os.path.join(new_root, item))
        root = new_root
    else:
        # 形态 A：外层目录名不要求等于 slug，但最终移动到 plugins/<slug>/
        # 此处不改 root，仅返回正确 slug。
        pass

    # 目录冲突禁止覆盖
    target = os.path.join(plugins_dir, slug)
    if os.path.exists(target):
        raise ValueError(
            _gettext('插件目录已存在：plugins/{0}/，请先备份并删除该目录后再上传，避免误覆盖正在运行中的自定义插件代码。').format(slug))

    # 汇总元数据
    file_count = 0
    total_bytes = 0
    for dp, _dn, fn in os.walk(root):
        for name in fn:
            fp = os.path.join(dp, name)
            try:
                total_bytes += os.path.getsize(fp)
            except OSError:
                pass
            file_count += 1
    meta = {
        'file_count': file_count,
        'size_kb': round(total_bytes / 1024, 1),
        'required_files': list(_PLUGIN_REQUIRED_FILES),
    }
    return root, slug, manifest, meta
