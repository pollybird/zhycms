"""数据库连接配置工具。

支持七种数据库：sqlite（默认）、mysql、postgresql、opengauss（v3.3.0）、
kingbase（v3.3.1，人大金仓 KingbaseES pg 模式）、dm（v3.3.2，达梦 DM8）、
polardb_pg（v3.3.3，PolarDB for PostgreSQL，Apache 2.0 开源自托管）。

- 初始化向导选择数据库类型后，mysql/postgresql/opengauss/kingbase/dm/polardb_pg
  的连接信息会以 ``instance/db_config.json`` 落盘（chmod 600），SQLite 则清除该
  文件走默认。
- 应用启动时的 URI 解析优先级见 ``app/config.py``：
  环境变量 ``ZHYCMS_DB_URI`` > ``db_config.json`` > 默认 sqlite。
- host 以 ``/`` 开头时按 Unix socket 路径处理（信创环境常见本机 socket 连接）。
- 初始化过程中可用 ``switch_engine`` 热切换 SQLAlchemy 引擎，免重启即时生效。
"""
import json
import logging
import os

from sqlalchemy import engine_from_config
from sqlalchemy.engine import URL

from flask_babel import gettext as _gettext
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
CONFIG_PATH = os.path.join(BASE_DIR, 'instance', 'db_config.json')

logger = logging.getLogger(__name__)

# 各数据库默认端口，供表单未填端口时回退使用
DEFAULT_PORTS = {'mysql': 3306, 'postgresql': 5432, 'opengauss': 5432,
                 'kingbase': 54321, 'dm': 5236, 'polardb_pg': 5432}

# 数据库类型 -> SQLAlchemy 驱动方言
_DRIVERS = {
    'mysql': 'mysql+pymysql',
    'postgresql': 'postgresql+psycopg2',
    'opengauss': 'opengauss+psycopg2',
    'kingbase': 'kingbase+psycopg2',
    'dm': 'dm+dmPython',
    'polardb_pg': 'polardb_pg+psycopg2',
}


