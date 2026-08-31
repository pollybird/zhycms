"""v2.2.0 主题管理：列表 + 上传压缩包 + 启用（即时生效，无需重启）。

与插件上传共用 8 步校验框架，校验项略有差异：
  - 必备文件：manifest.json 必需 + THEME_REQUIRED_FILES 中 7 个基础模板（index/list/article/page/base/404/500）
  - 若主题目录已存在但为内置主题（manifest.builtin=true），禁止覆盖；自定义主题覆盖同样要求先删除
"""
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import zipfile

from flask import (render_template, redirect, url_for, request, flash,
                   send_file)

from ..extensions import db
from ..models.audit import (OP_UPDATE, OP_UPLOAD, OP_DELETE, OP_EXPORT,
                            MODULE_SETTING)
from ..models.setting import Setting
from ..utils.helpers import permission_required, audit_log
from ..utils.pack import zip_directory
from ..utils.themes import (
    THEMES_DIR,
    THEME_ALLOWED_EXTS,
    THEME_REQUIRED_FILES,
    THEME_SLUG_RE,
    get_active_theme,
    list_theme_records,
)
from . import admin_bp
from .confirm import verify_delete_captcha

# ------- 校验工具（与 plugins.py 同构，校验规则不同） -------

def _safe_join(base, member_path):
    if os.path.isabs(member_path):
        raise ValueError(f'文件包含绝对路径：{member_path}')
    normalized = member_path.replace('\\', '/').lstrip('/')
    target = os.path.normpath(os.path.join(base, normalized))
    base_abs = os.path.normpath(os.path.abspath(base))
    target_abs = os.path.normpath(os.path.abspath(target))
    if not (target_abs == base_abs
            or target_abs.startswith(base_abs + os.sep)):
        raise ValueError(f'文件包含路径穿越：{member_path}')
    return target


def _is_path_traversal(name):
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


def _extract_archive(stream, ext, unpacked):
    try:
        if ext == 'zip':
            data = stream.read()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                bad = [m.filename for m in zf.infolist()
                       if _is_path_traversal(m.filename)]
                if bad:
                    return '压缩包含非法路径项：' + '、'.join(bad[:5])
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
            data = stream.read()
            with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tf:
                bad = [m.name for m in tf.getmembers()
                       if _is_path_traversal(m.name)]
                if bad:
                    return '压缩包含非法路径项：' + '、'.join(bad[:5])
                for member in tf.getmembers():
                    dst = _safe_join(unpacked, member.name)
                    if member.isdir():
                        os.makedirs(dst, exist_ok=True)
                        continue
                    if not member.isfile():
                        continue
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


def _find_root(unpacked):
    if os.path.isfile(os.path.join(unpacked, 'manifest.json')):
        return unpacked
    entries = [e for e in os.listdir(unpacked)
               if os.path.isdir(os.path.join(unpacked, e))
               and e not in ('__MACOSX',)]
    if len(entries) == 1:
        sub = os.path.join(unpacked, entries[0])
        if os.path.isfile(os.path.join(sub, 'manifest.json')):
            return sub
    return None


