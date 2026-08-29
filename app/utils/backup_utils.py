"""数据库备份与恢复工具（模块4）。

支持：
- SQLite：直接复制 .db 文件 + gzip 压缩
- MySQL / PostgreSQL：优先调用 system `mysqldump` / `pg_dump`，失败则回退到应用层导出为 JSON（数据行数有限制时可用）
"""
import os
import io
import gzip
import shutil
import json
import subprocess
import hashlib
from datetime import datetime, timedelta

from flask import current_app

from ..extensions import db
from ..models.backup import BackupRecord, TRIGGER_MANUAL, TRIGGER_SCHEDULED
from ..models.setting import Setting


def _db_type_and_path():
    """返回 (db_type, db_name_or_path, host, port, user, password)。"""
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if uri.startswith('sqlite:///'):
        path = uri[len('sqlite:///'):]
        return 'sqlite', path, None, None, None, None
    if uri.startswith('mysql+pymysql://') or uri.startswith('mysql://'):
        # mysql+pymysql://user:pwd@host:port/dbname
        prefix = 'mysql+pymysql://' if 'mysql+pymysql' in uri else 'mysql://'
        rest = uri[len(prefix):]
        return ('mysql',) + _parse_db_url(rest)
    if uri.startswith('postgresql'):
        prefix = 'postgresql+psycopg2://' if 'psycopg2' in uri else 'postgresql://'
        rest = uri[len(prefix):]
        return ('postgresql',) + _parse_db_url(rest)
    return 'unknown', uri, None, None, None, None


def _parse_db_url(rest):
    """解析 user:pwd@host:port/dbname → (dbname, host, port, user, pwd)。"""
    try:
        auth, hostpart = rest.split('@', 1) if '@' in rest else (None, rest)
        user, pwd = (auth.split(':', 1) if auth and ':' in auth else (auth, '')) if auth else ('', '')
        host_port, dbname = hostpart.split('/', 1) if '/' in hostpart else (hostpart, '')
        if ':' in host_port:
            host, port = host_port.split(':', 1)
        else:
            host, port = host_port, None
        port = int(port) if port and port.isdigit() else None
        # 剥离 SQLAlchemy URL 查询参数（如 ?charset=utf8mb4），否则 mysqldump 会
        # 把 "zhycms?charset=utf8mb4" 当成库名报 1049 Unknown database
        if '?' in dbname:
            dbname = dbname.split('?', 1)[0]
        return dbname, host, port, user or '', pwd or ''
    except Exception:
        return '', None, None, '', ''


def _backup_dir():
    return current_app.config.get('BACKUP_FOLDER') or os.path.join(
        os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        'instance', 'backups'
    )


def _ts():
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def _expired_at():
    try:
        days = int(Setting.get('backup_keep_days', '30'))
    except ValueError:
        days = 30
    if days <= 0:
        return None
    return datetime.now() + timedelta(days=days)


# ============================================================
# 执行备份
# ============================================================

def create_backup(trigger=TRIGGER_MANUAL, remark='', created_by=None):
    """创建一次备份，写入 BackupRecord；返回 (record, None) 或 (None, error_msg)。"""
    db_type, db_name_or_path, host, port, user, pwd = _db_type_and_path()
    backup_dir = _backup_dir()
    os.makedirs(backup_dir, exist_ok=True)
    filename = f'zhycms_{db_type}_{_ts()}.sql.gz'
    dest_path = os.path.join(backup_dir, filename)

    ok = False
    err_msg = None
    try:
        if db_type == 'sqlite':
            ok = _backup_sqlite(db_name_or_path, dest_path)
        elif db_type == 'mysql':
            ok = _backup_mysql(dest_path, db_name_or_path, host, port or 3306, user, pwd)
        elif db_type == 'postgresql':
            ok = _backup_pg(dest_path, db_name_or_path, host, port or 5432, user, pwd)
        else:
            ok = _backup_json(dest_path)  # 兜底：JSON 导出
    except Exception as e:
        err_msg = str(e)

    size = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
    record = BackupRecord(
        filename=filename,
        file_size=size,
        trigger=trigger,
        db_type=db_type,
        remark=remark or '',
        status='ok' if ok else 'failed',
        error_msg=err_msg if not ok else None,
        created_by=created_by.id if created_by and hasattr(created_by, 'id') else None,
        expired_at=_expired_at(),
    )
    db.session.add(record)
    db.session.commit()
    if not ok and not err_msg:
        err_msg = 'backup failed (unknown reason)'
    return (record, None) if ok else (None, err_msg or 'backup failed')


