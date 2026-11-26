"""v3.3.1 信创适配：KingbaseES（人大金仓）连接层单元测试。

覆盖：
  - 方言版本串解析（SHOW server_version / server_version_num）
  - 方言注册幂等与 Alembic DDL 实现登记
  - build_engine_options 按后端选择连接池参数
  - build_uri 的 kingbase 与 Unix socket 形态
  - 驱动缺失 / 认证失败 / 连接拒绝的可操作中文提示
  - switch_engine 按新 URI 重建参数并注册方言
  - 备份/恢复的 kingbase 分支与工具路径解析、KINGBASE_PASSWORD 注入
  - 初始化向导 kingbase 选项与 _current_db_label
  - live 集成（ZHYCMS_TEST_KINGBASE_URL 门控，默认跳过）：全量迁移、
    healthz db_dialect、备份产物校验

启用 live 集成（ZHYCMS_SECRET_KEY 须在进程启动前导出，因 SECRET_KEY 在导入时求值）：
    ZHYCMS_SECRET_KEY=kb-live \
    ZHYCMS_TEST_KINGBASE_URL=kingbase+psycopg2://system:pwd@127.0.0.1:54321/zhycms_test \
    ZHYCMS_KINGBASE_BIN=/opt/kingbase/bin \
    LD_LIBRARY_PATH=/opt/kingbase/lib \
    pytest tests/test_kingbase.py -q
"""
import gzip
import json
import os
import types

import pytest
from sqlalchemy.dialects import registry
from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2
from sqlalchemy.engine import make_url

from app.config import build_engine_options
from app.utils import backup_utils, dbconfig
from app.utils.dialects.kingbase import (
    _KINGBASE_VERSION_RE,
    KingbaseDialect,
    register_kingbase_dialect,
)

KINGBASE_URL = os.environ.get('ZHYCMS_TEST_KINGBASE_URL', '').strip()
requires_kingbase = pytest.mark.skipif(
    not KINGBASE_URL, reason='未设置 ZHYCMS_TEST_KINGBASE_URL')


# ============================================================
# 方言版本解析
# ============================================================
class TestDialectVersion:
    def test_version_regex(self):
        m = _KINGBASE_VERSION_RE.match('12.1')
        assert m is not None
        assert tuple(g for g in m.groups() if g) == ('12', '1')

    def test_version_regex_three_part(self):
        m = _KINGBASE_VERSION_RE.match('12.1.3')
        assert tuple(g for g in m.groups() if g) == ('12', '1', '3')

    @staticmethod
    def _conn(mapping):
        class _Scalar:
            def __init__(self, v):
                self._v = v

            def scalar(self):
                return self._v

        class _Conn:
            def __init__(self, m):
                self._m = m

            def exec_driver_sql(self, sql):
                return _Scalar(self._m.get(sql))

        return _Conn(mapping)

    def test_parse_server_version(self):
        d = KingbaseDialect()
        info = d._get_server_version_info(self._conn(
            {'SHOW server_version': '12.1', 'SHOW server_version_num': '120001'}))
        assert info == (12, 1)

    def test_fallback_server_version_num(self):
        d = KingbaseDialect()
        info = d._get_server_version_info(self._conn(
            {'SHOW server_version': '', 'SHOW server_version_num': '120001'}))
        assert info == (12, 1)

    def test_ultimate_fallback(self):
        d = KingbaseDialect()
        assert d._get_server_version_info(self._conn({})) == (12, 1)


# ============================================================
# 方言注册与 Alembic impl
# ============================================================
class TestDialectRegistration:
    def test_register_idempotent(self):
        assert register_kingbase_dialect() == 'builtin'
        register_kingbase_dialect()  # 重复注册不抛异常
        cls = registry.load('kingbase')
        assert issubclass(cls, PGDialect_psycopg2)
        assert cls.name == 'kingbase'

    def test_psycopg2_variant_registered(self):
        register_kingbase_dialect()
        assert registry.load('kingbase.psycopg2') is KingbaseDialect

    def test_alembic_impl_registered(self):
        register_kingbase_dialect()
        from alembic.ddl.impl import DefaultImpl

        class _FakeDialect:
            name = 'kingbase'

        impl = DefaultImpl.get_by_dialect(_FakeDialect())
        assert impl.__dialect__ == 'kingbase'


