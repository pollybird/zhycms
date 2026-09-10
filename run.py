"""zhycms 启动入口。

开发模式：
    python run.py

生产模式（推荐使用 gunicorn，见 wsgi.py）：
    ZHYCMS_ENV=production python run.py

安全修复（v2.4.1）：debug 不再硬编码为 True，跟随当前配置类，
避免生产环境误开启 Werkzeug 调试器（CWE-489）。

v2.6.1：use_reloader 显式跟随 debug。reloader 会导致进程双开、
插件重复加载，生产环境必须关闭；开发环境开启便于热重载。
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    debug = app.config.get('DEBUG', False)
    app.run(host='0.0.0.0', port=5000, debug=debug, use_reloader=debug)
