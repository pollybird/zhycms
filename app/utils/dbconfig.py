"""数据库连接配置工具。

支持三种数据库：sqlite（默认）、mysql、postgresql。

- 初始化向导选择数据库类型后，mysql/postgresql 的连接信息会以
  ``instance/db_config.json`` 落盘（chmod 600），SQLite 则清除该文件走默认。
- 应用启动时的 URI 解析优先级见 ``app/config.py``：
  环境变量 ``ZHOCMS_DB_URI`` > ``db_config.json`` > 默认 sqlite。
- 初始化过程中可用 ``switch_engine`` 热切换 SQLAlchemy 引擎，免重启即时生效。
"""
import json
import os

from sqlalchemy import engine_from_config
from sqlalchemy.engine import URL

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
CONFIG_PATH = os.path.join(BASE_DIR, 'instance', 'db_config.json')

# 各数据库默认端口，供表单未填端口时回退使用
DEFAULT_PORTS = {'mysql': 3306, 'postgresql': 5432}

# 数据库类型 -> SQLAlchemy 驱动方言
_DRIVERS = {
    'mysql': 'mysql+pymysql',
    'postgresql': 'postgresql+psycopg2',
}


def build_uri(db_type, host, port, database, user, password):
    """根据数据库类型与连接信息构造 SQLAlchemy URI。

    使用 ``URL.create`` 以保证用户名、密码中的特殊字符被正确转义。
    mysql 追加 ``charset=utf8mb4`` 保证中文与 emoji 正常存储。
    """
    db_type = (db_type or '').strip().lower()
    if db_type not in _DRIVERS:
        raise ValueError(f'不支持的数据库类型：{db_type}')

    if not port:
        port = DEFAULT_PORTS[db_type]
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValueError('端口必须为数字')

    query = {'charset': 'utf8mb4'} if db_type == 'mysql' else {}
    url = URL.create(
        drivername=_DRIVERS[db_type],
        username=user or None,
        password=password or None,
        host=host or None,
        port=port,
        database=database or None,
        query=query,
    )
    return url.render_as_string(hide_password=False)


def load_db_uri():
    """从 ``db_config.json`` 读取已保存的数据库 URI，不存在或损坏返回 None。"""
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (ValueError, OSError):
        return None
    uri = data.get('uri')
    return uri or None


def save_db_config(db_type, uri, meta=None):
    """将数据库配置落盘为 ``db_config.json``，权限收敛为 600。

    ``meta`` 可携带 host/port/database/user 等非敏感信息，便于排查；
    密码已包含在 uri 中，不单独明文存储。
    """
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    payload = {'db_type': db_type, 'uri': uri}
    if meta:
        payload['meta'] = meta
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        # Windows 等平台可能不支持 chmod，忽略即可
        pass


def clear_db_config():
    """删除 ``db_config.json``，使应用回退到默认 SQLite。"""
    if os.path.exists(CONFIG_PATH):
        try:
            os.remove(CONFIG_PATH)
        except OSError:
            pass


def test_connection(uri):
    """尝试连接给定 URI，返回 ``(ok: bool, message: str)``。

    对常见错误分类给出友好中文提示：
    - 驱动缺失（ModuleNotFoundError）
    - 无法连接 / 认证失败（OperationalError）
    - 其它 SQLAlchemy 错误
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError, SQLAlchemyError

    engine = None
    try:
        engine = create_engine(uri, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        return True, '连接成功'
    except ModuleNotFoundError as e:
        return False, f'缺少数据库驱动：{e}。请先安装对应驱动（PyMySQL / psycopg2-binary）。'
    except OperationalError as e:
        return False, f'无法连接数据库，请检查主机、端口、账号密码或数据库是否存在。详情：{e.orig if e.orig else e}'
    except SQLAlchemyError as e:
        return False, f'数据库连接失败：{e}'
    except Exception as e:  # noqa: BLE001 兜底，避免向导因未知异常白屏
        return False, f'数据库连接失败：{e}'
    finally:
        if engine is not None:
            engine.dispose()


def switch_engine(app, db, new_uri):
    """在运行时热切换 SQLAlchemy 引擎，免重启即时生效。

    Flask-SQLAlchemy 3.x 的 ``db.session`` 每次通过 ``get_bind`` 动态读取
    ``db.engines[None]``，因此替换该字典中的引擎即可让后续 session 走新库。
    切换后需由调用方执行 ``db.create_all()`` 建表。
    """
    app.config['SQLALCHEMY_DATABASE_URI'] = new_uri
    options = dict(app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {}))
    options['url'] = new_uri

    db.session.remove()
    engines = db.engines
    old = engines.get(None)
    new_engine = engine_from_config(options, prefix='')
    engines[None] = new_engine
    if old is not None:
        old.dispose()
    return new_engine
