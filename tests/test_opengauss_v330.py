"""v3.3.0 信创适配：openGauss 连接层单元测试。

覆盖：
  - 方言版本串解析（openGauss / openGauss-lite）
  - 方言注册幂等与 Alembic DDL 实现登记
  - build_engine_options 按后端选择连接池参数
  - build_uri 的 opengauss 与 Unix socket 形态
  - 驱动缺失 / 连接失败的可操作中文提示
  - switch_engine 按新 URI 重建参数
  - 备份/恢复的 openGauss 分支与工具路径解析
  - healthz 方言字段与初始化向导 openGauss 选项
"""
import gzip
import json
import types

import pytest
from sqlalchemy.dialects import registry
from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2
from sqlalchemy.engine import make_url

from app.config import build_engine_options
from app.utils import backup_utils, dbconfig
from app.utils.dialects.opengauss import (
    _OG_VERSION_RE,
    OpenGaussDialect,
    register_opengauss_dialect,
)


class TestDialectVersion:
    def test_lite_version_string(self):
        m = _OG_VERSION_RE.search('(openGauss-lite 7.0.0-RC3 build 1234)')
        assert m is not None
        assert m.groups() == ('7', '0', '0')

    def test_standard_version_string(self):
        m = _OG_VERSION_RE.search('openGauss 5.0.0 build 8f3a')
        assert m is not None
        assert m.groups() == ('5', '0', '0')

    def test_non_opengauss_version(self):
        assert _OG_VERSION_RE.search('PostgreSQL 14.5 on x86_64') is None


class TestDialectRegistration:
    def test_register_idempotent(self):
        assert register_opengauss_dialect() in ('builtin', 'official')
        register_opengauss_dialect()
        cls = registry.load('opengauss')
        assert issubclass(cls, PGDialect_psycopg2)
        assert cls.name == 'opengauss'

    def test_psycopg2_variant_registered(self):
        register_opengauss_dialect()
        assert registry.load('opengauss.psycopg2') is OpenGaussDialect

    def test_alembic_impl_registered(self):
        register_opengauss_dialect()
        from alembic.ddl.impl import DefaultImpl

        class _FakeDialect:
            name = 'opengauss'

        impl = DefaultImpl.get_by_dialect(_FakeDialect())
        assert impl.__dialect__ == 'opengauss'


class TestBuildEngineOptions:
    def test_sqlite_keeps_default(self):
        assert build_engine_options('sqlite:///tmp.db') == {'pool_pre_ping': True}

    def test_opengauss_pool_and_connect_args(self):
        opts = build_engine_options(
            'opengauss+psycopg2://u:p@127.0.0.1:5432/zhycms')
        assert opts['pool_pre_ping'] is True
        assert opts['pool_size'] == 10
        assert opts['max_overflow'] == 20
        assert opts['pool_recycle'] == 1800
        assert opts['pool_timeout'] == 30
        assert opts['connect_args'] == {
            'connect_timeout': 5,
            'application_name': 'zhycms',
        }

    def test_invalid_uri_fallback(self):
        assert build_engine_options('not-a-valid-uri') == {'pool_pre_ping': True}


class TestBuildUri:
    def test_opengauss_uri(self):
        uri = dbconfig.build_uri(
            'opengauss', '10.0.0.5', '', 'zhycms', 'gaussdb', 'p@ss')
        parsed = make_url(uri)
        assert parsed.drivername == 'opengauss+psycopg2'
        assert parsed.host == '10.0.0.5'
        assert parsed.port == 5432
        assert parsed.password == 'p@ss'

    def test_postgresql_socket(self):
        uri = dbconfig.build_uri(
            'postgresql', '/var/run/postgresql', '', 'zhycms', 'u', 'p')
        parsed = make_url(uri)
        assert parsed.host is None
        assert parsed.port is None
        assert parsed.query['host'] == '/var/run/postgresql'

    def test_mysql_socket(self):
        uri = dbconfig.build_uri(
            'mysql', '/var/run/mysqld/mysqld.sock', '', 'zhycms', 'u', 'p')
        parsed = make_url(uri)
        assert parsed.host is None
        assert parsed.query['unix_socket'] == '/var/run/mysqld/mysqld.sock'
        assert parsed.query['charset'] == 'utf8mb4'


