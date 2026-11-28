"""达梦 DM8（v3.3.2）适配测试。

覆盖：
  - 方言与 Alembic DDL 实现注册
  - DDLCompiler 为单列整数主键补齐 IDENTITY(1, 1)
  - build_engine_options / build_uri 的 dm 分支
  - 驱动缺失 / 方言缺失 / 认证失败 / 连接拒绝的中文提示
  - switch_engine 按新 URI 注册方言并重建参数
  - 备份/恢复 dexp/dimp 命令构造与工具路径解析
  - 初始化向导 dm 选项与 _current_db_label
  - live 集成（ZHYCMS_TEST_DM_URL 门控，默认跳过）：连接、自增主键、
    全量迁移与 healthz

启用 live 集成（ZHYCMS_SECRET_KEY 须在进程启动前导出，因 SECRET_KEY 在导入时求值）：
    ZHYCMS_SECRET_KEY=dm-live \
    ZHYCMS_TEST_DM_URL=dm+dmPython://ZHYCMS:pwd@127.0.0.1:5236/ZHYCMS \
    ZHYCMS_DM_BIN=/opt/dmdbms/bin \
    pytest tests/test_dm.py -q
"""
import gzip
import importlib.util
import json
import os
import types

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.dialects import registry
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateTable

from app.config import build_engine_options
from app.utils import backup_utils, dbconfig
import app.utils.dialects.dm as dm_dialect

DM_URL = os.environ.get('ZHYCMS_TEST_DM_URL', '').strip()
requires_dm = pytest.mark.skipif(not DM_URL, reason='未设置 ZHYCMS_TEST_DM_URL')
HAS_DM_PKG = (importlib.util.find_spec('dmSQLAlchemy') is not None
              and importlib.util.find_spec('dmPython') is not None)
requires_dm_pkg = pytest.mark.skipif(
    not HAS_DM_PKG, reason='未安装 dmpython/dmSQLAlchemy（requirements-dm.txt）')


# ============================================================
# 方言注册与 Alembic impl
# ============================================================
@requires_dm_pkg
class TestDialectRegistration:
    def test_register_returns_installed(self):
        assert dm_dialect.register_dm_dialect() == 'installed'

    def test_register_idempotent(self):
        dm_dialect.register_dm_dialect()
        dm_dialect.register_dm_dialect()  # 重复注册不抛异常

    @requires_dm_pkg
    def test_dialect_registered(self):
        dm_dialect.register_dm_dialect()
        cls = registry.load('dm')
        assert cls is dm_dialect.ZHDMDialect
        assert cls.name == 'dm'
        assert registry.load('dm.dmPython') is cls

    def test_alembic_impl_registered(self):
        dm_dialect.register_dm_dialect()
        from alembic.ddl.impl import DefaultImpl

        class _FakeDialect:
            name = 'dm'

        impl = DefaultImpl.get_by_dialect(_FakeDialect())
        assert impl.__dialect__ == 'dm'


# ============================================================
# DDL：整数主键自增
# ============================================================
@requires_dm_pkg
class TestDDLCompiler:
    def _compile(self, table):
        dialect = dm_dialect.ZHDMDialect()
        return str(CreateTable(table).compile(dialect=dialect))

    def test_single_integer_pk_gets_identity(self):
        t = Table('t_dm_pk', MetaData(),
                  Column('id', Integer, primary_key=True),
                  Column('name', String(20)))
        assert 'IDENTITY(1, 1)' in self._compile(t)

    def test_composite_pk_has_no_identity(self):
        t = Table('t_dm_composite', MetaData(),
                  Column('a', Integer, primary_key=True),
                  Column('b', Integer, primary_key=True))
        assert 'IDENTITY' not in self._compile(t)

    def test_string_pk_has_no_identity(self):
        t = Table('t_dm_strpk', MetaData(),
                  Column('code', String(20), primary_key=True))
        assert 'IDENTITY' not in self._compile(t)

    def test_non_pk_integer_has_no_identity(self):
        t = Table('t_dm_plain', MetaData(),
                  Column('id', Integer, primary_key=True),
                  Column('qty', Integer))
        sql = self._compile(t)
        assert sql.count('IDENTITY(1, 1)') == 1


