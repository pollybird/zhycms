"""Word（.docx）文档导入：转换为干净 HTML。

只保留标题、段落、表格、列表等结构，丢弃字体、颜色、字号等格式；
文档内嵌图片自动保存到上传目录，超过 100KB 的位图用 Pillow 压缩。
依赖 mammoth（docx→HTML）与 Pillow（图片压缩），均为纯 Python，跨平台。
"""
import io
import os
import re
import uuid
from datetime import datetime

import mammoth
from PIL import Image
from flask import current_app, url_for

# 内嵌图片超过该大小（字节）时进行压缩
IMAGE_COMPRESS_THRESHOLD = 100 * 1024
# 压缩时限制的最大宽度（像素），过宽的图缩放以进一步减小体积
IMAGE_MAX_WIDTH = 1600
# JPEG 压缩质量
JPEG_QUALITY = 85

# 只保留结构的样式映射：Word 段落/字符样式 → 语义化 HTML 标签。
# 不映射任何字体、颜色、字号，这些格式在转换中自然被丢弃。
STYLE_MAP = """
p[style-name='Title'] => h1:fresh
p[style-name='Subtitle'] => h2:fresh
p[style-name='Heading 1'] => h1:fresh
p[style-name='Heading 2'] => h2:fresh
p[style-name='Heading 3'] => h3:fresh
p[style-name='Heading 4'] => h4:fresh
p[style-name='Heading 5'] => h5:fresh
p[style-name='Heading 6'] => h6:fresh
p[style-name='标题 1'] => h1:fresh
p[style-name='标题 2'] => h2:fresh
p[style-name='标题 3'] => h3:fresh
p[style-name='标题 4'] => h4:fresh
p[style-name='标题 5'] => h5:fresh
p[style-name='标题 6'] => h6:fresh
b => strong
i => em
"""

# 转换后仅保留的标签（结构与基本文本语义），其余标签的属性一律剥离
_ALLOWED_TAGS = {
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'br', 'hr',
    'strong', 'em', 'u', 's', 'sub', 'sup',
    'ul', 'ol', 'li', 'blockquote',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'a', 'img',
}
# 各标签允许保留的属性（其余属性——尤其 style/class——全部剥离）
_ALLOWED_ATTRS = {
    'a': {'href', 'target'},
    'img': {'src', 'alt'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan'},
}


def _save_docx_image(data, content_type):
    """保存 docx 内嵌图片，返回可访问的 URL。超过阈值的位图会被压缩。"""
    # 从 content_type（如 'image/png'）推断后缀
    ext = 'png'
    if content_type and '/' in content_type:
        sub = content_type.split('/', 1)[1].lower()
        ext = {'jpeg': 'jpg', 'x-emf': 'emf', 'x-wmf': 'wmf'}.get(sub, sub)

    raw = data
    # 仅对超阈值的常见位图尝试压缩；矢量/特殊格式（wmf/emf/svg）不处理
    if len(raw) > IMAGE_COMPRESS_THRESHOLD and ext in ('jpg', 'jpeg', 'png', 'bmp', 'tiff', 'webp'):
        compressed, new_ext = _compress_image(raw)
        if compressed is not None and len(compressed) < len(raw):
            raw, ext = compressed, new_ext

    now = datetime.now()
    date_dir = now.strftime('%Y%m%d')
    save_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'article', date_dir)
    os.makedirs(save_dir, exist_ok=True)

    new_name = f'{uuid.uuid4().hex}.{ext}'
    with open(os.path.join(save_dir, new_name), 'wb') as f:
        f.write(raw)

    rel_path = f'uploads/article/{date_dir}/{new_name}'
    return url_for('static', filename=rel_path)


def _compress_image(raw):
    """用 Pillow 压缩位图，返回 (字节, 后缀)；失败返回 (None, None)。

    带透明通道的图保持 PNG 优化压缩；其余转 JPEG。过宽的图会等比缩放。
    """
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        return None, None

    # 等比缩放到最大宽度
    if img.width > IMAGE_MAX_WIDTH:
        ratio = IMAGE_MAX_WIDTH / float(img.width)
        img = img.resize((IMAGE_MAX_WIDTH, int(img.height * ratio)), Image.LANCZOS)

    has_alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)
    out = io.BytesIO()
    try:
        if has_alpha:
            img.convert('RGBA').save(out, format='PNG', optimize=True)
            return out.getvalue(), 'png'
        img.convert('RGB').save(out, format='JPEG', quality=JPEG_QUALITY, optimize=True)
        return out.getvalue(), 'jpg'
    except Exception:
        return None, None


def _clean_html(html):
    """剥离转换结果中残留的属性（style/class 等），仅保留白名单标签与属性。"""

    def _clean_tag(match):
        closing = match.group(1)  # '/' 或 ''
        tag = match.group(2).lower()
        attrs = match.group(3) or ''
        self_close = match.group(4) or ''

        if tag not in _ALLOWED_TAGS:
            return ''  # 剥离不在白名单的标签（保留其文本内容不受影响）

        if closing == '/':
            return f'</{tag}>'

        allowed = _ALLOWED_ATTRS.get(tag, set())
        kept = []
        if allowed:
            for name, val in re.findall(r'([a-zA-Z_:][-a-zA-Z0-9_:]*)\s*=\s*"([^"]*)"', attrs):
                if name.lower() in allowed:
                    kept.append(f'{name}="{val}"')
        attr_str = (' ' + ' '.join(kept)) if kept else ''
        return f'<{tag}{attr_str}{self_close}>'

    # 匹配标签：</tag> 或 <tag attrs> 或 <tag attrs/>
    return re.sub(r'<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^<>]*?)?)\s*(/?)\s*>',
                  _clean_tag, html)


def convert_docx_to_html(file_storage):
    """把上传的 .docx 转换为干净 HTML，返回 (html, messages)。

    保留标题/段落/表格/列表结构与基本文本语义（加粗/斜体等），丢弃字体等格式；
    内嵌图片自动保存并按需压缩，替换为 <img src>。
    """
    file_storage.stream.seek(0)

    def _convert_image(image):
        with image.open() as image_bytes:
            data = image_bytes.read()
        return {'src': _save_docx_image(data, image.content_type)}

    result = mammoth.convert_to_html(
        file_storage.stream,
        style_map=STYLE_MAP,
        convert_image=mammoth.images.img_element(_convert_image),
    )
    html = _clean_html(result.value)
    messages = [m.message for m in result.messages]
    return html, messages
