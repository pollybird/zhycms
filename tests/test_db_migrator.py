"""数据库迁移插件测试：迁移核心逻辑 + 后台路由门控。

迁移核心用 SQLite→SQLite 验证（目标 dialect 无序列重置，逻辑自动跳过）；
MySQL/PostgreSQL 目标需真实服务器，不纳入单测。
"""
import os

import pytest
from sqlalchemy import (
    Column, Integer, MetaData, String, Table, UniqueConstraint,
    create_engine, text,
)
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

    def test_migrate_1200_rows_succeeds(self, app, tmp_path):
        """3.1.7 回归：上线前灌入 1000+ 行数据时迁移不能失败。"""
        from app.extensions import db
        from app.models.article import Article
        from app.models.column import Column
        from plugins.db_migrator.migrate import run_migration

        uri = _target_uri(tmp_path)
        col = None
        with app.app_context():
            try:
                col = Column(name='迁移测试栏目', slug='mig-test-news', type='list')
                db.session.add(col)
                db.session.commit()
                for i in range(1200):
                    db.session.add(Article(
                        column_id=col.id, title='批量文章 %d' % i,
                        content='正文' * 50, status='published',
                        is_enabled=True, is_deleted=False,
                    ))
                db.session.commit()
                result = run_migration(uri)
                assert result['total_rows'] > 1200
                assert not result['orphans']
            finally:
                # 共享测试库：清理本用例灌入的数据，避免影响后续用例
                if col is not None:
                    Article.query.filter_by(column_id=col.id).delete(
                        synchronize_session=False)
                    Column.query.filter_by(id=col.id).delete(
                        synchronize_session=False)
                    db.session.commit()

        tgt = create_engine(uri)
        try:
            with tgt.connect() as tc:
                n = tc.execute(text('SELECT COUNT(*) FROM articles')).scalar()
            assert n >= 1200
        finally:
            tgt.dispose()

    def test_orphan_fk_blocks_with_readable_report(self, app, tmp_path):
        """源库孤儿外键（SQLite 不强制外键）→ 迁移前拦截并给出表名。"""
        from app.extensions import db
        from app.models.article import Article
        from plugins.db_migrator.migrate import run_migration, MigrationError

        uri = _target_uri(tmp_path)
        with app.app_context():
            article = Article(
                column_id=99999, title='孤儿引用文章', content='x',
                status='published', is_enabled=True, is_deleted=False,
            )
            db.session.add(article)
            db.session.commit()
            try:
                with pytest.raises(MigrationError) as ei:
                    run_migration(uri)
                msg = str(ei.value)
                assert 'articles' in msg
                assert '外键孤儿' in msg
            finally:
                Article.query.filter_by(id=article.id).delete(
                    synchronize_session=False)
                db.session.commit()

    def test_nullify_nullable_orphan_allowed(self, app, tmp_path):
        """可空外键孤儿：勾选自动置空后迁移成功，目标库对应值为 NULL。"""
        from app.extensions import db
        from app.models.audit import AuditLog
        from plugins.db_migrator.migrate import run_migration

        uri = _target_uri(tmp_path)
        with app.app_context():
            log = AuditLog(user_id=99999, op_type='create', module='article')
            db.session.add(log)
            db.session.commit()
            try:
                result = run_migration(uri, nullify_orphans=True)
                assert any(o['table'] == 'audit_logs' for o in result['orphans'])
            finally:
                AuditLog.query.filter_by(id=log.id).delete(
                    synchronize_session=False)
                db.session.commit()

        tgt = create_engine(uri)
        try:
            with tgt.connect() as tc:
                nulls = tc.execute(text(
                    'SELECT COUNT(*) FROM audit_logs WHERE user_id IS NULL'
                )).scalar()
            assert nulls >= 1
        finally:
            tgt.dispose()



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


class TestCapMysqlIndexColumns:
    """_cap_mysql_index_columns：老版 MySQL 767 字节索引前缀限制（utf8mb4）。"""

    @staticmethod
    def _fake_engine(dialect_name):
        class _Dialect:
            name = dialect_name
        class _Engine:
            dialect = _Dialect()
        return _Engine()

    def test_caps_indexed_and_unique_over_191(self):
        from plugins.db_migrator.migrate import _cap_mysql_index_columns
        md = MetaData()
        Table('t1', md,
              Column('id', Integer, primary_key=True),
              Column('fn', String(255), index=True),    # 索引列 → 191
              Column('uq', String(255), unique=True),   # 唯一列 → 191
              Column('plain', String(255)),             # 无索引 → 保持 255
              Column('ok', String(191), index=True))    # 已合规 → 不动
        _cap_mysql_index_columns(self._fake_engine('mysql'), md)
        t1 = md.tables['t1']
        assert t1.c.fn.type.length == 191
        assert t1.c.uq.type.length == 191
        assert t1.c.plain.type.length == 255
        assert t1.c.ok.type.length == 191

    def test_caps_composite_unique_constraint_columns(self):
        from plugins.db_migrator.migrate import _cap_mysql_index_columns
        md = MetaData()
        Table('t2', md,
              Column('id', Integer, primary_key=True),
              Column('a', String(300)),
              Column('b', String(255)),
              UniqueConstraint('a', 'b', name='uq_ab'))
        _cap_mysql_index_columns(self._fake_engine('mysql'), md)
        t2 = md.tables['t2']
        assert t2.c.a.type.length == 191
        assert t2.c.b.type.length == 191

    def test_non_mysql_target_untouched(self):
        from plugins.db_migrator.migrate import _cap_mysql_index_columns
        md = MetaData()
        Table('t', md, Column('x', String(255), index=True))
        _cap_mysql_index_columns(self._fake_engine('sqlite'), md)
        _cap_mysql_index_columns(self._fake_engine('postgresql'), md)
        assert md.tables['t'].c.x.type.length == 255

    def test_real_model_backup_records_filename_capped(self):
        """线上报错场景回归：backup_records.filename 在 MySQL 目标下降到 191。"""
        from plugins.db_migrator.migrate import _cap_mysql_index_columns
        from app import create_app
        from app.extensions import db
        app = create_app()
        with app.app_context():
            md = db.Model.metadata
            assert md.tables['backup_records'].c.filename.type.length == 255
            _cap_mysql_index_columns(self._fake_engine('mysql'), md)
            assert md.tables['backup_records'].c.filename.type.length == 191