# ============================================================
# 引擎参数
# ============================================================
class TestBuildEngineOptions:
    def test_dm_pool_and_connect_args(self):
        opts = build_engine_options(
            'dm+dmPython://SYSDBA:pwd@127.0.0.1:5236/ZHYCMS')
        assert opts['pool_pre_ping'] is True
        assert opts['pool_size'] == 10
        assert opts['max_overflow'] == 20
        assert opts['pool_recycle'] == 1800
        assert opts['pool_timeout'] == 30
        assert opts['connect_args'] == {'connection_timeout': 5}

    def test_dm_does_not_use_pg_connect_args(self):
        opts = build_engine_options('dm+dmPython://u:p@localhost:5236/X')
        assert 'application_name' not in opts['connect_args']
        assert 'connect_timeout' not in opts['connect_args']


# ============================================================
# URI 构造
# ============================================================
class TestBuildUri:
    def test_dm_default_port(self):
        uri = dbconfig.build_uri('dm', '10.0.0.5', '', 'ZHYCMS', 'SYSDBA', 'p@ss')
        parsed = make_url(uri)
        assert parsed.drivername == 'dm+dmPython'
        assert parsed.host == '10.0.0.5'
        assert parsed.port == 5236
        assert parsed.database == 'ZHYCMS'
        assert parsed.password == 'p@ss'

    def test_dm_explicit_port(self):
        uri = dbconfig.build_uri('dm', '10.0.0.5', '5237', 'ZHYCMS', 'U', 'pw')
        assert make_url(uri).port == 5237

    def test_dm_no_charset_query(self):
        uri = dbconfig.build_uri('dm', '10.0.0.5', '', 'ZHYCMS', 'U', 'pw')
        assert make_url(uri).query == {}


# ============================================================
# 连接错误提示
# ============================================================
class TestConnectionHints:
    def test_missing_driver_message(self, monkeypatch):
        import sqlalchemy

        def _boom(*args, **kwargs):
            raise ModuleNotFoundError('No module named dmPython')

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        ok, msg = dbconfig.test_connection(
            'dm+dmPython://SYSDBA:pwd@127.0.0.1:5236/ZHYCMS')
        assert ok is False
        assert '达梦' in msg
        assert 'requirements-dm.txt' in msg

    def test_missing_dialect_message(self, monkeypatch):
        import sqlalchemy
        from sqlalchemy.exc import NoSuchModuleError

        def _boom(*args, **kwargs):
            raise NoSuchModuleError(
                "Can't load plugin: sqlalchemy.dialects:dm.dmPython")

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        ok, msg = dbconfig.test_connection(
            'dm+dmPython://SYSDBA:pwd@127.0.0.1:5236/ZHYCMS')
        assert ok is False
        assert 'dmSQLAlchemy' in msg

    def test_auth_failure_hint(self, monkeypatch):
        import sqlalchemy
        from sqlalchemy.exc import OperationalError

        def _boom(*args, **kwargs):
            raise OperationalError('SELECT 1', {}, Exception('用户名或密码错误'))

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        ok, msg = dbconfig.test_connection(
            'dm+dmPython://SYSDBA:pwd@127.0.0.1:5236/ZHYCMS')
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
            'dm+dmPython://SYSDBA:pwd@127.0.0.1:5236/ZHYCMS')
        assert ok is False
        assert '5236' in msg


# ============================================================
# switch_engine
# ============================================================
@requires_dm_pkg
class TestSwitchEngine:
    def test_switch_engine_rebuilds_dm_options(self, monkeypatch):
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

        uri = 'dm+dmPython://SYSDBA:pwd@127.0.0.1:5236/ZHYCMS'
        engine = dbconfig.switch_engine(app, fake_db, uri)

        assert isinstance(engine, _FakeEngine)
        assert app.config['ZHYCMS_DB_DIALECT'] == 'dm'
        assert app.config['SQLALCHEMY_ENGINE_OPTIONS']['pool_size'] == 10
        assert captured['url'] == uri
        assert captured['connect_args'] == {'connection_timeout': 5}


