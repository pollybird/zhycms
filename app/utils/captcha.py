"""简单的图片验证码生成。"""
import io
import random
import string

from PIL import Image, ImageDraw, ImageFont


def generate_captcha(length=4, width=120, height=40):
    """生成验证码图片，返回 (验证码文本, PNG 二进制数据)。"""
    chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
    # 排除容易混淆的字符
    chars = chars.replace('0', 'D').replace('O', 'Q').replace('I', 'J').replace('1', 'L')

    image = Image.new('RGB', (width, height), (245, 246, 247))
    draw = ImageDraw.Draw(image)

    # 尝试加载系统字体
    font = None
    for path in [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/System/Library/Fonts/Monaco.ttf',
    ]:
        try:
            font = ImageFont.truetype(path, 22)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    for i, ch in enumerate(chars):
        x = 8 + i * (width - 16) // length
        y = random.randint(2, 8)
        color = (random.randint(20, 120), random.randint(20, 120), random.randint(80, 160))
        draw.text((x, y), ch, font=font, fill=color)

    # 干扰线
    for _ in range(4):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        draw.line(((x1, y1), (x2, y2)), fill=(random.randint(150, 200), random.randint(150, 200), random.randint(150, 200)), width=1)

    # 干扰点
    for _ in range(80):
        x, y = random.randint(0, width - 1), random.randint(0, height - 1)
        draw.point((x, y), fill=(random.randint(120, 200), random.randint(120, 200), random.randint(120, 200)))

    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return chars, buffer.getvalue()
