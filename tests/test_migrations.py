"""Alembic 迁移测试（v2.6.2 W3）。

迁移链设计契约（见 migrations/versions/0001 docstring 与 create_app bootstrap）：
  Alembic 在「schema 已成型」的库上运行——新装/旧库均先 db.create_all()
  建齐核心+插件表，再 stamp baseline 0001、执行增量（0002+，全部带
  表/列存在性守卫，幂等可重放）。

本测试按该契约模拟（不依赖 Flask 上下文，独立临时 SQLite 库）：
- create_all → stamp 0001 → upgrade heads（生产 bootstrap 等价路径）
- 重复 upgrade 幂等
- downgrade 0001 → 再 upgrade heads 往返
- 逐级 -1 降级
- 版本图：单 head、0001→0007 线性链
"""
import os

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

migration = pytest.mark.migration

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(ROOT, 'migrations')

CORE_TABLES = {
    'users', 'articles', 'columns', 'settings', 'roles', 'permissions',
    'uploaded_files',
}
I18N_TABLES = {
    'article_translations', 'column_translations', 'fragment_translations',
}


def _cfg(db_path):
    cfg = Config()
    cfg.set_main_option('script_location', MIGRATIONS_DIR)
    cfg.set_main_option('sqlalchemy.url', f'sqlite:///{db_path}')
    return cfg


def _metadata_create_all(db_path):
    """生产契约的第一步：db.create_all() 等价操作（独立引擎）。"""
    from app.extensions import db
    from app import models  # noqa: F401  确保核心+插件模型全部进入 metadata
    engine = create_engine(f'sqlite:///{db_path}')
    db.metadata.create_all(engine)
    return engine


def _inspector(db_path):
    return inspect(create_engine(f'sqlite:///{db_path}'))


def _current_version(db_path):
    with create_engine(f'sqlite:///{db_path}').connect() as conn:
        row = conn.execute(text('SELECT version_num FROM alembic_version')).fetchone()
    return row[0] if row else None


def _bootstrap_like_production(db_path):
    """等价 create_app 的 _alembic_bootstrap（旧库分支）。"""
    engine = _metadata_create_all(db_path)
    engine.dispose()
    cfg = _cfg(db_path)
    command.stamp(cfg, '0001')
    command.upgrade(cfg, 'heads')
    return cfg


@migration
class TestUpgrade:
    """create_all → stamp → upgrade heads（生产 bootstrap 等价）。"""

    def test_upgrade_head_reaches_head(self, tmp_path):
        db = str(tmp_path / 'mig.db')
        cfg = _bootstrap_like_production(db)
        head = ScriptDirectory.from_config(cfg).get_current_head()
        assert _current_version(db) == head

    def test_core_tables_present(self, tmp_path):
        db = str(tmp_path / 'mig.db')
        _bootstrap_like_production(db)
        tables = set(_inspector(db).get_table_names())
        assert CORE_TABLES <= tables, f'核心表缺失: {CORE_TABLES - tables}'

    def test_seed_settings_applied(self, tmp_path):
        """0003 的搜索设置种子与 0004 的 storage_driver 设置已写入。"""
        db = str(tmp_path / 'mig.db')
        _bootstrap_like_production(db)
        with create_engine(f'sqlite:///{db}').connect() as conn:
            keys = {row[0] for row in conn.execute(text('SELECT key FROM settings'))}
        assert 'storage_driver' in keys
        assert {'search_engine', 'search_index_on_save'} <= keys

    def test_upgrade_is_idempotent(self, tmp_path):
        db = str(tmp_path / 'mig.db')
        cfg = _bootstrap_like_production(db)
        head = ScriptDirectory.from_config(cfg).get_current_head()
        # 二次执行：守卫跳过已存在结构，版本不变、不报错
        command.upgrade(cfg, 'heads')
        assert _current_version(db) == head


@migration
class TestDowngrade:
    """heads → 0001 → heads 往返与逐级降级。"""

    def test_downgrade_to_baseline_reverts_incremental(self, tmp_path):
        db = str(tmp_path / 'mig.db')
        cfg = _bootstrap_like_production(db)
        command.downgrade(cfg, '0001')

        tables = set(_inspector(db).get_table_names())
        # 0005/0006 的 i18n 增量表被回退删除
        assert not (I18N_TABLES & tables), 'i18n 增量表未回退'
        # baseline 核心表保留（0001 不支持降级）
        assert CORE_TABLES <= tables
        assert _current_version(db) == '0001'

    def test_reupgrade_after_downgrade_restores(self, tmp_path):
        db = str(tmp_path / 'mig.db')
        cfg = _bootstrap_like_production(db)
        command.downgrade(cfg, '0001')
        command.upgrade(cfg, 'heads')

        head = ScriptDirectory.from_config(cfg).get_current_head()
        assert _current_version(db) == head
        assert I18N_TABLES <= set(_inspector(db).get_table_names())

    def test_stepwise_downgrade_one_step(self, tmp_path):
        """逐级 -1（0007 → 0006）后可再次升级回 head。"""
        db = str(tmp_path / 'mig.db')
        cfg = _bootstrap_like_production(db)
        command.downgrade(cfg, '-1')
        assert _current_version(db) == '0006'
        command.upgrade(cfg, 'heads')
        head = ScriptDirectory.from_config(cfg).get_current_head()
        assert _current_version(db) == head


@migration
class TestRevisionGraph:
    """版本链健康：单 head、线性无分叉。"""

    def test_single_head(self):
        script = ScriptDirectory.from_config(_cfg('unused.db'))
        heads = script.get_heads()
        assert len(heads) == 1, f'存在多个迁移 head: {heads}'

    def test_linear_chain_from_baseline(self):
        """walk_revisions 自 head 向 base 回溯：0007 → … → 0001。"""
        script = ScriptDirectory.from_config(_cfg('unused.db'))
        objs = list(script.walk_revisions('base', 'heads'))
        assert objs[0].revision.startswith('0007')
        assert objs[-1].revision.startswith('0001')
        assert len(objs) == 7
        ordered = list(reversed(objs))  # base → head
        for i, rev in enumerate(ordered):
            assert (rev.down_revision is None) if i == 0 \
                else (rev.down_revision == ordered[i - 1].revision)