# ============================================================
# 备份目标解析
# ============================================================
class TestBackupTargetParsing:
    def _parse(self, app, monkeypatch, uri):
        with app.app_context():
            monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', uri)
            return backup_utils._db_type_and_path()

    def test_dm_uri(self, app, monkeypatch):
        db_type, dbname, host, port, user, pwd = self._parse(
            app, monkeypatch,
            'dm+dmPython://SYSDBA:Zhycms%4012345@127.0.0.1:5236/ZHYCMS')
        assert (db_type, dbname, host, port, user, pwd) == (
            'dm', 'ZHYCMS', '127.0.0.1', 5236, 'SYSDBA', 'Zhycms@12345')


# ============================================================
# 工具路径
# ============================================================
class TestBinTool:
    def test_dm_bin_env(self, monkeypatch, tmp_path):
        tool = tmp_path / 'dexp'
        tool.write_text('')
        monkeypatch.setenv('ZHYCMS_DB_DUMP_BIN', '')
        monkeypatch.setenv('ZHYCMS_DM_BIN', str(tmp_path))
        assert backup_utils._bin_tool('dexp', 'dm') == str(tool)

    def test_dm_home_bin_subdir(self, monkeypatch, tmp_path):
        (tmp_path / 'bin').mkdir()
        tool = tmp_path / 'bin' / 'dimp'
        tool.write_text('')
        monkeypatch.setenv('ZHYCMS_DB_DUMP_BIN', '')
        monkeypatch.delenv('ZHYCMS_DM_BIN', raising=False)
        monkeypatch.setenv('DM_HOME', str(tmp_path))
        assert backup_utils._bin_tool('dimp', 'dm') == str(tool)


# ============================================================
# 备份/恢复命令构造
# ============================================================
class _FakeProc:
    returncode = 0

    def communicate(self, timeout=None):
        return b'', b''


class TestBackupCommands:
    def test_backup_dm_command(self, monkeypatch, tmp_path):
        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured['cmd'] = cmd
            for arg in cmd:
                if arg.startswith('FILE='):
                    with open(arg[5:], 'wb') as f:
                        f.write(b'DMDUMP')
            return _FakeProc()

        monkeypatch.setattr(backup_utils.subprocess, 'Popen', _fake_popen)
        monkeypatch.setattr(backup_utils, '_bin_tool',
                            lambda name, db_type=None: name)
        monkeypatch.setattr(backup_utils.shutil, 'which',
                            lambda name: f'/opt/dmdbms/bin/{name}')

        dest = tmp_path / 'zhycms_dm_20260101_000000.dmp.gz'
        ok = backup_utils._backup_dm(
            str(dest), 'ZHYCMS', '127.0.0.1', 5236, 'SYSDBA', 'pwd')

        assert ok is True
        with gzip.open(dest, 'rb') as f:
            assert f.read() == b'DMDUMP'
        cmd = captured['cmd']
        assert cmd[0] == 'dexp'
        assert 'USERID=SYSDBA/pwd@127.0.0.1:5236' in cmd
        assert 'SCHEMAS=ZHYCMS' in cmd

    def test_backup_dm_missing_tool(self, monkeypatch, tmp_path):
        monkeypatch.setattr(backup_utils, '_bin_tool',
                            lambda name, db_type=None: name)
        monkeypatch.setattr(backup_utils.shutil, 'which', lambda name: None)
        with pytest.raises(RuntimeError) as ei:
            backup_utils._backup_dm(
                str(tmp_path / 'x.dmp.gz'), 'ZHYCMS',
                '127.0.0.1', 5236, 'SYSDBA', 'pwd')
        assert 'dexp' in str(ei.value)


class TestRestoreCommands:
    def test_restore_dm_command(self, app, monkeypatch, tmp_path):
        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured['cmd'] = cmd
            return _FakeProc()

        monkeypatch.setattr(backup_utils.subprocess, 'Popen', _fake_popen)
        monkeypatch.setattr(backup_utils, '_bin_tool',
                            lambda name, db_type=None: name)
        monkeypatch.setattr(backup_utils.shutil, 'which',
                            lambda name: f'/opt/dmdbms/bin/{name}')
        monkeypatch.setattr(backup_utils, '_db_type_and_path',
                            lambda: ('dm', 'ZHYCMS', '127.0.0.1',
                                     5236, 'SYSDBA', 'pwd'))

        gz_path = tmp_path / 'zhycms_dm_restore.dmp.gz'
        with gzip.open(gz_path, 'wb') as f:
            f.write(b'DMDUMP')

        with app.app_context():
            ok, msg = backup_utils._restore_dm(str(gz_path))

        assert ok is True
        assert msg == '达梦 DM8 恢复成功'
        cmd = captured['cmd']
        assert cmd[0] == 'dimp'
        assert 'USERID=SYSDBA/pwd@127.0.0.1:5236' in cmd
        assert 'SCHEMAS=ZHYCMS' in cmd


