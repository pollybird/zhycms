"""PolarDB for PostgreSQL（v3.3.3）适配测试。

覆盖：
  - 方言与 Alembic DDL 实现注册
  - 版本串解析与 SHOW server_version 兜底
  - build_engine_options / build_uri 的 polardb_pg 分支
  - 驱动缺失 / 方言缺失 / 认证失败 / 连接拒绝的中文提示
  - switch_engine 按新 URI 注册方言并重建参数
  - 备份/恢复 pg_dump / psql 命令构造与工具路径解析
  - 初始化向导 polardb_pg 选项与 _current_db_label
  - live 集成（ZHYCMS_TEST_POLARDB_URL 门控，默认跳过）

启用 live 集成（ZHYCMS_SECRET_KEY 须在进程启动前导出，因 SECRET_KEY 在导入时求值）：
    ZHYCMS_SECRET_KEY=polardb-live \
    ZHYCMS_TEST_POLARDB_URL=polardb_pg+psycopg2://zhycms:pwd@127.0.0.1:5432/zhycms \
    pytest tests/test_polardb.py -q
"""
import gzip
import json
import os
import types

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.dialects import registry
from sqlalchemy.engine import make_url

from app.config import build_engine_options
from app.utils import backup_utils, dbconfig
import app.utils.dialects.polardb as polardb_dialect

POLARDB_URL = os.environ.get('ZHYCMS_TEST_POLARDB_URL', '').strip()
requires_polardb = pytest.mark.skipif(
    not POLARDB_URL, reason='未设置 ZHYCMS_TEST_POLARDB_URL')


# ============================================================
# 方言注册与 Alembic impl
# ============================================================
class TestDialectRegistration:
    def test_register_returns_builtin(self):
        assert polardb_dialect.register_polardb_dialect() == 'builtin'

    def test_register_idempotent(self):
        polardb_dialect.register_polardb_dialect()
        polardb_dialect.register_polardb_dialect()  # 重复注册不抛异常

    def test_dialect_registered(self):
        polardb_dialect.register_polardb_dialect()
        cls = registry.load('polardb_pg')
        assert cls is polardb_dialect.PolarDBPGDialect
        assert cls.name == 'polardb_pg'
        assert cls.driver == 'psycopg2'
        assert registry.load('polardb_pg.psycopg2') is cls

    def test_alembic_impl_registered(self):
        polardb_dialect.register_polardb_dialect()
        from alembic.ddl.impl import DefaultImpl

        class _FakeDialect:
            name = 'polardb_pg'

        impl = DefaultImpl.get_by_dialect(_FakeDialect())
        assert impl.__dialect__ == 'polardb_pg'


# ============================================================
# 版本解析
# ============================================================
class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeConn:
    def __init__(self, version_value, show_value='15.20'):
        self._version_value = version_value
        self._show_value = show_value

    def exec_driver_sql(self, sql):
        if 'version()' in sql:
            return _FakeResult(self._version_value)
        return _FakeResult(self._show_value)


class TestServerVersion:
    def test_standard_pg_version_string(self):
        d = polardb_dialect.PolarDBPGDialect()
        conn = _FakeConn(
            'PostgreSQL 15.20 (PolarDB 15.20.5.0 build abcdef) on x86_64')
        assert d._get_server_version_info(conn) == (15, 20)

    def test_fallback_when_version_unparsable(self):
        d = polardb_dialect.PolarDBPGDialect()
        conn = _FakeConn('PolarDB 15.20.5.0 build abcdef', show_value='15.20')
        assert d._get_server_version_info(conn) == (15, 20)

    def test_final_fallback_does_not_crash(self):
        d = polardb_dialect.PolarDBPGDialect()
        conn = _FakeConn('unknown', show_value='')
        assert d._get_server_version_info(conn) == (15, 0)


# ============================================================
# 引擎参数
# ============================================================
class TestBuildEngineOptions:
    def test_polardb_pool_and_connect_args(self):
        opts = build_engine_options(
            'polardb_pg+psycopg2://zhycms:pwd@127.0.0.1:5432/zhycms')
        assert opts['pool_pre_ping'] is True
        assert opts['pool_size'] == 10
        assert opts['max_overflow'] == 20
        assert opts['pool_recycle'] == 1800
        assert opts['pool_timeout'] == 30
        assert opts['connect_args'] == {
            'connect_timeout': 5, 'application_name': 'zhycms'}