def build_uri(db_type, host, port, database, user, password):
    """根据数据库类型与连接信息构造 SQLAlchemy URI。

    使用 ``URL.create`` 以保证用户名、密码中的特殊字符被正确转义。
    mysql 追加 ``charset=utf8mb4`` 保证中文与 emoji 正常存储。
    """
    db_type = (db_type or '').strip().lower()
    if db_type not in _DRIVERS:
        raise ValueError(_gettext('不支持的数据库类型：{0}').format(db_type))

    host = (host or '').strip()
    query = {'charset': 'utf8mb4'} if db_type == 'mysql' else {}
    if host.startswith('/'):
        # Unix socket：MySQL 用 unix_socket，PostgreSQL/openGauss/KingbaseES 用 host 参数
        query['unix_socket' if db_type == 'mysql' else 'host'] = host
        host = None
        port = None
    else:
        if not port:
            port = DEFAULT_PORTS[db_type]
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise ValueError(_gettext('端口必须为数字'))

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
    from sqlalchemy.exc import NoSuchModuleError, OperationalError, SQLAlchemyError

    uri = uri or ''
    is_opengauss = uri.startswith('opengauss')
    is_kingbase = uri.startswith('kingbase')
    is_dm = uri.startswith('dm+') or uri.startswith('dm:')
    is_polardb = uri.startswith('polardb_pg')
    engine = None
    try:
        engine = create_engine(uri, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        return True, '连接成功'
    except ModuleNotFoundError as e:
        if is_opengauss:
            return False, (f'缺少 openGauss 数据库驱动：{e}。请安装 openGauss 官方 '
                           'psycopg2 驱动（参考 requirements-opengauss.txt 与信创部署文档）。')
        if is_kingbase:
            return False, (f'缺少 KingbaseES 数据库驱动：{e}。KingbaseES（pg 模式）'
                           '复用标准 psycopg2-binary 驱动，请确认已安装 psycopg2-binary。')
        if is_polardb:
            return False, (f'缺少 PolarDB for PostgreSQL 数据库驱动：{e}。PolarDB-PG '
                           '复用标准 psycopg2-binary 驱动，请确认已安装 psycopg2-binary。')
        if is_dm:
            return False, (f'缺少达梦 DM8 数据库驱动：{e}。请安装 dmpython 与 '
                           'dmSQLAlchemy（pip install -r requirements-dm.txt）。')
        return False, f'缺少数据库驱动：{e}。请先安装对应驱动（PyMySQL / psycopg2-binary）。'
    except NoSuchModuleError as e:
        # 方言包未安装时 create_engine 阶段抛此异常（早于建立连接）
        logger.warning('数据库方言加载失败：%s', e, exc_info=True)
        if is_dm:
            return False, ('缺少达梦 DM8 数据库方言：请安装 dmpython 与 dmSQLAlchemy'
                           '（pip install -r requirements-dm.txt）。')
        if is_polardb:
            return False, ('缺少 PolarDB for PostgreSQL 数据库方言：内置方言未注册，'
                           '请确认应用版本与 psycopg2-binary 安装完整。')
        return False, '数据库方言加载失败，请确认已安装对应数据库驱动。'
    except OperationalError as e:
        # v3.1.9 VULN-013：对外文案固定，不回显 e.orig（含主机/端口/驱动细节），
        # 详细信息仅写日志供运维排障。
        logger.warning('数据库连接失败（OperationalError）：%s', e, exc_info=True)
        detail = str(getattr(e, 'orig', '') or e).lower()
        if is_opengauss:
            if 'sha256' in detail:
                return False, ('openGauss 认证失败：账号密码校验未通过（sha256 认证）。'
                               '请核对密码，并确认已安装支持 sha256 的 openGauss 官方驱动。')
            if any(k in detail for k in ('connection refused', 'could not connect',
                                         'timeout', 'timed out')):
                return False, ('无法连接 openGauss：请检查主机/端口连通性、监听地址，'
                               '以及 pg_hba.conf 是否允许本机或客户端 TCP 连接。')
        elif is_kingbase:
            if any(k in detail for k in ('password', 'authentication', 'auth failed',
                                         'no password supplied')):
                return False, ('KingbaseES 认证失败：账号或密码不正确。请核对账号密码，'
                               '并确认目标数据库已允许该账号连接（默认账号 system）。')
            if any(k in detail for k in ('connection refused', 'could not connect',
                                         'timeout', 'timed out')):
                return False, ('无法连接 KingbaseES：请检查主机/端口连通性（默认端口 '
                               '54321）、监听地址，以及 pg_hba.conf 是否允许本机或 '
                               '客户端 TCP 连接。')
        elif is_dm:
            if any(k in detail for k in ('密码', '口令', 'password', 'authentication',
                                         'invalid user', '无效的用')):
                return False, ('达梦 DM8 认证失败：用户名或密码不正确。请核对账号密码，'
                               '并确认该账号拥有目标 Schema 的访问权限。')
            if any(k in detail for k in ('connection refused', 'could not connect',
                                         'timeout', 'timed out', '通信')):
                return False, ('无法连接达梦 DM8：请检查主机/端口连通性（默认端口 5236）'
                               '与实例监听状态。')
        elif is_polardb:
            if any(k in detail for k in ('password', 'authentication', 'auth failed',
                                         'no password supplied')):
                return False, ('PolarDB for PostgreSQL 认证失败：账号或密码不正确。'
                               '请核对账号密码，并确认 pg_hba.conf 允许该客户端地址连接。')
            if any(k in detail for k in ('connection refused', 'could not connect',
                                         'timeout', 'timed out')):
                return False, ('无法连接 PolarDB for PostgreSQL：请检查主机/端口连通性'
                               '（默认端口 5432）、监听地址，以及 pg_hba.conf 是否允许'
                               '本机或客户端 TCP 连接。')
        return False, '无法连接数据库，请检查主机、端口、账号密码或数据库是否存在。'
    except SQLAlchemyError as e:
        logger.warning('数据库连接失败（SQLAlchemyError）：%s', e, exc_info=True)
        return False, '数据库连接失败，请检查连接配置后重试。'
    except Exception as e:  # noqa: BLE001 兜底，避免向导因未知异常白屏
        logger.warning('数据库连接失败（未知异常）：%s', e, exc_info=True)
        return False, '数据库连接失败，请检查连接配置后重试。'
    finally:
        if engine is not None:
            engine.dispose()


def switch_engine(app, db, new_uri):
    """在运行时热切换 SQLAlchemy 引擎，免重启即时生效。

    Flask-SQLAlchemy 3.x 的 ``db.session`` 每次通过 ``get_bind`` 动态读取
    ``db.engines[None]``，因此替换该字典中的引擎即可让后续 session 走新库。
    引擎参数按新 URI 重建（openGauss 与其它后端参数不同）。
    切换后需由调用方执行 ``db.create_all()`` 建表。
    """
    from app.config import build_engine_options

    app.config['SQLALCHEMY_DATABASE_URI'] = new_uri

    try:
        from sqlalchemy.engine import make_url
        backend = make_url(new_uri).get_backend_name()
    except Exception:
        backend = ''
    app.config['ZHYCMS_DB_DIALECT'] = backend
    if backend == 'opengauss':
        from app.utils.dialects import register_opengauss_dialect
        register_opengauss_dialect()
    elif backend == 'kingbase':
        from app.utils.dialects import register_kingbase_dialect
        register_kingbase_dialect()
    elif backend == 'polardb_pg':
        from app.utils.dialects import register_polardb_dialect
        register_polardb_dialect()
    elif backend == 'dm':
        from app.utils.dialects import register_dm_dialect
        if register_dm_dialect() != 'installed':
            raise RuntimeError(
                '缺少达梦 DM8 数据库驱动，请先安装 dmpython 与 dmSQLAlchemy'
                '（pip install -r requirements-dm.txt）')

    options = build_engine_options(new_uri)
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = dict(options)
    options['url'] = new_uri

    db.session.remove()
    engines = db.engines
    old = engines.get(None)
    new_engine = engine_from_config(options, prefix='')
    engines[None] = new_engine
    if old is not None:
        old.dispose()
    return new_engine