def _validate_theme_package(unpacked, themes_dir):
    """返回 (root, slug, manifest, meta)。不合法抛 ValueError(str)。"""
    root = _find_root(unpacked)
    if root is None:
        raise ValueError('未找到 manifest.json，主题包结构不符合规范')

    # 1) manifest
    mf = os.path.join(root, 'manifest.json')
    try:
        with open(mf, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except (ValueError, OSError) as e:
        raise ValueError(f'manifest.json 解析失败：{e}')
    if not isinstance(manifest, dict):
        raise ValueError('manifest.json 必须是 JSON 对象')

    slug = (manifest.get('slug') or '').strip()
    if not slug:
        raise ValueError('manifest.json 缺少必填字段 slug')
    if not THEME_SLUG_RE.match(slug):
        raise ValueError(
            f'manifest.json 的 slug 格式不合法，只能包含字母/数字/连字符/下划线，'
            f'长度 2-32 位（当前：{slug}）')

    # 2) 必备模板：THEME_REQUIRED_FILES ∪ manifest.template_required
    extra = manifest.get('template_required') or []
    if isinstance(extra, str):
        extra = [x.strip() for x in extra.split(',') if x.strip()]
    required = list(THEME_REQUIRED_FILES)
    for x in extra:
        if isinstance(x, str) and x and x not in required:
            required.append(x)
    missing = [f for f in required if not os.path.isfile(os.path.join(root, f))]
    if missing:
        raise ValueError('缺少必备模板文件：' + '、'.join(missing)
                         + '（主题需包含 index/list/article/page/base/404/500 等基础模板）')

    # 3) 形态 B（平铺）→ 包一层
    if root == unpacked:
        new_root = os.path.join(unpacked, '__target_' + slug)
        os.makedirs(new_root, exist_ok=True)
        for item in os.listdir(root):
            if item.startswith('__target_'):
                continue
            shutil.move(os.path.join(root, item),
                        os.path.join(new_root, item))
        root = new_root

    # 4) 目录冲突禁止覆盖；内置主题一律禁止覆盖
    target = os.path.join(themes_dir, slug)
    if os.path.isdir(target):
        try:
            with open(os.path.join(target, 'manifest.json'), 'r',
                      encoding='utf-8') as f:
                existing_mf = json.load(f)
        except (ValueError, OSError):
            existing_mf = {}
        builtin = bool(existing_mf.get('builtin')) if isinstance(existing_mf, dict) else False
        if builtin:
            raise ValueError(
                f'目标目录 themes/{slug}/ 为<b>官方内置主题</b>，禁止覆盖；'
                f'如想自定义请以其它 slug 命名后上传。')
        raise ValueError(
            f'主题目录已存在：themes/{slug}/，请先备份并删除该目录后再上传，'
            f'避免误覆盖正在使用的自定义主题。')

    # 5) 汇总元数据
    file_count = 0
    total_bytes = 0
    tpl_count = 0
    for dp, _dn, fn in os.walk(root):
        for name in fn:
            fp = os.path.join(dp, name)
            try:
                total_bytes += os.path.getsize(fp)
            except OSError:
                pass
            file_count += 1
            if name.endswith('.html'):
                tpl_count += 1
    meta = {
        'file_count': file_count,
        'size_kb': round(total_bytes / 1024, 1),
        'template_count': tpl_count,
        'required_files': required,
    }
    return root, slug, manifest, meta


# ------- 视图 -------

@admin_bp.route('/themes')
@permission_required('system:settings')
def theme_index():
    records = list_theme_records()
    active = get_active_theme()
    # 缺模板的主题仍可列出但会标红，启用按钮变灰
    return render_template(
        'admin/theme/index.html',
        themes=records,
        active=active,
        allowed_exts=' / '.join(THEME_ALLOWED_EXTS),
        required_files='、'.join(THEME_REQUIRED_FILES + ('manifest.json',)),
    )


@admin_bp.route('/themes/<slug>/activate', methods=['POST'])
@permission_required('system:settings')
def theme_activate(slug):
    """启用主题（Setting.site_theme = slug）→ 即时生效。

    启用前校验：目录必须存在且必备模板齐全；否则拒绝。
    """
    target_dir = os.path.join(THEMES_DIR, slug)
    if not os.path.isdir(target_dir):
        flash(f'主题目录不存在：themes/{slug}/', 'danger')
        return redirect(url_for('admin.theme_index'))

    # 读取 manifest（若有）+ 检查必备模板
    mf_path = os.path.join(target_dir, 'manifest.json')
    mf = {}
    if os.path.isfile(mf_path):
        try:
            with open(mf_path, 'r', encoding='utf-8') as f:
                mf = json.load(f)
        except (ValueError, OSError):
            mf = {}
    if not isinstance(mf, dict):
        mf = {}
    extra = mf.get('template_required') or []
    if isinstance(extra, str):
        extra = [x.strip() for x in extra.split(',') if x.strip()]
    required = list(THEME_REQUIRED_FILES)
    for x in extra:
        if isinstance(x, str) and x and x not in required:
            required.append(x)
    missing = [f for f in required
               if not os.path.isfile(os.path.join(target_dir, f))]
    if missing:
        flash(f'主题 {slug} 缺少必备模板：{"、".join(missing)}，无法启用',
              'danger')
        return redirect(url_for('admin.theme_index'))

    old_theme = Setting.get('site_theme') or 'default'
    if old_theme == slug:
        flash(f'「{mf.get("name") or slug}」已是当前启用主题', 'info')
        return redirect(url_for('admin.theme_index'))

    Setting.set('site_theme', slug)
    db.session.commit()

    name = (mf.get('name') or '').strip() or slug
    audit_log(OP_UPDATE, MODULE_SETTING, target_id='site_theme',
              target_name=name,
              detail={'site_theme': [old_theme, slug],
                      'version': (mf.get('version') or '').strip(),
                      'author': (mf.get('author') or '').strip(),
                      })
    flash(f'主题「{name}」启用成功，前台立即生效', 'success')
    return redirect(url_for('admin.theme_index'))


@admin_bp.route('/themes/<slug>/delete', methods=['POST'])
@permission_required('system:settings')
def theme_delete(slug):
    """删除主题：验证码确认后物理删除 themes/<slug>/ 目录。

    防护：slug 格式校验（防路径穿越）→ 内置主题禁止 → 当前启用中禁止（先切换）。
    删除后 get_active_theme() 若引用该主题会自动兜底回退 default，前台不空白。
    """
    err = verify_delete_captcha()
    if err:
        flash(err, 'danger')
        return redirect(url_for('admin.theme_index'))

    # slug 来自 URL，严格校验防路径穿越
    if not THEME_SLUG_RE.match(slug or ''):
        flash('非法的主题标识', 'danger')
        return redirect(url_for('admin.theme_index'))

    target_dir = os.path.join(THEMES_DIR, slug)
    if not os.path.isdir(target_dir):
        flash(f'主题目录不存在：themes/{slug}/', 'danger')
        return redirect(url_for('admin.theme_index'))

    # manifest（可能缺失，缺失时按非内置处理）
    mf_path = os.path.join(target_dir, 'manifest.json')
    mf = {}
    if os.path.isfile(mf_path):
        try:
            with open(mf_path, 'r', encoding='utf-8') as f:
                mf = json.load(f)
        except (ValueError, OSError):
            mf = {}
    if not isinstance(mf, dict):
        mf = {}

    if mf.get('builtin'):
        name = (mf.get('name') or '').strip() or slug
        flash(f'「{name}」为官方内置主题，不支持删除（删除会导致系统模板缺失）',
              'danger')
        return redirect(url_for('admin.theme_index'))

    # 当前启用中的主题禁止删除（含目录名与 manifest.slug 双重判断）
    active = get_active_theme()
    if active == slug or (mf.get('slug') or '').strip() == active:
        flash('该主题正在启用中，请先切换到其他主题再删除', 'danger')
        return redirect(url_for('admin.theme_index'))

    name = (mf.get('name') or '').strip() or slug
    version = (mf.get('version') or '').strip()

    try:
        shutil.rmtree(target_dir)
    except OSError as e:
        flash(f'删除主题目录失败：{e}（请检查目录写权限）', 'danger')
        return redirect(url_for('admin.theme_index'))

    audit_log(OP_DELETE, MODULE_SETTING, target_id=slug, target_name=name,
              detail={'action': '删除主题', 'version': version})
    flash(f'主题「{name}」已删除，目录 themes/{slug}/ 已移除', 'success')
    return redirect(url_for('admin.theme_index'))


@admin_bp.route('/themes/<slug>/download')
@permission_required('system:settings')
def theme_download(slug):
    """打包下载主题目录为 zip（单目录形态，可在其他站点直接上传复用）。"""
    if not THEME_SLUG_RE.match(slug or ''):
        flash('非法的主题标识', 'danger')
        return redirect(url_for('admin.theme_index'))

    target_dir = os.path.join(THEMES_DIR, slug)
    if not os.path.isdir(target_dir):
        flash(f'主题目录不存在：themes/{slug}/', 'danger')
        return redirect(url_for('admin.theme_index'))

    # manifest 可能有缺失（缺失时按目录名处理）
    mf_path = os.path.join(target_dir, 'manifest.json')
    mf = {}
    if os.path.isfile(mf_path):
        try:
            with open(mf_path, 'r', encoding='utf-8') as f:
                mf = json.load(f)
        except (ValueError, OSError):
            mf = {}
    if not isinstance(mf, dict):
        mf = {}

    name = (mf.get('name') or '').strip() or slug
    version = (mf.get('version') or '').strip()

    buf, file_count = zip_directory(target_dir, slug)
    audit_log(OP_EXPORT, MODULE_SETTING, target_id=slug, target_name=name,
              detail={'action': '下载主题包', 'version': version,
                      'file_count': file_count,
                      'size_kb': round(buf.getbuffer().nbytes / 1024, 1)})
    return send_file(buf, mimetype='application/zip', as_attachment=True,
                     download_name=f'{slug}.zip')


@admin_bp.route('/themes/upload', methods=['POST'])
@permission_required('system:settings')
def theme_upload():
    f = request.files.get('archive')
    if f is None or not f.filename:
        flash('请选择主题压缩包', 'danger')
        return redirect(url_for('admin.theme_index'))

    raw_name = f.filename or ''
    lower = raw_name.lower()
    if lower.endswith('.tar.gz'):
        ext = 'tar.gz'
    else:
        ext = lower.rsplit('.', 1)[-1] if '.' in lower else ''
    if ext not in THEME_ALLOWED_EXTS:
        flash(f'非法文件类型：仅允许 {" / ".join(THEME_ALLOWED_EXTS)}',
              'danger')
        return redirect(url_for('admin.theme_index'))

    os.makedirs(THEMES_DIR, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix='zhycms_theme_')
    try:
        unpacked = os.path.join(workdir, 'unpacked')
        os.makedirs(unpacked, exist_ok=True)
        err = _extract_archive(f.stream, ext, unpacked)
        if err:
            flash(f'解压失败：{err}', 'danger')
            return redirect(url_for('admin.theme_index'))
        try:
            root, slug, manifest, meta = _validate_theme_package(
                unpacked, THEMES_DIR)
        except ValueError as e:
            flash(f'主题包不合法：{e}', 'danger')
            return redirect(url_for('admin.theme_index'))
        target = os.path.join(THEMES_DIR, slug)
        try:
            shutil.move(root, target)
        except OSError as e:
            flash(f'写入 themes 目录失败：{e}', 'danger')
            return redirect(url_for('admin.theme_index'))

        name = (manifest.get('name') or '').strip() or slug
        ver = (manifest.get('version') or '').strip()
        flash(f'主题「{name}」（{slug} v{ver or "-"}）上传成功，'
              f'可在下方列表中点击「启用」应用到前台；未生效可刷新页面或重启。',
              'success')
        audit_log(OP_UPLOAD, MODULE_SETTING,
                  target_id=slug, target_name=name,
                  detail={'action': '上传主题',
                          'version': ver,
                          'author': (manifest.get('author') or '').strip(),
                          'file_count': meta['file_count'],
                          'size_kb': meta['size_kb'],
                          'template_count': meta['template_count'],
                          })
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return redirect(url_for('admin.theme_index'))
