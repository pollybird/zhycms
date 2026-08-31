"""目录打包下载工具（v2.2.0）：插件/主题 zip 导出共用。

打包后 zip 内部为单目录形态（<arc_root>/manifest.json ...），
与上传校验的「形态 A」一致，下载后可直接在其他站点重新上传复用。
自动跳过 __pycache__ / .pyc / .git 等非分发文件与符号链接。
"""
import io
import os
import zipfile

# 打包时跳过的目录与文件后缀（开发缓存类，不属于分发包）
SKIP_DIRS = {'__pycache__', '.git', '.idea', '.vscode', '__MACOSX'}
SKIP_EXTS = ('.pyc', '.pyo')


def zip_directory(src_dir, arc_root):
    """把 src_dir 打包为内存 zip，内部根目录名为 arc_root。

    返回 (BytesIO, file_count)；供 send_file 直接输出。
    """
    buf = io.BytesIO()
    file_count = 0
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for dp, dns, fns in os.walk(src_dir):
            dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
            for fn in sorted(fns):
                if fn.lower().endswith(SKIP_EXTS):
                    continue
                full = os.path.join(dp, fn)
                if not os.path.isfile(full):  # 符号链接/特殊文件跳过
                    continue
                rel = os.path.relpath(full, src_dir).replace(os.sep, '/')
                zf.write(full, f'{arc_root}/{rel}')
                file_count += 1
    buf.seek(0)
    return buf, file_count
