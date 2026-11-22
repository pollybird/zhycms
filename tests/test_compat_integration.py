"""v3.3.0 信创适配：openGauss / openAMDC 集成测试（默认跳过）。

启用方式（未设置对应变量时相关用例 skip，不影响 SQLite 默认回归）：

    ZHYCMS_TEST_OPENAMDC_URL=redis://127.0.0.1:6379/0 \
    ZHYCMS_TEST_OPENGAUSS_URL=opengauss+psycopg2://gaussdb:pwd@127.0.0.1:5432/zhycms \
    pytest tests/test_compat_integration.py -q

CI 由 ``.github/workflows/compat.yml`` 设置上述变量后执行。
"""
import concurrent.futures
import os
import uuid

import pytest

from app.services import redis_backend

pytestmark = pytest.mark.integration

OPENAMDC_URL = os.environ.get('ZHYCMS_TEST_OPENAMDC_URL', '').strip()
OPENGAUSS_URL = os.environ.get('ZHYCMS_TEST_OPENGAUSS_URL', '').strip()

requires_openamdc = pytest.mark.skipif(
    not OPENAMDC_URL, reason='未设置 ZHYCMS_TEST_OPENAMDC_URL')
requires_opengauss = pytest.mark.skipif(
    not OPENGAUSS_URL, reason='未设置 ZHYCMS_TEST_OPENGAUSS_URL')


def _redis_client():
    import redis

    client = redis.from_url(
        OPENAMDC_URL, socket_connect_timeout=5, socket_timeout=5)
    client.ping()
    return client


def _key(name):
    return f'zhycms:compat:{name}:{uuid.uuid4().hex}'


def _opengauss_engine():
    from sqlalchemy import create_engine

    from app.utils.dialects import register_opengauss_dialect

    register_opengauss_dialect()
    return create_engine(OPENGAUSS_URL, pool_pre_ping=True)


@requires_openamdc
class TestOpenAMDC:
    def test_flavor_is_openamdc(self):
        meta = redis_backend.describe(_redis_client())
        assert meta['flavor'] == 'openamdc'
        assert meta['version']

    def test_cache_roundtrip_with_ttl(self):
        client = _redis_client()
        key = _key('roundtrip')
        try:
            assert client.set(key, 'v1', ex=30) is True
            assert client.get(key) == b'v1'
            assert 0 < client.ttl(key) <= 30
            assert client.delete(key) == 1
            assert client.get(key) is None
        finally:
            client.delete(key)

    def test_lua_incr_is_atomic(self):
        client = _redis_client()
        key = _key('lua')
        try:
            script = "return redis.call('INCR', KEYS[1])"
            results = [client.eval(script, 1, key) for _ in range(20)]
            assert sorted(results) == list(range(1, 21))
            assert int(client.get(key)) == 20
        finally:
            client.delete(key)

    def test_set_nx_single_owner_across_threads(self):
        client = _redis_client()
        key = _key('nx')

        def _acquire(_):
            return bool(client.set(key, '1', nx=True, ex=30))

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
                owners = list(pool.map(_acquire, range(200)))
            assert owners.count(True) == 1
        finally:
            client.delete(key)


@requires_opengauss
class TestOpenGauss:
    def test_dialect_and_server_version(self):
        from sqlalchemy import text

        engine = _opengauss_engine()
        assert engine.dialect.name == 'opengauss'
        with engine.connect() as conn:
            version = str(conn.execute(text('select version()')).scalar())
        assert 'opengauss' in version.lower()

    def test_temp_table_crud(self):
        from sqlalchemy import text

        engine = _opengauss_engine()
        # openGauss 不支持在临时表上创建 serial 列，这里不依赖自增。
        with engine.begin() as conn:
            conn.execute(text(
                'CREATE TEMP TABLE compat_probe (note varchar(32))'))
            conn.execute(text("INSERT INTO compat_probe (note) VALUES ('a')"))
            conn.execute(text("INSERT INTO compat_probe (note) VALUES ('b')"))
            rows = conn.execute(text(
                'SELECT note FROM compat_probe ORDER BY note')).scalars().all()
            assert rows == ['a', 'b']
            conn.execute(text('DELETE FROM compat_probe WHERE note = :n'),
                         {'n': 'a'})
            remaining = conn.execute(text(
                'SELECT count(*) FROM compat_probe')).scalar()
            assert remaining == 1
