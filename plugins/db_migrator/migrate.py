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
import logging

from sqlalchemy import and_, create_engine, func, inspect, select

# 每批复制行数（平衡内存占用与 executemany 效率）
CHUNK_SIZE = 500

logger = logging.getLogger(__name__)


class MigrationError(Exception):
    """迁移失败（信息可直接展示给用户）。"""


def _fk_pairs(table, fk, metadata):
    """返回 (父表引用, [(子列, 父列)])；自引用外键需用别名避免同名 join。

    父表不在 metadata 中（插件未启用等）时返回 (None, [])，跳过该项检查。
    """
    parent = fk.referred_table
    if parent.name not in metadata.tables:
        return None, []
    parent_t = parent.alias() if parent is table else parent
    pairs = [(lc, parent_t.c[el.column.key])
             for lc, el in zip(fk.columns, fk.elements)]
    return parent_t, pairs


def _check_source_foreign_keys(src_conn, metadata):
    """预检源库外键孤儿数据，返回报告列表。

    SQLite 默认不强制外键，直接用 SQL/脚本灌入的数据很容易留下孤儿引用；
    迁移到 MySQL/PostgreSQL 后这些表带真实外键，复制时会报 1452 并整体
    回滚。提前检查可给出「表.列 → 孤儿行数」的可读报告，避免用户只看到
    一条底层数据库报错。

    返回：[{'table', 'columns', 'parent', 'count', 'nullable'}]
    """
    report = []
    for table in metadata.sorted_tables:
        for fk in table.foreign_key_constraints:
            parent_t, pairs = _fk_pairs(table, fk, metadata)
            if not pairs:
                continue
            on = and_(*[lc == pc for lc, pc in pairs])
            not_null = and_(*[lc.isnot(None) for lc, _ in pairs])
            missing = and_(*[pc.is_(None) for _, pc in pairs])
            n = src_conn.execute(
                select(func.count()).select_from(table.outerjoin(parent_t, on))
                .where(not_null, missing)
            ).scalar() or 0
            if n:
                report.append({
                    'table': table.name,
                    'columns': [c.key for c in fk.columns],
                    'parent': fk.referred_table.name,
                    'count': n,
                    'nullable': all(c.nullable for c in fk.columns),
                })
    return report


def _collect_orphan_pk_map(src_conn, metadata):
    """收集可空外键的孤儿行主键，供复制时把这些列置空。

    返回 {表名: {'pk_keys': [...], 'pks': {(pk...), ...}, 'columns': [...]}}。
    """
    mapping = {}
    for table in metadata.sorted_tables:
        pk_cols = list(table.primary_key.columns)
        if not pk_cols:
            continue
        for fk in table.foreign_key_constraints:
            parent_t, pairs = _fk_pairs(table, fk, metadata)
            if not pairs or not all(c.nullable for c in fk.columns):
                continue
            on = and_(*[lc == pc for lc, pc in pairs])
            not_null = and_(*[lc.isnot(None) for lc, _ in pairs])
            missing = and_(*[pc.is_(None) for _, pc in pairs])
            rows = src_conn.execute(
                select(*pk_cols).select_from(table.outerjoin(parent_t, on))
                .where(not_null, missing)
            ).fetchall()
            if not rows:
                continue
            entry = {
                'pk_keys': [c.key for c in pk_cols],
                'pks': set(tuple(r) for r in rows),
                'columns': [c.key for c in fk.columns],
            }
            mapping.setdefault(table.name, []).append(entry)
    return mapping


def _describe_orphans(report):
    """把孤儿报告拼成便于用户处理的中文提示。"""
    lines = []
    for item in report[:10]:
        lines.append('{0}.{1} → {2}（{3} 行）'.format(
            item['table'], '/'.join(item['columns']),
            item['parent'], item['count']))
    if len(report) > 10:
        lines.append('……共 {0} 处'.format(len(report)))
    return '；'.join(lines)


def _cap_mysql_index_columns(tgt_engine, metadata):
    """老版 MySQL（5.6/Antelope 或 innodb_large_prefix=OFF）单列索引前缀上限
    767 字节；utf8mb4 每字符占 4 字节，String(N) 的 N>191 时建索引即报
    1709「Index column size too large」。SQLite/PostgreSQL 无此限制，因此
    开发库一切正常、迁移建表时才暴露。

    在 create_all 前统一把超限的索引/唯一列降到 191 字符（191×4=764≤767），
    覆盖 index=True / unique=True / 组合索引 / 组合唯一约束四种形态，仅
    影响目标库 DDL。极端边界：源库该列存在超过 191 字符的行会在数据复制
    阶段报错；实际业务数据（文件名/slug/邮箱等）不会触达该长度。
    """
    if tgt_engine.dialect.name != 'mysql':
        return
    from sqlalchemy import String, UniqueConstraint
    for table in metadata.tables.values():
        indexed_keys = set()
        for idx in table.indexes:
            indexed_keys.update(c.key for c in idx.columns)
        for cons in table.constraints:
            if isinstance(cons, UniqueConstraint):
                indexed_keys.update(c.key for c in cons.columns)
        for col in table.columns:
            if not (col.index or col.unique or col.key in indexed_keys):
                continue
            length = getattr(col.type, 'length', None)
            if isinstance(col.type, String) and length and length > 191:
                col.type.length = 191


