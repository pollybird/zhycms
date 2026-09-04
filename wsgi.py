"""生产 WSGI 入口：gunicorn 加载此模块。
用法：gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app
"""
from app import create_app

app = create_app()
