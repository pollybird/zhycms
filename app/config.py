import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def _resolve_database_uri():
    """按优先级解析启动时的数据库 URI。

    优先级：环境变量 ZHYCMS_DB_URI > instance/db_config.json（初始化向导所存）
    > 默认 SQLite。延迟导入 dbconfig 以避免潜在循环依赖。

    兼容说明：v2.1 前环境变量前缀为 ZHOCMS_（历史拼写差异），
    仍作为回退读取，未来版本将移除。
    """
    env_uri = os.environ.get('ZHYCMS_DB_URI') or os.environ.get('ZHOCMS_DB_URI')
    if env_uri:
        return env_uri
    try:
        from app.utils.dbconfig import load_db_uri
        saved = load_db_uri()
        if saved:
            return saved
    except Exception:
        # 配置文件缺失或损坏时静默回退到默认库，保证应用可启动进入初始化向导
        pass
    return 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'zhycms.db')


class Config:
    # 基础配置（SECRET_KEY 兼容读取旧前缀 ZHOCMS_SECRET_KEY）
    SECRET_KEY = (os.environ.get('ZHYCMS_SECRET_KEY')
                  or os.environ.get('ZHOCMS_SECRET_KEY')
                  or 'zhycms-default-secret-key-change-in-production')

    # 数据库 URI：ZHYCMS_DB_URI > instance/db_config.json > 默认 SQLite
    SQLALCHEMY_DATABASE_URI = _resolve_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}

    # 文件上传
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'app', 'static', 'uploads')
    BACKUP_FOLDER = os.path.join(BASE_DIR, 'instance', 'backups')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 默认 50MB，单字段可在数据库配置中再约束

    # 会话
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    SESSION_COOKIE_HTTPONLY = True

    # 分页
    DEFAULT_PAGE_SIZE = 10

    # 后台每页显示条数
    ADMIN_PAGE_SIZE = 15

    # 模块8：Flask-Caching 配置（默认 SimpleCache，单进程够用；生产可切 filesystem / redis）
    CACHE_TYPE = 'SimpleCache'
    CACHE_DEFAULT_TIMEOUT = 3600
    CACHE_DIR = os.path.join(BASE_DIR, 'instance', 'cache')

    # 图片缩略图与压缩临时目录
    IMAGE_TEMP_DIR = os.path.join(BASE_DIR, 'instance', 'image_cache')

    @staticmethod
    def init_app(app):
        os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)
        os.makedirs(os.path.join(BASE_DIR, 'app', 'static', 'uploads'), exist_ok=True)
        os.makedirs(os.path.join(BASE_DIR, 'instance', 'backups'), exist_ok=True)
        os.makedirs(Config.CACHE_DIR, exist_ok=True)
        os.makedirs(Config.IMAGE_TEMP_DIR, exist_ok=True)


class DevelopmentConfig(Config):
    DEBUG = True
    ENV = 'development'


class ProductionConfig(Config):
    DEBUG = False
    ENV = 'production'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
