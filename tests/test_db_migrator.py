"""数据库迁移插件测试：迁移核心逻辑 + 后台路由门控。

迁移核心用 SQLite→SQLite 验证（目标 dialect 无序列重置，逻辑自动跳过）；
MySQL/PostgreSQL 目标需真实服务器，不纳入单测。
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy import inspect as sa_inspect

PLUGIN = 'db_migrator'


def _enable(app):
    from app.plugin_system import enable_plugin
    with app.app_context():
        err = enable_plugin(PLUGIN)
        assert err is None, f'启用插件失败: {err}'


def _target_uri(tmp_path):
    return 'sqlite:///' + str(tmp_path / 'target.db')


class TestMigrationCore:
    """run_migration 核心逻辑。"""

    def test_migrate_copies_all_tables(self, app, tmp_path):
        """迁移后目标库包含源库全部业务表，行数一致。"""
        from plugins.db_migrator.migrate import run_migration

        uri = _target_uri(tmp_path)
        with app.app_context():
            result = run_migration(uri)
            assert result['tables']
            assert result['total_rows'] == sum(t['rows'] for t in result['tables'])

        tgt = create_engine(uri)
        try:
            from app.extensions import db as _db
            with app.app_context():
                src_tables = set(sa_inspect(_db.engine).get_table_names())
            tgt_tables = set(sa_inspect(tgt).get_table_names())
            # alembic_version 为 Alembic 自管表，不随业务表复制，
            # 但版本号会同步到目标库（保证重启时不重复执行增量迁移）
            assert src_tables - {'alembic_version'} <= tgt_tables
            with app.app_context():
                with _db.engine.connect() as sc:
                    src_ver = sc.execute(
                        text('SELECT version_num FROM alembic_version')).scalar()
            with tgt.connect() as tc:
                tgt_ver = tc.execute(
                    text('SELECT version_num FROM alembic_version')).scalar()
            assert tgt_ver == src_ver

            # 抽查核心表行数一致
            from app.models.article import Article
            with app.app_context():
                n_src = Article.query.count()
            with tgt.connect() as tc:
                n_tgt = tc.execute(text('SELECT COUNT(*) FROM articles')).scalar()
            assert n_tgt == n_src
        finally:
            tgt.dispose()

    def test_rerun_rejected_when_target_not_empty(self, app, tmp_path):
        """目标库已有数据且未允许覆盖 → 拒绝并报 MigrationError。"""
        from plugins.db_migrator.migrate import run_migration, MigrationError

        uri = _target_uri(tmp_path)
        with app.app_context():
            run_migration(uri)
            with pytest.raises(MigrationError):
                run_migration(uri)

    def test_overwrite_rerun_no_duplicate(self, app, tmp_path):
        """覆盖重迁：行数不翻倍。"""
        from plugins.db_migrator.migrate import run_migration

        uri = _target_uri(tmp_path)
        with app.app_context():
            first = run_migration(uri)
            second = run_migration(uri, overwrite=True)
            assert second['total_rows'] == first['total_rows']


class TestDbMigratorRoutes:
    """后台路由：门控 404、页面 200、测试连接、迁移 HTTP 流程。"""

    def test_404_when_disabled(self, app, admin_client):
        """插件未启用时后台路由 404（不暴露存在性）。"""
        assert admin_client.get('/admin/db-migrator').status_code == 404

    def test_page_200_when_enabled(self, app, admin_client):
        _enable(app)
        resp = admin_client.get('/admin/db-migrator')
        assert resp.status_code == 200
        assert '数据库迁移'.encode() in resp.data

    def test_test_endpoint_unreachable(self, app, admin_client):
        """测试连接：目标库连不上时返回 ok=False 的 JSON。"""
        _enable(app)
        resp = admin_client.post('/admin/db-migrator/test', data={
            'db_type': 'mysql', 'host': '127.0.0.1', 'port': '1',
            'database': 'zhycms', 'user': 'u', 'password': 'p',
        })
        assert resp.status_code == 200
        assert resp.json['ok'] is False

    def test_test_endpoint_invalid_type(self, app, admin_client):
        """测试连接：不支持的类型返回 ok=False 的 JSON。"""
        _enable(app)
        resp = admin_client.post('/admin/db-migrator/test', data={
            'db_type': 'sqlite',
        })
        assert resp.status_code == 200
        assert resp.json['ok'] is False

    def test_migrate_full_flow(self, app, admin_client, tmp_path, monkeypatch):
        """迁移 HTTP 全流程（不勾立即切换）：数据写入目标库 + 配置落盘临时路径。"""
        import plugins.db_migrator.admin as admin_mod
        import app.utils.dbconfig as dbconfig_mod

        uri = _target_uri(tmp_path)
        monkeypatch.setattr(admin_mod, '_build_target_uri', lambda: uri)
        # db_config.json 落盘路径隔离，避免污染真实 instance 目录
        monkeypatch.setattr(dbconfig_mod, 'CONFIG_PATH',
                            str(tmp_path / 'db_config.json'))
        _enable(app)

        resp = admin_client.post('/admin/db-migrator/migrate', data={
            'db_type': 'sqlite', 'overwrite': '', 'switch_now': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert '迁移完成'.encode() in resp.data

        tgt = create_engine(uri)
        try:
            from app.models.article import Article
            with app.app_context():
                n_src = Article.query.count()
            with tgt.connect() as tc:
                n_tgt = tc.execute(text('SELECT COUNT(*) FROM articles')).scalar()
            assert n_tgt == n_src
        finally:
            tgt.dispose()
        assert os.path.exists(str(tmp_path / 'db_config.json'))
