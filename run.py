"""zhycms 启动入口。

开发模式：
    python run.py

生产模式：
    ZHYCMS_ENV=production python run.py
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