# ============================================================
# 引擎参数
# ============================================================
class TestBuildEngineOptions:
    def test_kingbase_pool_and_connect_args(self):
        opts = build_engine_options(
            'kingbase+psycopg2://u:p@127.0.0.1:54321/zhycms')
        assert opts['pool_pre_ping'] is True
        assert opts['pool_size'] == 10
        assert opts['max_overflow'] == 20
        assert opts['pool_recycle'] == 1800
        assert opts['pool_timeout'] == 30
        assert opts['connect_args'] == {
            'connect_timeout': 5,
            'application_name': 'zhycms',
        }

    def test_sqlite_keeps_default(self):
        assert build_engine_options('sqlite:///tmp.db') == {'pool_pre_ping': True}


# ============================================================
# URI 构造
# ============================================================
class TestBuildUri:
    def test_kingbase_default_port(self):
        uri = dbconfig.build_uri(
            'kingbase', '10.0.0.5', '', 'zhycms', 'system', 'p@ss')
        parsed = make_url(uri)
        assert parsed.drivername == 'kingbase+psycopg2'
        assert parsed.host == '10.0.0.5'
        assert parsed.port == 54321
        assert parsed.password == 'p@ss'

    def test_kingbase_explicit_port(self):
        uri = dbconfig.build_uri(
            'kingbase', '10.0.0.5', '54322', 'zhycms', 'system', 'pw')
        assert make_url(uri).port == 54322

    def test_kingbase_socket(self):
        uri = dbconfig.build_uri(
            'kingbase', '/var/run/kingbase', '', 'zhycms', 'u', 'p')
        parsed = make_url(uri)
        assert parsed.host is None
        assert parsed.port is None
        assert parsed.query['host'] == '/var/run/kingbase'


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
            'kingbase+psycopg2://u:p@127.0.0.1:54321/zhycms')
        assert ok is False
        assert 'KingbaseES' in msg
        assert 'psycopg2-binary' in msg

    def test_auth_failure_hint(self, monkeypatch):
        import sqlalchemy
        from sqlalchemy.exc import OperationalError

        def _boom(*args, **kwargs):
            raise OperationalError(
                'SELECT 1', {}, Exception('fe_sendauth: no password supplied'))

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        ok, msg = dbconfig.test_connection(
            'kingbase+psycopg2://u:p@127.0.0.1:54321/zhycms')
        assert ok is False
        assert 'KingbaseES' in msg
        assert '认证' in msg

    def test_connection_refused_hint(self, monkeypatch):
        import sqlalchemy
        from sqlalchemy.exc import OperationalError

        def _boom(*args, **kwargs):
            raise OperationalError(
                'SELECT 1', {},
                Exception('could not connect to server: Connection refused'))

        monkeypatch.setattr(sqlalchemy, 'create_engine', _boom)
        ok, msg = dbconfig.test_connection(
            'kingbase+psycopg2://u:p@127.0.0.1:54321/zhycms')
        assert ok is False
        assert 'KingbaseES' in msg
        assert '54321' in msg


# ============================================================
# switch_engine
# ============================================================
class TestSwitchEngine:
    def test_switch_engine_rebuilds_kingbase_options(self, monkeypatch):
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

        uri = 'kingbase+psycopg2://u:p@127.0.0.1:54321/zhycms'
        engine = dbconfig.switch_engine(app, fake_db, uri)

        assert isinstance(engine, _FakeEngine)
        assert app.config['ZHYCMS_DB_DIALECT'] == 'kingbase'
        assert app.config['SQLALCHEMY_ENGINE_OPTIONS']['pool_size'] == 10
        assert captured['url'] == uri
        assert captured['connect_args']['application_name'] == 'zhycms'


# ============================================================
# 备份目标解析
# ============================================================
class TestBackupTargetParsing:
    def _parse(self, app, monkeypatch, uri):
        with app.app_context():
            monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', uri)
            return backup_utils._db_type_and_path()

    def test_kingbase_uri(self, app, monkeypatch):
        db_type, dbname, host, port, user, pwd = self._parse(
            app, monkeypatch,
            'kingbase+psycopg2://system:Zhycms%4012345@127.0.0.1:54321/zhycms')
        assert (db_type, dbname, host, port, user, pwd) == (
            'kingbase', 'zhycms', '127.0.0.1', 54321, 'system', 'Zhycms@12345')

    def test_kingbase_socket_host_in_query(self, app, monkeypatch):
        uri = dbconfig.build_uri(
            'kingbase', '/var/run/kingbase', '', 'zhycms', 'u', 'p')
        db_type, dbname, host, port, *_ = self._parse(app, monkeypatch, uri)
        assert db_type == 'kingbase'
        assert host == '/var/run/kingbase'
        assert port is None