def run_migration(target_uri, overwrite=False, nullify_orphans=False):
    """把当前库全部业务表迁移到目标库。

    :param target_uri: 目标数据库 SQLAlchemy URI
    :param overwrite:  目标库同名表已有数据时是否清空重迁（先 drop 再建）
    :param nullify_orphans: 源库存在可空外键孤儿数据时，复制时把这些列置空
    :returns: {'tables': [{'table': 表名, 'rows': 行数}, ...], 'total_rows': 总行数,
                'orphans': 孤儿外键报告}
    :raises MigrationError: 目标库非空且未允许覆盖、源库孤儿数据不可自动修复等
    """
    from app.extensions import db

    src_engine = db.engine
    tgt_engine = create_engine(target_uri)
    metadata = db.Model.metadata

    try:
        # 0. 源库外键完整性预检（放在改动目标库之前）
        #
        # SQLite 默认不强制外键，上线前用 SQL/脚本灌入的数据常带孤儿引用；
        # 目标库为 MySQL/PostgreSQL 时这些表有真实外键，复制会报 1452 并
        # 整库回滚。这里提前定位到「表.列 → 孤儿行数」，并支持对可空列
        # 在复制阶段自动置空。
        with src_engine.connect() as sc:
            orphans = _check_source_foreign_keys(sc, metadata)
        orphan_map = {}
        if orphans:
            non_nullable = [o for o in orphans if not o['nullable']]
            if non_nullable:
                raise MigrationError(
                    '源库存在外键孤儿数据，且相关列不允许为空，无法自动修复：{0}。'
                    '请先在源库补齐父表记录或删除这些行后重试。'
                    .format(_describe_orphans(non_nullable)))
            if not nullify_orphans:
                raise MigrationError(
                    '源库存在外键孤儿数据：{0}。这些数据在 SQLite 下不会报错，'
                    '但迁移到 MySQL/PostgreSQL 会因外键约束失败。可勾选'
                    '「自动置空孤儿外键（可空列）」后重试，或先清理源库数据。'
                    .format(_describe_orphans(orphans)))
            with src_engine.connect() as sc:
                orphan_map = _collect_orphan_pk_map(sc, metadata)
            logger.warning('源库存在 %d 处可空外键孤儿引用，迁移时将置空',
                           len(orphans))

        # 1. 目标库建表（覆盖模式先删本系统已知表再建）
        if overwrite:
            metadata.drop_all(tgt_engine)
        _cap_mysql_index_columns(tgt_engine, metadata)
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
                try:
                    count = _copy_table(sc, tc, table, orphan_map)
                except MigrationError:
                    raise
                except Exception as e:
                    raise MigrationError(
                        '复制表 {0} 失败：{1}'.format(table.name, e)) from e
                summary.append({'table': table.name, 'rows': count})
                total += count
                logger.info('迁移表 %s：%d 行', table.name, count)

        # 4. PostgreSQL：重置自增序列
        if tgt_engine.dialect.name == 'postgresql':
            _reset_pg_sequences(tgt_engine, metadata)

        # 5. 同步 alembic 版本号：目标库由 create_all 建出与源库一致的完整
        #    schema，版本号一并同步后，重启时启动器识别为「已管理」直接
        #    upgrade head（无增量），避免对已存在的表重复执行中间迁移而报错
        _copy_alembic_version(src_engine, tgt_engine)

        return {'tables': summary, 'total_rows': total, 'orphans': orphans}
    finally:
        tgt_engine.dispose()


def _copy_table(src_conn, tgt_conn, table, orphan_map=None):
    """按批次复制一张表的全部行，返回复制的行数。"""
    orphan_map = orphan_map or {}
    rows_total = 0
    result = src_conn.execute(select(table))
    while True:
        chunk = result.fetchmany(CHUNK_SIZE)
        if not chunk:
            break
        try:
            tgt_conn.execute(
                table.insert(),
                [_sanitize(r, table, orphan_map) for r in chunk])
        except Exception as e:
            raise MigrationError(
                '复制表 {0} 失败（已复制 {1} 行，当前批次 {2} 行）：{3}'
                .format(table.name, rows_total, len(chunk), e)) from e
        rows_total += len(chunk)
    return rows_total


def _sanitize(row, table=None, orphan_map=None):
    """行值清洗。

    - SQLite BLOB 列读出为 memoryview，统一转 bytes 以便跨驱动写入；
    - 命中孤儿外键主键的行，把对应可空外键列置为 NULL（由预检报告决定）。
    """
    mapping = row._mapping if hasattr(row, '_mapping') else row
    values = {k: (v.tobytes() if isinstance(v, memoryview) else v)
              for k, v in mapping.items()}
    entries = (orphan_map or {}).get(table.name) if table is not None else None
    if entries:
        pk = tuple(values.get(k) for k in entries[0]['pk_keys'])
        for entry in entries:
            if pk in entry['pks']:
                for key in entry['columns']:
                    if key in values:
                        values[key] = None
    return values


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