# ============================================================
# 向导与显示标签
# ============================================================
def test_current_db_label_dm(app):
    from app.admin.auth import _current_db_label

    original = app.config['SQLALCHEMY_DATABASE_URI']
    with app.app_context():
        app.config['SQLALCHEMY_DATABASE_URI'] = (
            'dm+dmPython://SYSDBA:pwd@127.0.0.1:5236/ZHYCMS')
        try:
            assert _current_db_label() == '达梦 DM8'
        finally:
            app.config['SQLALCHEMY_DATABASE_URI'] = original


def test_setup_accepts_dm(app, client, monkeypatch):
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
        'username': 'dmadmin',
        'nickname': 'DM Admin',
        'password': 'Abcdef123456!',
        'password_confirm': 'Abcdef123456!',
        'demo_type': 'none',
        'db_type': 'dm',
        'db_host': '127.0.0.1',
        'db_port': '',
        'db_name': 'ZHYCMS',
        'db_user': 'SYSDBA',
        'db_password': 'Dm12345678',
    })

    assert resp.status_code == 302
    assert saved['db_type'] == 'dm'
    assert saved['uri'].startswith('dm+dmPython://')
    assert saved['meta']['port'] == 5236  # 未填端口时回退默认 5236


# ============================================================
# live 集成（ZHYCMS_TEST_DM_URL 门控，默认跳过）
# ============================================================
@requires_dm
@requires_dm_pkg
class TestDMLive:
    def test_connect_and_select(self):
        from sqlalchemy import create_engine, text

        dm_dialect.register_dm_dialect()
        engine = create_engine(DM_URL, pool_pre_ping=True)
        try:
            assert engine.dialect.name == 'dm'
            with engine.connect() as conn:
                assert conn.execute(text('SELECT 1')).scalar() == 1
        finally:
            engine.dispose()

    def test_identity_autoincrement(self):
        from sqlalchemy import create_engine, select

        dm_dialect.register_dm_dialect()
        engine = create_engine(DM_URL)
        meta = MetaData()
        t = Table('t_dm_live_identity', meta,
                  Column('id', Integer, primary_key=True),
                  Column('name', String(20)))
        try:
            meta.create_all(engine)
            with engine.begin() as conn:
                conn.execute(t.insert().values(name='first'))
                rid = conn.execute(select(t.c.id)).scalar()
            assert rid == 1
        finally:
            with engine.begin() as conn:
                t.drop(conn, checkfirst=True)
            engine.dispose()

    def test_test_connection_ok(self):
        ok, msg = dbconfig.test_connection(DM_URL)
        assert ok is True, msg

    def test_full_migration_and_healthz(self, monkeypatch):
        from app.config import Config as _AppConfig
        from app import create_app
        from app.extensions import db

        # SQLALCHEMY_DATABASE_URI 与 SECRET_KEY 均在 Config 类导入时求值，
        # 运行期改 os.environ 无效，需直接覆盖类属性（from_object 会读取）。
        monkeypatch.setattr(_AppConfig, 'SQLALCHEMY_DATABASE_URI', DM_URL)
        dm_app = create_app('production')
        try:
            assert dm_app.config['ZHYCMS_DB_DIALECT'] == 'dm'
            with dm_app.app_context():
                from sqlalchemy import text
                rev = db.session.execute(
                    text('SELECT version_num FROM alembic_version')).scalar()
                tables = db.session.execute(
                    text('SELECT count(*) FROM user_tables')).scalar()
            assert rev == '0020'
            assert tables >= 40
            client = dm_app.test_client()
            resp = client.get('/healthz?detail=1')
            assert resp.status_code == 200
            assert json.loads(resp.get_data(as_text=True))['db_dialect'] == 'dm'
        finally:
            with dm_app.app_context():
                db.session.remove()
                db.engine.dispose()
