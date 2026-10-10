# -*- coding: utf-8 -*-
"""数据库迁移插件核心逻辑。

把「当前应用正在使用的数据库」中的全部业务表结构与数据，复制到用户指定的
目标数据库（MySQL / PostgreSQL）。典型场景：本地用 SQLite 开发，完成后
迁移到服务器的 MySQL / PostgreSQL。

流程：
  1. 目标库建表（db.Model.metadata.create_all；勾选「覆盖」时先 drop 再建，
     drop_all 仅删除本系统已知表，不碰目标库中其它无关表）
  2. 安全检查：目标库中与本系统同名的表已有数据时拒绝迁移（防重复导入
     造成主键冲突 / 数据翻倍）
  3. 按 metadata.sorted_tables 拓扑序逐表复制行数据（满足外键依赖），
     单事务执行，失败整体回滚
  4. 目标库为 PostgreSQL 时重置整型主键的序列（setval），保证迁移后
     继续插入不产生主键冲突；MySQL 的 AUTO_INCREMENT 会随显式主键插入
     自动抬高，无需处理

完成后由路由层决定是否写 db_config.json / 热切换引擎（switch_engine）。
"""
from sqlalchemy import create_engine, func, inspect, select

# 每批复制行数（平衡内存占用与 executemany 效率）
CHUNK_SIZE = 500


class MigrationError(Exception):
    """迁移失败（信息可直接展示给用户）。"""


def run_migration(target_uri, overwrite=False):
    """把当前库全部业务表迁移到目标库。

    :param target_uri: 目标数据库 SQLAlchemy URI
    :param overwrite:  目标库同名表已有数据时是否清空重迁（先 drop 再建）
    :returns: {'tables': [{'table': 表名, 'rows': 行数}, ...], 'total_rows': 总行数}
    :raises MigrationError: 目标库非空且未允许覆盖等可预期错误
    """
    from app.extensions import db

    src_engine = db.engine
    tgt_engine = create_engine(target_uri)
    metadata = db.Model.metadata

    try:
        # 1. 目标库建表（覆盖模式先删本系统已知表再建）
        if overwrite:
            metadata.drop_all(tgt_engine)
        metadata.create_all(tgt_engine)

        # 2. 安全检查：目标库同名表已有数据 → 拒绝（防重复导入）
        existing = set(inspect(tgt_engine).get_table_names())
        with tgt_engine.connect() as tc:
            for table in metadata.sorted_tables:
                if table.name not in existing:
                    continue
                n = tc.execute(
                    select(func.count()).select_from(table)).scalar()
                if n:
                    raise MigrationError(
                        '目标数据库中表 {0} 已有 {1} 条数据。'
                        '如确认要清空重迁，请勾选「覆盖目标库已有数据」后重试。'
                        .format(table.name, n))

        # 3. 逐表复制（单事务，任一表失败整体回滚，目标库不残留半截数据）
        summary = []
        total = 0
        with src_engine.connect() as sc, tgt_engine.begin() as tc:
            for table in metadata.sorted_tables:
                count = _copy_table(sc, tc, table)
                summary.append({'table': table.name, 'rows': count})
                total += count

        # 4. PostgreSQL：重置自增序列
        if tgt_engine.dialect.name == 'postgresql':
            _reset_pg_sequences(tgt_engine, metadata)

        # 5. 同步 alembic 版本号：目标库由 create_all 建出与源库一致的完整
        #    schema，版本号一并同步后，重启时启动器识别为「已管理」直接
        #    upgrade head（无增量），避免对已存在的表重复执行中间迁移而报错
        _copy_alembic_version(src_engine, tgt_engine)

        return {'tables': summary, 'total_rows': total}
    finally:
        tgt_engine.dispose()


def _copy_table(src_conn, tgt_conn, table):
    """按批次复制一张表的全部行，返回复制的行数。"""
    rows_total = 0
    result = src_conn.execute(select(table))
    while True:
        chunk = result.fetchmany(CHUNK_SIZE)
        if not chunk:
            break
        tgt_conn.execute(table.insert(), [_sanitize(r) for r in chunk])
        rows_total += len(chunk)
    return rows_total


def _sanitize(row):
    """行值清洗：SQLite BLOB 列读出为 memoryview，统一转 bytes 以便跨驱动写入。"""
    mapping = row._mapping if hasattr(row, '_mapping') else row
    return {k: (v.tobytes() if isinstance(v, memoryview) else v)
            for k, v in mapping.items()}


def _copy_alembic_version(src_engine, tgt_engine):
    """把源库的 alembic_version 版本号同步到目标库。

    源库未纳入 Alembic 管理（无该表或无版本行）时跳过。alembic_version
    是 Alembic 自管表，不在业务 metadata 中，需在目标库单独建表写入。
    """
    from sqlalchemy import Column, MetaData, String, Table, text

    insp = inspect(src_engine)
    if not insp.has_table('alembic_version'):
        return
    with src_engine.connect() as sc:
        version = sc.execute(
            text('SELECT version_num FROM alembic_version')).scalar()
    if not version:
        return
    meta = MetaData()
    Table('alembic_version', meta,
          Column('version_num', String(32), primary_key=True))
    meta.create_all(tgt_engine)
    with tgt_engine.begin() as tc:
        tc.execute(text('DELETE FROM alembic_version'))
        tc.execute(text('INSERT INTO alembic_version (version_num) VALUES (:v)'),
                   {'v': version})


def _reset_pg_sequences(tgt_engine, metadata):
    """PostgreSQL：把每张表整型主键（serial）的序列重置为 max(id)+1。

    表名 / 列名来自代码中定义的 metadata（非用户输入），拼接安全；
    序列名取自 pg_get_serial_sequence 的系统返回值，同样可信。
    """
    from sqlalchemy import text
    with tgt_engine.begin() as conn:
        for table in metadata.sorted_tables:
            for col in table.primary_key.columns:
                server_default = str(getattr(col.server_default, 'arg', '') or '')
                if 'nextval' not in server_default:
                    continue
                seq = conn.execute(
                    text('SELECT pg_get_serial_sequence(:t, :c)'),
                    {'t': table.name, 'c': col.name}).scalar()
                if not seq:
                    continue
                conn.execute(text(
                    "SELECT setval('{0}', COALESCE("
                    "(SELECT MAX({1}) FROM {2}), 0) + 1, false)"
                ).format(seq, col.name, table.name))