class TestConnectionHints:
    def test_missing_driver_message(self, monkeypatch):
        import sqlalchemy

        def _boom(*args, **kwargs):
            raise ModuleNotFoundError('No module named psycopg2')

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        ok, msg = dbconfig.test_connection(
            'opengauss+psycopg2://u:p@127.0.0.1:5432/zhycms')
        assert ok is False
        assert 'openGauss' in msg
        assert '驱动' in msg

    def test_connection_refused_hint(self, monkeypatch):
        import sqlalchemy
        from sqlalchemy.exc import OperationalError

        def _boom(*args, **kwargs):
            raise OperationalError('SELECT 1', {}, Exception('connection refused'))

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        ok, msg = dbconfig.test_connection(
            'opengauss+psycopg2://u:p@127.0.0.1:5432/zhycms')
        assert ok is False
        assert 'openGauss' in msg
        assert 'pg_hba.conf' in msg

    def test_sha256_auth_hint(self, monkeypatch):
        import sqlalchemy
        from sqlalchemy.exc import OperationalError

        def _boom(*args, **kwargs):
            raise OperationalError(
                'SELECT 1', {}, Exception('Invalid password, sha256 auth failed'))

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        ok, msg = dbconfig.test_connection(
            'opengauss+psycopg2://u:p@127.0.0.1:5432/zhycms')
        assert ok is False
        assert 'sha256' in msg


class TestSwitchEngine:
    def test_switch_engine_rebuilds_opengauss_options(self, monkeypatch):
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

        uri = 'opengauss+psycopg2://u:p@127.0.0.1:5432/zhycms'
        engine = dbconfig.switch_engine(app, fake_db, uri)

        assert isinstance(engine, _FakeEngine)
        assert engines[None] is engine
        assert app.config['ZHYCMS_DB_DIALECT'] == 'opengauss'
        assert app.config['SQLALCHEMY_ENGINE_OPTIONS']['pool_size'] == 10
        assert 'url' not in app.config['SQLALCHEMY_ENGINE_OPTIONS']
        assert captured['url'] == uri
        assert captured['pool_size'] == 10
        assert captured['connect_args']['application_name'] == 'zhycms'


def test_create_app_records_dialect(app):
    assert app.config['ZHYCMS_DB_DIALECT'] == 'sqlite'
    assert app.config['SQLALCHEMY_ENGINE_OPTIONS'] == {'pool_pre_ping': True}


class TestBackupTargetParsing:
    def _parse(self, app, monkeypatch, uri):
        with app.app_context():
            monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', uri)
            return backup_utils._db_type_and_path()

    def test_opengauss_uri(self, app, monkeypatch):
        db_type, dbname, host, port, user, pwd = self._parse(
            app, monkeypatch,
            'opengauss+psycopg2://gaussdb:Zhycms%4012345@127.0.0.1:15432/zhycms')
        assert (db_type, dbname, host, port, user, pwd) == (
            'opengauss', 'zhycms', '127.0.0.1', 15432, 'gaussdb', 'Zhycms@12345')

    def test_opengauss_socket_host_in_query(self, app, monkeypatch):
        uri = dbconfig.build_uri(
            'opengauss', '/var/run/opengauss', '', 'zhycms', 'u', 'p')
        db_type, dbname, host, port, *_ = self._parse(app, monkeypatch, uri)
        assert db_type == 'opengauss'
        assert dbname == 'zhycms'
        assert host == '/var/run/opengauss'
        assert port is None

    def test_mysql_socket_host_in_query(self, app, monkeypatch):
        uri = dbconfig.build_uri(
            'mysql', '/var/run/mysqld/mysqld.sock', '', 'zhycms', 'u', 'p')
        db_type, dbname, host, _port, *_ = self._parse(app, monkeypatch, uri)
        assert db_type == 'mysql'
        assert dbname == 'zhycms'
        assert host == '/var/run/mysqld/mysqld.sock'

    def test_unknown_uri(self, app, monkeypatch):
        db_type, rest, *_ = self._parse(app, monkeypatch, 'oracle://u:p@h/db')
        assert db_type == 'unknown'
        assert rest == 'oracle://u:p@h/db'


class TestBinTool:
    def test_config_bin_dir_first(self, app, monkeypatch, tmp_path):
        tool = tmp_path / 'gs_dump'
        tool.write_text('')
        monkeypatch.setenv('ZHYCMS_DB_DUMP_BIN', '')
        with app.app_context():
            monkeypatch.setitem(app.config, 'DB_DUMP_BIN_DIR', str(tmp_path))
            assert backup_utils._bin_tool('gs_dump', 'opengauss') == str(tool)

    def test_opengauss_bin_env(self, monkeypatch, tmp_path):
        tool = tmp_path / 'gsql'
        tool.write_text('')
        monkeypatch.setenv('ZHYCMS_DB_DUMP_BIN', '')
        monkeypatch.setenv('OPENGAUSS_BIN', str(tmp_path))
        assert backup_utils._bin_tool('gsql', 'opengauss') == str(tool)

    def test_tool_env_injects_opengauss_lib(self, monkeypatch, tmp_path):
        monkeypatch.setenv('ZHYCMS_OPENGAUSS_LIB', str(tmp_path))
        env = backup_utils._tool_env('opengauss', 'secret')
        assert env['PGPASSWORD'] == 'secret'
        assert env['LD_LIBRARY_PATH'].split(':')[0] == str(tmp_path)

    def test_tool_env_plain_backend(self, monkeypatch):
        monkeypatch.delenv('ZHYCMS_OPENGAUSS_LIB', raising=False)
        env = backup_utils._tool_env('postgresql', 'secret')
        assert env['PGPASSWORD'] == 'secret'
        assert 'LD_LIBRARY_PATH' not in env or not env['LD_LIBRARY_PATH'].startswith(
            '/usr/local/opengauss/lib')