# ============================================================
# URI 构造
# ============================================================
class TestBuildUri:
    def test_polardb_default_port(self):
        uri = dbconfig.build_uri(
            'polardb_pg', '10.0.0.5', '', 'zhycms', 'zhycms', 'p@ss')
        parsed = make_url(uri)
        assert parsed.drivername == 'polardb_pg+psycopg2'
        assert parsed.host == '10.0.0.5'
        assert parsed.port == 5432
        assert parsed.database == 'zhycms'
        assert parsed.password == 'p@ss'

    def test_polardb_explicit_port(self):
        uri = dbconfig.build_uri(
            'polardb_pg', '10.0.0.5', '5433', 'zhycms', 'U', 'pw')
        assert make_url(uri).port == 5433

    def test_polardb_no_charset_query(self):
        uri = dbconfig.build_uri(
            'polardb_pg', '10.0.0.5', '', 'zhycms', 'U', 'pw')
        assert make_url(uri).query == {}


# ============================================================
# 连接错误提示
# ============================================================
class TestConnectionHints:
    def test_missing_driver_message(self, monkeypatch):
        import sqlalchemy

        def _boom(*args, **kwargs):
            raise ModuleNotFoundError('No module named psycopg2')

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        ok, msg = dbconfig.test_connection(
            'polardb_pg+psycopg2://zhycms:pwd@127.0.0.1:5432/zhycms')
        assert ok is False
        assert 'PolarDB' in msg
        assert 'psycopg2-binary' in msg

    def test_missing_dialect_message(self, monkeypatch):
        import sqlalchemy
        from sqlalchemy.exc import NoSuchModuleError

        def _boom(*args, **kwargs):
            raise NoSuchModuleError(
                "Can't load plugin: sqlalchemy.dialects:polardb_pg.psycopg2")

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        ok, msg = dbconfig.test_connection(
            'polardb_pg+psycopg2://zhycms:pwd@127.0.0.1:5432/zhycms')
        assert ok is False
        assert '内置方言' in msg

    def test_auth_failure_hint(self, monkeypatch):
        import sqlalchemy
        from sqlalchemy.exc import OperationalError

        def _boom(*args, **kwargs):
            raise OperationalError(
                'SELECT 1', {}, Exception('password authentication failed'))

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        ok, msg = dbconfig.test_connection(
            'polardb_pg+psycopg2://zhycms:pwd@127.0.0.1:5432/zhycms')
        assert ok is False
        assert '认证' in msg

    def test_connection_refused_hint(self, monkeypatch):
        import sqlalchemy
        from sqlalchemy.exc import OperationalError

        def _boom(*args, **kwargs):
            raise OperationalError(
                'SELECT 1', {}, Exception('Connection refused'))

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        ok, msg = dbconfig.test_connection(
            'polardb_pg+psycopg2://zhycms:pwd@127.0.0.1:5432/zhycms')
        assert ok is False
        assert '5432' in msg


# ============================================================
# switch_engine
# ============================================================
class TestSwitchEngine:
    def test_switch_engine_rebuilds_polardb_options(self, monkeypatch):
        captured = {}

        class _FakeEngine:
            def dispose(self):
                pass

        def _fake_engine_from_config(options, prefix=''):
            captured.update(options)
            return _FakeEngine()

        monkeypatch.setattr(dbconfig, 'engine_from_config', _fake_engine_from_config)
        app = types.SimpleNamespace(config={})
        engines = {None: None}
        fake_db = types.SimpleNamespace(
            session=types.SimpleNamespace(remove=lambda: None),
            engines=engines,
        )

        uri = 'polardb_pg+psycopg2://zhycms:pwd@127.0.0.1:5432/zhycms'
        engine = dbconfig.switch_engine(app, fake_db, uri)

        assert isinstance(engine, _FakeEngine)
        assert app.config['ZHYCMS_DB_DIALECT'] == 'polardb_pg'
        assert app.config['SQLALCHEMY_ENGINE_OPTIONS']['pool_size'] == 10
        assert captured['url'] == uri
        assert captured['connect_args'] == {
            'connect_timeout': 5, 'application_name': 'zhycms'}