def _backup_sqlite(src_path, dest_path):
    """SQLite 备份：复制 db 文件后 gzip 压缩。"""
    # 使用 sqlite3.backup API（通过 SQLAlchemy engine.raw_connection()）
    import sqlite3 as _sq
    try:
        if not os.path.exists(src_path):
            # DATABASE_URI 可能是相对路径
            from app.config import BASE_DIR
            alt = os.path.join(BASE_DIR, src_path)
            if os.path.exists(alt):
                src_path = alt
        # 优先用 sqlite3 的 backup API 防止复制到半写入文件
        raw_conn = db.engine.raw_connection()
        try:
            temp_path = dest_path[:-3]  # 去掉 .gz
            dst = _sq.connect(temp_path)
            try:
                raw_conn.driver_connection.backup(dst)
            finally:
                dst.close()
        finally:
            raw_conn.close()
        with open(temp_path, 'rb') as f_in, gzip.open(dest_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return True
    except Exception:
        # fallback: 直接复制 + gzip
        if os.path.exists(src_path):
            with open(src_path, 'rb') as f_in, gzip.open(dest_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            return True
        return False


def _backup_mysql(dest_path, dbname, host, port, user, pwd):
    """调用 mysqldump；失败回退 JSON。"""
    cmd = ['mysqldump', '--default-character-set=utf8mb4',
           f'-h{host or "localhost"}', f'-P{port}', f'-u{user or ""}']
    if pwd:
        cmd.append(f'-p{pwd}')
    cmd.append(dbname or '')
    return _run_dump_with_gzip(cmd, dest_path, fallback_json=True)


def _backup_pg(dest_path, dbname, host, port, user, pwd):
    env = os.environ.copy()
    if pwd:
        env['PGPASSWORD'] = pwd
    cmd = ['pg_dump', f'--host={host or "localhost"}', f'--port={port}',
           f'--username={user or ""}', dbname or '']
    return _run_dump_with_gzip(cmd, dest_path, env=env, fallback_json=True)


def _run_dump_with_gzip(cmd, dest_path, env=None, fallback_json=False):
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        with gzip.open(dest_path, 'wb') as f_out:
            shutil.copyfileobj(proc.stdout, f_out)
        rc = proc.wait(timeout=600)
        if rc == 0:
            return True
        # 失败时清掉空文件，走 fallback
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except OSError:
            pass
    except Exception:
        pass
    if fallback_json:
        return _backup_json(dest_path)
    return False


def _backup_json(dest_path):
    """兜底备份：用 ORM 把所有表导出为 JSON（适合小规模数据）。"""
    try:
        data = {}
        insp = db.inspect(db.engine)
        tbls = insp.get_table_names()
        # 按方言引用标识符（MySQL/MariaDB 反引号，PG 双引号）
        _q = db.engine.dialect.identifier_preparer.quote
        for t in tbls:
            rows = []
            for row in db.session.execute(db.text(f'SELECT * FROM {_q(t)}')).mappings().all():
                d = {}
                for k, v in dict(row).items():
                    if isinstance(v, datetime):
                        d[k] = v.isoformat()
                    else:
                        d[k] = v
                rows.append(d)
            data[t] = rows
        with gzip.open(dest_path, 'wt', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
        return True
    except Exception as e:
        current_app.logger.exception('json backup failed: %s', e)
        return False


# ============================================================
# 备份恢复
# ============================================================

def restore_backup(record_or_filename):
    """恢复备份。返回 (ok, message)。"""
    if isinstance(record_or_filename, BackupRecord):
        path = record_or_filename.abs_path
    else:
        path = os.path.join(_backup_dir(), record_or_filename)
    if not os.path.exists(path):
        return False, '备份文件不存在'
    db_type, *_ = _db_type_and_path()
    try:
        if db_type == 'sqlite':
            return _restore_sqlite(path)
        if db_type == 'mysql':
            return _restore_mysql(path)
        if db_type == 'postgresql':
            return _restore_pg(path)
        # JSON 格式
        return _restore_json(path)
    except Exception as e:
        return False, f'restore error: {e}'


def _restore_sqlite(gz_path):
    """解压 .gz 后替换 SQLite db 文件（替换前备份一份当前库以防万一）。"""
    db_type, db_path, *_ = _db_type_and_path()
    import sqlite3 as _sq
    # 解压到临时 db 文件
    tmp_path = gz_path + '.restore_tmp.db'
    with gzip.open(gz_path, 'rb') as f_in, open(tmp_path, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)
    # 校验 tmp_path 是否为合法 sqlite
    try:
        t = _sq.connect(tmp_path)
        t.execute('SELECT 1')
        t.close()
    except Exception:
        os.remove(tmp_path) if os.path.exists(tmp_path) else None
        return False, '备份文件格式损坏，无法恢复为 SQLite'

    # 在应用层：用 sqlite3 backup API 把备份文件内容复制回当前库（避免文件锁定）
    raw_conn = db.engine.raw_connection()
    try:
        src = _sq.connect(tmp_path)
        try:
            # 方向：src(备份文件) -> 当前库连接，才是「恢复」
            src.backup(raw_conn.driver_connection)
            raw_conn.commit()
        finally:
            src.close()
    except Exception:
        # 无法 backup 方法回写，直接尝试用文件覆盖（仅在文件路径模式可用）
        try:
            raw_conn.close()
            db.engine.dispose()
            if os.path.exists(db_path):
                shutil.copy(db_path, db_path + '.before_restore')
            shutil.copy(tmp_path, db_path)
        except Exception as e:
            return False, f'无法写入数据库文件：{e}'
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    # 恢复后丢弃连接池中的旧连接，避免后续查询读到恢复前的旧数据
    db.engine.dispose()
    return True, 'SQLite 恢复成功'


def _restore_mysql(gz_path):
    """解压 .gz 后通过 `mysql` CLI 导入。"""
    db_type, dbname, host, port, user, pwd = _db_type_and_path()
    sql_path = gz_path + '.sql'
    try:
        with gzip.open(gz_path, 'rb') as f_in, open(sql_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    except Exception:
        # gzip 损坏：copyfileobj 中途失败会留下空/半截 .sql 中间文件，必须清理
        try:
            if os.path.exists(sql_path):
                os.remove(sql_path)
        except OSError:
            pass
        return False, '备份文件解压失败（文件损坏或格式不符）'
    try:
        # 判断是否为 JSON 备份（.json.gz 存为 .gz，但解压出来是 JSON 文本）
        with open(sql_path, 'r', encoding='utf-8', errors='ignore') as f:
            head = f.read(2048)
        if head.lstrip().startswith('{'):
            return _restore_json(gz_path)
        # 关键：先结束当前 ORM 会话事务并丢弃本进程连接池。
        # 池内连接若处于未提交事务（曾 SELECT 过表），会持有对应表的
        # 元数据锁（MDL），导致导入端 `DROP TABLE` 与自己死锁、永久挂起。
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        db.engine.dispose()
        # --init-command 设置锁等待超时：并发连接持锁时 15 秒快速失败，
        # 避免恢复请求永久挂起（错误信息可通过返回值提示用户稍后重试）
        cmd = ['mysql', '--init-command=SET SESSION lock_wait_timeout=15',
               f'-h{host or "localhost"}', f'-P{port or 3306}', f'-u{user or ""}']
        if pwd:
            cmd.append(f'-p{pwd}')
        cmd.append(dbname or '')
        with open(sql_path, 'rb') as f:
            proc = subprocess.Popen(cmd, stdin=f, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, err = proc.communicate(timeout=600)
        if proc.returncode != 0:
            return False, f'mysql 导入失败: {(err or b"").decode("utf-8", errors="ignore")[:500]}'
        return True, 'MySQL 恢复成功'
    finally:
        try:
            os.remove(sql_path)
        except OSError:
            pass


def _restore_pg(gz_path):
    db_type, dbname, host, port, user, pwd = _db_type_and_path()
    sql_path = gz_path + '.sql'
    env = os.environ.copy()
    if pwd:
        env['PGPASSWORD'] = pwd
    try:
        with gzip.open(gz_path, 'rb') as f_in, open(sql_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    except Exception:
        try:
            if os.path.exists(sql_path):
                os.remove(sql_path)
        except OSError:
            pass
        return False, '备份文件解压失败（文件损坏或格式不符）'
    try:
        with open(sql_path, 'r', encoding='utf-8', errors='ignore') as f:
            head = f.read(2048)
        if head.lstrip().startswith('{'):
            return _restore_json(gz_path)
        cmd = ['psql', f'--host={host or "localhost"}', f'--port={port or 5432}',
               f'--username={user or ""}', '-f', sql_path, dbname or '']
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        _, err = proc.communicate(timeout=600)
        if proc.returncode != 0:
            return False, f'psql 导入失败: {(err or b"").decode("utf-8", errors="ignore")[:500]}'
        return True, 'PostgreSQL 恢复成功'
    finally:
        try:
            os.remove(sql_path)
        except OSError:
            pass


def _restore_json(gz_path):
    """恢复 JSON 备份：逐表清空 + 批量 insert（小数据集）。"""
    with gzip.open(gz_path, 'rt', encoding='utf-8') as f:
        data = json.load(f)
    # 先把 tables 按外键依赖排序；简单实现：先删子表再删父表（反向）、写父表再子表（正向）
    tables = list(data.keys())
    # 简单策略：按常见创建顺序重排
    preferred = ['roles', 'permissions', 'role_permissions', 'users', 'user_roles', 'user_column_permissions',
                 'columns', 'column_fields', 'column_field_values', 'articles', 'article_field_values',
                 'article_versions', 'fragment_groups', 'fragments', 'friend_links',
                 'forms', 'form_fields', 'form_submissions', 'form_submission_values',
                 'settings', 'login_logs', 'audit_logs', 'backup_records', 'uploaded_files']
    ordered = [t for t in preferred if t in tables] + [t for t in tables if t not in preferred]
    # 先 disable foreign key check
    dialect = db.engine.dialect.name
    # 按方言引用标识符：MySQL/MariaDB 用反引号，PG/SQLite 用双引号，
    # 硬编码双引号在 MySQL(未开 ANSI_QUOTES) 上直接 1064 报错
    _prep = db.engine.dialect.identifier_preparer
    _q = _prep.quote
    conn = db.engine.raw_connection()
    try:
        cur = conn.cursor()
        if dialect == 'sqlite':
            cur.execute('PRAGMA foreign_keys=OFF')
        for t in reversed(ordered):
            try:
                cur.execute(f'DELETE FROM {_q(t)}')
            except Exception:
                conn.rollback()
        for t in ordered:
            rows = data.get(t, [])
            if not rows:
                continue
            cols = list(rows[0].keys())
            placeholders = ','.join(['?'] * len(cols)) if dialect == 'sqlite' else ','.join(['%s'] * len(cols))
            colsql = ','.join(_q(c) for c in cols)
            stmt = f'INSERT INTO {_q(t)} ({colsql}) VALUES ({placeholders})'
            batch = []
            for r in rows:
                batch.append([r.get(c) for c in cols])
                if len(batch) >= 500:
                    cur.executemany(stmt, batch)
                    batch = []
            if batch:
                cur.executemany(stmt, batch)
        conn.commit()
        if dialect == 'sqlite':
            cur.execute('PRAGMA foreign_keys=ON')
    finally:
        conn.close()
    return True, 'JSON 备份恢复成功'


# ============================================================
# 定时备份入口（调度器调用）
# ============================================================

def run_scheduled_backup():
    if Setting.get('backup_enable_scheduled') != 'on':
        return None
    return create_backup(trigger=TRIGGER_SCHEDULED, remark='scheduled auto backup')


# ============================================================
# 系统运维监控指标
# ============================================================

def system_monitor_stats():
    """返回 {disk_used_gb, disk_total_gb, db_size_mb, uptime_seconds, ...}。"""
    from ..config import BASE_DIR
    res = {}
    # 磁盘占用（INSTANCE 目录所在分区）
    try:
        path = BASE_DIR
        usage = shutil.disk_usage(path)
        res['disk_total_gb'] = round(usage.total / (1024 ** 3), 2)
        res['disk_used_gb'] = round(usage.used / (1024 ** 3), 2)
        res['disk_free_gb'] = round(usage.free / (1024 ** 3), 2)
        res['disk_used_pct'] = round(usage.used * 100 / usage.total, 1) if usage.total else 0
    except Exception:
        pass
    # DB 文件大小（SQLite 直接看文件；MySQL/PG 近似用 information_schema 查）
    try:
        db_type, db_name_or_path, *_ = _db_type_and_path()
        if db_type == 'sqlite':
            if os.path.exists(db_name_or_path):
                res['db_size_mb'] = round(os.path.getsize(db_name_or_path) / (1024 * 1024), 2)
            else:
                from app.config import BASE_DIR as _BD
                alt = os.path.join(_BD, db_name_or_path)
                if os.path.exists(alt):
                    res['db_size_mb'] = round(os.path.getsize(alt) / (1024 * 1024), 2)
        elif db_type in ('mysql', 'postgresql'):
            try:
                if db_type == 'mysql':
                    r = db.session.execute(db.text(
                        'SELECT ROUND(SUM(data_length + index_length)/1024/1024,2) '
                        'FROM information_schema.tables WHERE table_schema = DATABASE()'
                    )).scalar()
                else:
                    r = db.session.execute(db.text(
                        "SELECT ROUND(pg_database_size(current_database())/1024/1024::numeric, 2)"
                    )).scalar()
                res['db_size_mb'] = float(r or 0)
            except Exception:
                pass
    except Exception:
        pass
    # 站点运行时长：从最早用户创建时间 / 或用当前进程启动时间近似
    try:
        from ..models.user import User
        first = User.query.order_by(User.created_at.asc()).first()
        if first:
            res['uptime_seconds'] = int((datetime.now() - first.created_at).total_seconds())
    except Exception:
        pass
    # 备份目录总大小
    try:
        bdir = _backup_dir()
        total = 0
        for fn in os.listdir(bdir) if os.path.isdir(bdir) else []:
            fp = os.path.join(bdir, fn)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
        res['backup_total_mb'] = round(total / (1024 * 1024), 2)
        res['backup_count'] = BackupRecord.query.count()
    except Exception:
        pass
    # DB 健康状态
    try:
        db.session.execute(db.text('SELECT 1'))
        res['db_alive'] = True
    except Exception:
        res['db_alive'] = False
    return res