class TestBackupCommands:
    def test_backup_pg_opengauss_command(self, monkeypatch, tmp_path):
        captured = {}

        def _fake_run(cmd, dest_path, dbname, env=None):
            captured.update(cmd=cmd, dbname=dbname, env=env)
            return True

        monkeypatch.setattr(backup_utils, '_run_og_dump_with_gzip', _fake_run)
        monkeypatch.setattr(
            backup_utils, '_bin_tool',
            lambda name, db_type=None: f'/opt/opengauss/bin/{name}')
        monkeypatch.setenv('ZHYCMS_OPENGAUSS_LIB', str(tmp_path))

        ok = backup_utils._backup_pg(
            str(tmp_path / 'zhycms_opengauss.sql.gz'), 'zhycms',
            '127.0.0.1', 15432, 'gaussdb', 'Zhycms@12345', db_type='opengauss')

        assert ok is True
        cmd = captured['cmd']
        assert cmd[0] == '/opt/opengauss/bin/gs_dump'
        assert '--host=127.0.0.1' in cmd
        assert '--port=15432' in cmd
        assert '--username=gaussdb' in cmd
        assert '-d' not in cmd
        assert captured['dbname'] == 'zhycms'
        assert captured['env']['PGPASSWORD'] == 'Zhycms@12345'
        assert captured['env']['LD_LIBRARY_PATH'].split(':')[0] == str(tmp_path)

    def test_restore_pg_opengauss_command(self, app, monkeypatch, tmp_path):
        captured = {}

        class _Proc:
            returncode = 0

            def communicate(self, timeout=None):
                return b'', b''

        def _fake_popen(cmd, **kwargs):
            captured.update(cmd=cmd, env=kwargs.get('env'))
            return _Proc()

        monkeypatch.setattr(backup_utils.subprocess, 'Popen', _fake_popen)
        monkeypatch.setattr(
            backup_utils, '_bin_tool',
            lambda name, db_type=None: f'/opt/opengauss/bin/{name}')
        monkeypatch.setattr(backup_utils, '_db_type_and_path',
                            lambda: ('opengauss', 'zhycms', '127.0.0.1',
                                     15432, 'gaussdb', 'pw'))

        gz_path = tmp_path / 'zhycms_opengauss.sql.gz'
        with gzip.open(gz_path, 'wb') as f:
            f.write(b'SELECT 1;\n')

        with app.app_context():
            ok, msg = backup_utils._restore_pg(str(gz_path))

        assert ok is True
        assert msg == 'openGauss 恢复成功'
        cmd = captured['cmd']
        assert cmd[0] == '/opt/opengauss/bin/gsql'
        assert '-d' in cmd
        assert cmd[cmd.index('-d') + 1] == 'zhycms'
        assert '-f' in cmd


def test_healthz_detail_reports_db_dialect(client):
    resp = client.get('/healthz?detail=1')
    assert resp.status_code == 200
    assert json.loads(resp.get_data(as_text=True))['db_dialect'] == 'sqlite'


def test_setup_accepts_opengauss(app, client, monkeypatch):
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
        'username': 'ogadmin',
        'nickname': 'openGauss Admin',
        'password': 'Abcdef123456!',
        'password_confirm': 'Abcdef123456!',
        'demo_type': 'none',
        'db_type': 'opengauss',
        'db_host': '127.0.0.1',
        'db_port': '15432',
        'db_name': 'zhycms',
        'db_user': 'gaussdb',
        'db_password': 'Zhycms@12345',
    })

    assert resp.status_code == 302
    assert saved['db_type'] == 'opengauss'
    assert saved['uri'].startswith('opengauss+psycopg2://')
    assert saved['meta']['port'] == 15432


def test_current_db_label_opengauss(app):
    from app.admin.auth import _current_db_label

    original = app.config['SQLALCHEMY_DATABASE_URI']
    with app.app_context():
        app.config['SQLALCHEMY_DATABASE_URI'] = (
            'opengauss+psycopg2://u:p@127.0.0.1:5432/zhycms')
        try:
            assert _current_db_label() == 'openGauss'
        finally:
            app.config['SQLALCHEMY_DATABASE_URI'] = original