# ============================================================
# 工具路径与 env
# ============================================================
class TestBinTool:
    def test_kingbase_bin_env(self, monkeypatch, tmp_path):
        tool = tmp_path / 'ksql'
        tool.write_text('')
        monkeypatch.setenv('ZHYCMS_DB_DUMP_BIN', '')
        monkeypatch.setenv('ZHYCMS_KINGBASE_BIN', str(tmp_path))
        assert backup_utils._bin_tool('ksql', 'kingbase') == str(tool)

    def test_kingbase_bin_fallback_var(self, monkeypatch, tmp_path):
        tool = tmp_path / 'sys_dump'
        tool.write_text('')
        monkeypatch.setenv('ZHYCMS_DB_DUMP_BIN', '')
        monkeypatch.delenv('ZHYCMS_KINGBASE_BIN', raising=False)
        monkeypatch.setenv('KINGBASE_BIN', str(tmp_path))
        assert backup_utils._bin_tool('sys_dump', 'kingbase') == str(tool)


class TestToolEnv:
    def test_kingbase_uses_kingbase_password(self, monkeypatch):
        monkeypatch.delenv('PGPASSWORD', raising=False)
        monkeypatch.delenv('KINGBASE_PASSWORD', raising=False)
        env = backup_utils._tool_env('kingbase', 'S3cr3t')
        assert env['KINGBASE_PASSWORD'] == 'S3cr3t'
        assert 'PGPASSWORD' not in env
        # KingbaseES 无需 LD_LIBRARY_PATH（与 openGauss 不同）
        assert not env.get('LD_LIBRARY_PATH', '').startswith('/usr/local/opengauss')

    def test_postgresql_still_uses_pgpassword(self, monkeypatch):
        monkeypatch.delenv('PGPASSWORD', raising=False)
        env = backup_utils._tool_env('postgresql', 'S3cr3t')
        assert env['PGPASSWORD'] == 'S3cr3t'
        assert 'KINGBASE_PASSWORD' not in env


# ============================================================
# 备份/恢复命令构造
# ============================================================
class TestBackupCommands:
    def test_backup_kingbase_command(self, monkeypatch, tmp_path):
        captured = {}

        def _fake_run(cmd, dest_path, env=None, fallback_json=False):
            captured.update(cmd=cmd, env=env)
            return True

        monkeypatch.setattr(backup_utils, '_run_dump_with_gzip', _fake_run)
        monkeypatch.setattr(
            backup_utils, '_bin_tool',
            lambda name, db_type=None: f'/opt/kingbase/bin/{name}')

        ok = backup_utils._backup_pg(
            str(tmp_path / 'zhycms_kingbase.sql.gz'), 'zhycms',
            '127.0.0.1', 54321, 'system', 'S3cr3t', db_type='kingbase')

        assert ok is True
        cmd = captured['cmd']
        assert cmd[0] == '/opt/kingbase/bin/sys_dump'
        assert '--host=127.0.0.1' in cmd
        assert '--port=54321' in cmd
        assert '--username=system' in cmd
        assert '--no-password' in cmd
        assert cmd[-1] == 'zhycms'  # 库名作为位置参数
        assert 'S3cr3t' not in cmd  # 密码不在命令行明文
        assert captured['env']['KINGBASE_PASSWORD'] == 'S3cr3t'
        assert 'PGPASSWORD' not in captured['env']


class TestRestoreCommands:
    def test_restore_kingbase_command(self, app, monkeypatch, tmp_path):
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
            lambda name, db_type=None: f'/opt/kingbase/bin/{name}')
        monkeypatch.setattr(backup_utils, '_db_type_and_path',
                            lambda: ('kingbase', 'zhycms', '127.0.0.1',
                                     54321, 'system', 'pw'))

        gz_path = tmp_path / 'zhycms_kingbase.sql.gz'
        with gzip.open(gz_path, 'wb') as f:
            f.write(b'SELECT 1;\n')

        with app.app_context():
            ok, msg = backup_utils._restore_pg(str(gz_path))

        assert ok is True
        assert msg == 'KingbaseES 恢复成功'
        cmd = captured['cmd']
        assert cmd[0] == '/opt/kingbase/bin/ksql'
        assert '--port=54321' in cmd
        assert '-w' in cmd
        assert '-d' in cmd
        assert cmd[cmd.index('-d') + 1] == 'zhycms'
        assert '-f' in cmd
        assert 'pw' not in cmd
        assert captured['env']['KINGBASE_PASSWORD'] == 'pw'


