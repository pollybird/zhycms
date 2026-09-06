import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def _resolve_secret_key():
    """解析 SECRET_KEY。

    优先级：环境变量 ``ZHYCMS_SECRET_KEY``（兼容旧前缀 ``ZHOCMS_SECRET_KEY``）
    > ``instance/secret_key`` 持久化文件 > 首次启动自动生成随机密钥并落盘。

    安全修复（v2.4.1）：不再回退到源码中硬编码的默认密钥（CWE-798）。
    Flask 会话为客户端签名 Cookie，硬编码密钥会导致可离线伪造管理员会话。
    随机密钥持久化在 ``instance/secret_key``（权限 600，该目录已 gitignore）。
    存量部署首次启动会自动生成新密钥并使旧会话失效（需重新登录）。
    """
    env_key = os.environ.get('ZHYCMS_SECRET_KEY') or os.environ.get('ZHOCMS_SECRET_KEY')
    if env_key:
        return env_key
    key_path = os.path.join(BASE_DIR, 'instance', 'secret_key')
    try:
        if os.path.exists(key_path):
            with open(key_path, 'r', encoding='utf-8') as f:
                key = f.read().strip()
            if key:
                return key
    except OSError:
        pass
    # 生成随机密钥并持久化
    key = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        with open(key_path, 'w', encoding='utf-8') as f:
            f.write(key)
        os.chmod(key_path, 0o600)
    except OSError:
        # 无法落盘时也使用本次随机密钥（至少不使用硬编码值），仅影响重启后会话失效
        pass
    return key


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
    # 基础配置（SECRET_KEY：环境变量 > instance/secret_key 持久化 > 首次启动生成）
    SECRET_KEY = _resolve_secret_key()

    # v2.5.0：Redis URL（可选）。有值则启用 Redis 缓存 + 服务端 Session，无则回退 SimpleCache + Cookie Session
    REDIS_URL = os.environ.get('REDIS_URL', '')

    # 会话安全（v2.4.1）：显式 SameSite，HTTPS 下启用 Secure（生产环境由反向代理
    # 或 ZHYCMS_ENV=production 触发 ProductionConfig 中的 SESSION_COOKIE_SECURE）
    SESSION_COOKIE_SAMESITE = 'Lax'

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
    # v2.5.0：有 REDIS_URL 时 Session 存入 Redis（多实例共享登录态），否则保持默认 Cookie Session
    if REDIS_URL:
        SESSION_TYPE = 'redis'
        SESSION_PERMANENT = True
        SESSION_USE_SIGNER = True
        SESSION_KEY_PREFIX = 'zhycms:sess:'
        # SESSION_REDIS 在 create_app 中用 redis.from_url(REDIS_URL) 延迟初始化，避免 import 阶段建连接

    # 分页
    DEFAULT_PAGE_SIZE = 10

    # 后台每页显示条数
    ADMIN_PAGE_SIZE = 15

    # 模块8：Flask-Caching 配置
    # v2.5.0：有 REDIS_URL 时切 RedisCache（多实例共享缓存），否则 SimpleCache（单机零依赖）
    if REDIS_URL:
        CACHE_TYPE = 'RedisCache'
        CACHE_REDIS_URL = REDIS_URL
        CACHE_KEY_PREFIX = 'zhycms:'
        CACHE_DEFAULT_TIMEOUT = 3600
    else:
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
        # SimpleCache 模式需要缓存目录，Redis 模式无 CACHE_DIR
        cache_dir = getattr(Config, 'CACHE_DIR', None)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
        os.makedirs(Config.IMAGE_TEMP_DIR, exist_ok=True)


class DevelopmentConfig(Config):
    DEBUG = True
    ENV = 'development'


class ProductionConfig(Config):
    DEBUG = False
    ENV = 'production'
    # HTTPS 部署时会话 Cookie 仅通过 HTTPS 传输，防明文窃取
    SESSION_COOKIE_SECURE = True


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