# ============================================================
# 备份目标解析与工具路径
# ============================================================
class TestBackupTargetParsing:
    def test_polardb_uri(self, app, monkeypatch):
        with app.app_context():
            monkeypatch.setitem(
                app.config, 'SQLALCHEMY_DATABASE_URI',
                'polardb_pg+psycopg2://zhycms:Zhycms%4012345'
                '@127.0.0.1:5432/zhycms')
            got = backup_utils._db_type_and_path()
        assert got == ('polardb_pg', 'zhycms', '127.0.0.1', 5432,
                       'zhycms', 'Zhycms@12345')


class TestBinTool:
    def test_polardb_bin_env(self, monkeypatch, tmp_path):
        tool = tmp_path / 'pg_dump'
        tool.write_text('')
        monkeypatch.setenv('ZHYCMS_DB_DUMP_BIN', '')
        monkeypatch.setenv('ZHYCMS_POLARDB_BIN', str(tmp_path))
        assert backup_utils._bin_tool('pg_dump', 'polardb_pg') == str(tool)

    def test_polardb_home_bin_subdir(self, monkeypatch, tmp_path):
        (tmp_path / 'bin').mkdir()
        tool = tmp_path / 'bin' / 'psql'
        tool.write_text('')
        monkeypatch.setenv('ZHYCMS_DB_DUMP_BIN', '')
        monkeypatch.delenv('ZHYCMS_POLARDB_BIN', raising=False)
        monkeypatch.setenv('POLARDB_HOME', str(tmp_path))
        assert backup_utils._bin_tool('psql', 'polardb_pg') == str(tool)


# ============================================================
# 备份/恢复命令构造
# ============================================================
class _FakeProc:
    returncode = 0

    def communicate(self, timeout=None):
        return b'', b''


class TestBackupCommands:
    def test_backup_polardb_uses_pg_dump(self, monkeypatch, tmp_path):
        captured = {}

        def _fake_dump(cmd, dest_path, env=None, fallback_json=False):
            captured['cmd'] = cmd
            captured['env'] = env
            return True

        monkeypatch.setattr(backup_utils, '_bin_tool',
                            lambda name, db_type=None: name)
        monkeypatch.setattr(backup_utils, '_run_dump_with_gzip', _fake_dump)

        dest = tmp_path / 'zhycms_polardb_pg_20260101_000000.sql.gz'
        ok = backup_utils._backup_pg(
            str(dest), 'zhycms', '127.0.0.1', 5432, 'zhycms', 'pwd',
            db_type='polardb_pg')

        assert ok is True
        cmd = captured['cmd']
        assert cmd[0] == 'pg_dump'
        assert '--no-password' in cmd
        assert cmd[-1] == 'zhycms'
        assert captured['env']['PGPASSWORD'] == 'pwd'


class TestRestoreCommands:
    def test_restore_polardb_uses_psql(self, app, monkeypatch, tmp_path):
        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured['cmd'] = cmd
            return _FakeProc()

        monkeypatch.setattr(backup_utils.subprocess, 'Popen', _fake_popen)
        monkeypatch.setattr(backup_utils, '_bin_tool',
                            lambda name, db_type=None: name)
        monkeypatch.setattr(
            backup_utils, '_db_type_and_path',
            lambda: ('polardb_pg', 'zhycms', '127.0.0.1', 5432,
                     'zhycms', 'pwd'))

        gz_path = tmp_path / 'zhycms_polardb_restore.sql.gz'
        with gzip.open(gz_path, 'wb') as f:
            f.write(b'SELECT 1;')

        with app.app_context():
            ok, msg = backup_utils._restore_pg(str(gz_path))

        assert ok is True
        assert msg == 'PolarDB for PostgreSQL 恢复成功'
        cmd = captured['cmd']
        assert cmd[0] == 'psql'
        assert '-f' in cmd


# ============================================================
# 向导与显示标签
# ============================================================
def test_current_db_label_polardb(app):
    from app.admin.auth import _current_db_label

    original = app.config['SQLALCHEMY_DATABASE_URI']
    with app.app_context():
        app.config['SQLALCHEMY_DATABASE_URI'] = (
            'polardb_pg+psycopg2://zhycms:pwd@127.0.0.1:5432/zhycms')
        try:
            assert _current_db_label() == 'PolarDB for PostgreSQL'
        finally:
            app.config['SQLALCHEMY_DATABASE_URI'] = original