# ============================================================
# 向导与显示标签
# ============================================================
def test_current_db_label_kingbase(app):
    from app.admin.auth import _current_db_label

    original = app.config['SQLALCHEMY_DATABASE_URI']
    with app.app_context():
        app.config['SQLALCHEMY_DATABASE_URI'] = (
            'kingbase+psycopg2://u:p@127.0.0.1:54321/zhycms')
        try:
            assert _current_db_label() == 'KingbaseES'
        finally:
            app.config['SQLALCHEMY_DATABASE_URI'] = original


def test_setup_accepts_kingbase(app, client, monkeypatch):
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
        'username': 'kbadmin',
        'nickname': 'Kingbase Admin',
        'password': 'Abcdef123456!',
        'password_confirm': 'Abcdef123456!',
        'demo_type': 'none',
        'db_type': 'kingbase',
        'db_host': '127.0.0.1',
        'db_port': '',
        'db_name': 'zhycms',
        'db_user': 'system',
        'db_password': 'Kingbase123',
    })

    assert resp.status_code == 302
    assert saved['db_type'] == 'kingbase'
    assert saved['uri'].startswith('kingbase+psycopg2://')
    assert saved['meta']['port'] == 54321  # 未填端口时回退默认 54321


# ============================================================
# live 集成（ZHYCMS_TEST_KINGBASE_URL 门控，默认跳过）
# ============================================================
def _kingbase_tools_available():
    if os.environ.get('ZHYCMS_KINGBASE_BIN'):
        return os.path.isdir(os.environ['ZHYCMS_KINGBASE_BIN'])
    import shutil
    return bool(shutil.which('sys_dump') and shutil.which('ksql'))


@requires_kingbase
class TestKingbaseLive:
    def test_dialect_and_server_version(self):
        from sqlalchemy import create_engine, text

        register_kingbase_dialect()
        engine = create_engine(KINGBASE_URL, pool_pre_ping=True)
        assert engine.dialect.name == 'kingbase'
        with engine.connect() as conn:
            version = str(conn.execute(text('select version()')).scalar())
        assert 'kingbase' in version.lower()
        engine.dispose()

    def test_full_migration_and_healthz(self, monkeypatch):
        from app.config import Config as _AppConfig
        from app import create_app
        from app.extensions import db

        # SQLALCHEMY_DATABASE_URI 与 SECRET_KEY 均在 Config 类导入时求值，
        # 运行期改 os.environ 无效，需直接覆盖类属性（from_object 会读取）。
        monkeypatch.setattr(
            _AppConfig, 'SQLALCHEMY_DATABASE_URI', KINGBASE_URL)
        kb_app = create_app('production')
        try:
            assert kb_app.config['ZHYCMS_DB_DIALECT'] == 'kingbase'
            with kb_app.app_context():
                from sqlalchemy import text
                rev = db.session.execute(
                    text('SELECT version_num FROM alembic_version')).scalar()
                tables = db.session.execute(text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='public'")).scalar()
            assert rev == '0020'
            assert tables >= 40
            client = kb_app.test_client()
            resp = client.get('/healthz?detail=1')
            assert resp.status_code == 200
            assert json.loads(resp.get_data(as_text=True))['db_dialect'] == 'kingbase'
        finally:
            with kb_app.app_context():
                db.session.remove()
                db.engine.dispose()

    @pytest.mark.skipif(
        not _kingbase_tools_available(),
        reason='未找到 sys_dump/ksql（设置 ZHYCMS_KINGBASE_BIN 并确保 LD_LIBRARY_PATH）')
    def test_backup_produces_kingbase_dump(self, monkeypatch):
        from app.config import Config as _AppConfig
        from app import create_app
        from app.extensions import db

        monkeypatch.setattr(
            _AppConfig, 'SQLALCHEMY_DATABASE_URI', KINGBASE_URL)
        kb_app = create_app('production')
        abs_path = None
        try:
            with kb_app.app_context():
                rec, err = backup_utils.create_backup()
                assert rec is not None, f'backup failed: {err}'
                # 在会话内读取路径，避免退出上下文后 DetachedInstanceError
                abs_path = rec.abs_path
            assert os.path.getsize(abs_path) > 0
            with gzip.open(abs_path, 'rt', encoding='utf-8',
                           errors='ignore') as f:
                head = f.read(300)
            assert 'Kingbase database dump' in head
        finally:
            with kb_app.app_context():
                db.session.remove()
                db.engine.dispose()
