"""v3.3.4：缓存按前缀批量清理。

背景：flask-caching 2.5 没有 delete_pattern，clear_content_cache 曾退化为
cache.clear()——Redis 下即 KEYS <prefix>* + 单条大 DEL，缓存键多时会阻塞
Redis 并占用大量内存，导致文章保存请求超过 gunicorn 超时（nginx 记录
upstream prematurely closed connection）。本文件锁定新的 SCAN 批量实现。
"""
import fnmatch

from app.extensions import cache


class _FakeRedisClient:
    def __init__(self, keys):
        self.store = set(keys)
        self.batches = []

    def scan_iter(self, match=None, count=None):
        for key in sorted(self.store):
            if match is None or fnmatch.fnmatch(str(key), match):
                yield key

    def delete(self, *keys):
        self.batches.append(list(keys))
        for key in keys:
            self.store.discard(key)
        return len(keys)


class _FakeBackend:
    key_prefix = 'zhycms:cache:'

    def __init__(self, keys):
        self._read_client = _FakeRedisClient(keys)

    def keys(self, *args, **kwargs):  # pragma: no cover - 被调用即失败
        raise AssertionError('不应使用阻塞的 KEYS 命令')


def test_purge_cache_prefix_scan_and_batch(app, monkeypatch):
    from app.utils.helpers import purge_cache_prefix
    keys = [f'zhycms:cache:frontend/site0/page/{i}' for i in range(1200)]
    keys += ['zhycms:cache:frontend/site1/page/0',
             'zhycms:cache:settings']
    backend = _FakeBackend(keys)
    monkeypatch.setattr(type(cache), 'cache', property(lambda self: backend))

    with app.app_context():
        deleted = purge_cache_prefix('frontend/site0/')

    assert deleted == 1200
    assert backend._read_client.store == {
        'zhycms:cache:frontend/site1/page/0',
        'zhycms:cache:settings',
    }
    # 每批最多 500，且不一次性大 DEL
    assert [len(batch) for batch in backend._read_client.batches] == [500, 500, 200]


def test_clear_content_cache_never_flushes_all(app, monkeypatch):
    """站点内容变更不再调用 cache.clear()（会波及其它站点与设置缓存）。"""
    from app.models.setting import Setting
    from app.utils.helpers import clear_content_cache

    def _boom():
        raise AssertionError('不应调用 cache.clear()')

    from app.extensions import db

    monkeypatch.setattr(cache, 'clear', _boom, raising=False)
    with app.app_context():
        old = Setting.get('cache_enable')
        Setting.set('cache_enable', 'on')
        db.session.commit()
        cache.set('frontend/site0/tmp-key', 'x')
        try:
            clear_content_cache()
            assert cache.get('frontend/site0/tmp-key') is None
        finally:
            Setting.set('cache_enable', old or 'off')
            db.session.commit()


def test_try_cache_ignores_unknown_query_args(app, client, monkeypatch):
    """随机查询参数（utm_* 等）不再生成独立缓存键。"""
    from app.extensions import db
    from app.models.setting import Setting

    captured = []
    monkeypatch.setattr(cache, 'get', lambda key, **kw: None)
    monkeypatch.setattr(cache, 'set',
                        lambda key, value, **kw: captured.append(key))
    with app.app_context():
        old = Setting.get('cache_enable')
        Setting.set('cache_enable', 'on')
        db.session.commit()
    try:
        resp1 = client.get('/?utm_source=a&utm_medium=x')
        resp2 = client.get('/?utm_source=b&utm_medium=y')
    finally:
        with app.app_context():
            Setting.set('cache_enable', old or 'off')
            db.session.commit()

    frontend_keys = {k for k in captured if 'frontend/site0/' in str(k)}
    assert len(frontend_keys) == 1, (resp1.status_code, resp2.status_code,
                                     captured)