def test_setup_accepts_polardb(app, client, monkeypatch):
    from app.admin import auth as admin_auth

    saved = {}

    monkeypatch.setattr(admin_auth, '_is_initialized', lambda: False)
    monkeypatch.setattr(admin_auth, '_db_managed_by_env', lambda: False)
    monkeypatch.setattr(admin_auth, 'test_connection', lambda uri: (True, '连接成功'))
    monkeypatch.setattr(
        admin_auth, 'save_db_config',
        lambda db_type, uri, meta=None: saved.update(
            db_type=db_type, uri=uri, meta=meta))
    monkeypatch.setattr(admin_auth, 'switch_engine', lambda *a, **kw: None)
    monkeypatch.setattr(admin_auth, 'init_default_settings', lambda: None)
    monkeypatch.setattr(
        admin_auth, 'create_admin',
        lambda username, password, nickname=None: types.SimpleNamespace(id=1))

    resp = client.post('/admin/setup', data={
        'username': 'pdbadmin',
        'nickname': 'PolarDB Admin',
        'password': 'Abcdef123456!',
        'password_confirm': 'Abcdef123456!',
        'demo_type': 'none',
        'db_type': 'polardb_pg',
        'db_host': '127.0.0.1',
        'db_port': '',
        'db_name': 'zhycms',
        'db_user': 'zhycms',
        'db_password': 'Zhycms-2026pdb',
    })

    assert resp.status_code == 302
    assert saved['db_type'] == 'polardb_pg'
    assert saved['uri'].startswith('polardb_pg+psycopg2://')
    assert saved['meta']['port'] == 5432  # 未填端口时回退默认 5432


# ============================================================
# live 集成（ZHYCMS_TEST_POLARDB_URL 门控，默认跳过）
# ============================================================
@requires_polardb
class TestPolarDBLive:
    def test_connect_and_select(self):
        from sqlalchemy import create_engine, text

        polardb_dialect.register_polardb_dialect()
        engine = create_engine(POLARDB_URL, pool_pre_ping=True)
        try:
            assert engine.dialect.name == 'polardb_pg'
            with engine.connect() as conn:
                assert conn.execute(text('SELECT 1')).scalar() == 1
                version = str(conn.execute(text('SELECT version()')).scalar())
            assert 'PolarDB' in version
        finally:
            engine.dispose()

    def test_temp_table_crud(self):
        from sqlalchemy import create_engine, select

        polardb_dialect.register_polardb_dialect()
        engine = create_engine(POLARDB_URL)
        meta = MetaData()
        t = Table('t_polardb_live_crud', meta,
                  Column('id', Integer, primary_key=True),
                  Column('name', String(20)))
        try:
            meta.create_all(engine)
            with engine.begin() as conn:
                conn.execute(t.insert().values(name='first'))
                assert conn.execute(select(t.c.name)).scalar() == 'first'
        finally:
            with engine.begin() as conn:
                t.drop(conn, checkfirst=True)
            engine.dispose()

    def test_test_connection_ok(self):
        ok, msg = dbconfig.test_connection(POLARDB_URL)
        assert ok is True, msg

    def test_full_migration_and_healthz(self, monkeypatch):
        from app.config import Config as _AppConfig
        from app import create_app
        from app.extensions import db

        # SQLALCHEMY_DATABASE_URI 与 SECRET_KEY 均在 Config 类导入时求值，
        # 运行期改 os.environ 无效，需直接覆盖类属性（from_object 会读取）。
        monkeypatch.setattr(_AppConfig, 'SQLALCHEMY_DATABASE_URI', POLARDB_URL)
        pdb_app = create_app('production')
        try:
            assert pdb_app.config['ZHYCMS_DB_DIALECT'] == 'polardb_pg'
            with pdb_app.app_context():
                from sqlalchemy import text
                rev = db.session.execute(
                    text('SELECT version_num FROM alembic_version')).scalar()
                tables = db.session.execute(
                    text('SELECT count(*) FROM information_schema.tables '
                         "WHERE table_schema = 'public'")).scalar()
            assert rev == '0020'
            assert tables >= 40
            client = pdb_app.test_client()
            resp = client.get('/healthz?detail=1')
            assert resp.status_code == 200
            assert json.loads(
                resp.get_data(as_text=True))['db_dialect'] == 'polardb_pg'
        finally:
            with pdb_app.app_context():
                db.session.remove()
                db.engine.dispose()
