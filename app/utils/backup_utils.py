"""数据库备份与恢复工具（模块4）。

支持：
- SQLite：直接复制 .db 文件 + gzip 压缩
- MySQL / PostgreSQL / PolarDB for PostgreSQL：优先调用 system `mysqldump` / `pg_dump`，失败则回退到应用层导出为 JSON（数据行数有限制时可用）
- openGauss / KingbaseES / 达梦 DM8：调用各自厂商工具
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
    """返回 (db_type, db_name_or_path, host, port, user, password)。

    统一用 ``make_url`` 解析，兼容用户名/密码中的特殊字符，并识别
    openGauss / KingbaseES 以及 host 位于 query 的 Unix socket 形态。
    """
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '') or ''
    try:
        from sqlalchemy.engine import make_url
        url = make_url(uri)
        backend = url.get_backend_name()
    except Exception as e:
        current_app.logger.warning('数据库连接串解析失败，按空配置处理：%s', e)
        return 'unknown', uri, None, None, None, None

    if backend == 'sqlite':
        return 'sqlite', url.database or '', None, None, None, None
    if backend not in ('mysql', 'postgresql', 'opengauss', 'kingbase', 'dm',
                       'polardb_pg'):
        return 'unknown', uri, None, None, None, None

    # v3.3.0：build_uri() 对 socket 连接把路径放在 query（MySQL: unix_socket，
    # PostgreSQL/openGauss/KingbaseES: host），此时 url.host 为空，需要回退到 query 取。
    socket_key = 'unix_socket' if backend == 'mysql' else 'host'
    host = url.query.get(socket_key) or url.host
    return backend, url.database or '', host, url.port, url.username or '', url.password or ''


def _bin_tool(name, db_type=None):
    """定位外部数据库工具路径（v3.3.0）。

    优先级：``DB_DUMP_BIN_DIR`` 配置/环境变量 > 信创库专用 bin 目录
    （openGauss ``OPENGAUSS_BIN`` / KingbaseES ``ZHYCMS_KINGBASE_BIN`` /
    达梦 ``ZHYCMS_DM_BIN`` 或 ``DM_HOME`` / PolarDB ``ZHYCMS_POLARDB_BIN``） >
    ``ZHYCMS_DB_DUMP_BIN`` 显式文件（仅备份工具） > PATH。
    """
    from flask import has_app_context
    dump_tools = ('mysqldump', 'pg_dump', 'gs_dump', 'sys_dump', 'dexp')
    bin_dir = ''
    if has_app_context():
        bin_dir = current_app.config.get('DB_DUMP_BIN_DIR') or ''
    bin_dir = (bin_dir or os.environ.get('ZHYCMS_DB_DUMP_BIN_DIR')
               or os.environ.get('DB_DUMP_BIN_DIR') or '')
    if bin_dir:
        candidate = os.path.join(bin_dir, name)
        if os.path.exists(candidate):
            return candidate
    if db_type == 'opengauss':
        og_bin = os.environ.get('OPENGAUSS_BIN', '')
        if og_bin:
            candidate = os.path.join(og_bin, name) if os.path.isdir(og_bin) else og_bin
            if os.path.exists(candidate):
                return candidate
    if db_type == 'kingbase':
        kb_bin = os.environ.get('ZHYCMS_KINGBASE_BIN', '') or os.environ.get('KINGBASE_BIN', '')
        if kb_bin:
            candidate = os.path.join(kb_bin, name) if os.path.isdir(kb_bin) else kb_bin
            if os.path.exists(candidate):
                return candidate
    if db_type == 'dm':
        # ZHYCMS_DM_BIN 可指向达梦客户端 bin 目录或 DM_HOME（自动补 bin/）
        dm_bin = os.environ.get('ZHYCMS_DM_BIN', '') or os.environ.get('DM_HOME', '')
        if dm_bin:
            if os.path.isdir(dm_bin):
                candidate = os.path.join(dm_bin, name)
                if not os.path.exists(candidate):
                    candidate = os.path.join(dm_bin, 'bin', name)
            else:
                candidate = dm_bin
            if os.path.exists(candidate):
                return candidate
    if db_type == 'polardb_pg':
        # ZHYCMS_POLARDB_BIN 可指向 PolarDB 客户端 bin 目录或 POLARDB_HOME（自动补 bin/）
        pdb_bin = os.environ.get('ZHYCMS_POLARDB_BIN', '') or os.environ.get('POLARDB_HOME', '')
        if pdb_bin:
            if os.path.isdir(pdb_bin):
                candidate = os.path.join(pdb_bin, name)
                if not os.path.exists(candidate):
                    candidate = os.path.join(pdb_bin, 'bin', name)
            else:
                candidate = pdb_bin
            if os.path.exists(candidate):
                return candidate
    if name in dump_tools:
        explicit = os.environ.get('ZHYCMS_DB_DUMP_BIN', '')
        if explicit and os.path.isfile(explicit):
            return explicit
    return shutil.which(name) or name


def _tool_env(db_type, password=None):
    """构造外部工具运行环境：密码 + openGauss 动态库搜索路径。

    KingbaseES 的客户端工具（ksql / sys_dump / sys_restore）不识别
    ``PGPASSWORD``，必须通过 ``KINGBASE_PASSWORD`` 注入密码（v3.3.1 实测）。
    """
    env = os.environ.copy()
    if password:
        if db_type == 'kingbase':
            env['KINGBASE_PASSWORD'] = password
        else:
            env['PGPASSWORD'] = password
    if db_type == 'opengauss':
        libdir = (os.environ.get('ZHYCMS_OPENGAUSS_LIB')
                  or os.environ.get('OPENGAUSS_LIB') or '/usr/local/opengauss/lib')
        if os.path.isdir(libdir):
            old = env.get('LD_LIBRARY_PATH', '')
            env['LD_LIBRARY_PATH'] = libdir + (':' + old if old else '')
    return env


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
    # 达梦使用 dexp 导出二进制 DMP（.dmp.gz），其它后端为纯 SQL / JSON
    suffix = '.dmp.gz' if db_type == 'dm' else '.sql.gz'
    filename = f'zhycms_{db_type}_{_ts()}{suffix}'
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
        elif db_type == 'polardb_pg':
            ok = _backup_pg(dest_path, db_name_or_path, host, port or 5432, user, pwd,
                            db_type='polardb_pg')
        elif db_type == 'opengauss':
            ok = _backup_pg(dest_path, db_name_or_path, host, port or 5432, user, pwd,
                            db_type='opengauss')
        elif db_type == 'kingbase':
            ok = _backup_pg(dest_path, db_name_or_path, host, port or 54321, user, pwd,
                            db_type='kingbase')
        elif db_type == 'dm':
            ok = _backup_dm(dest_path, db_name_or_path, host, port or 5236, user, pwd)
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
    except Exception as e:
        # backup API 不可用（如事务状态异常）：回退直接复制 + gzip
        current_app.logger.warning('SQLite backup API 失败，回退文件复制：%s', e, exc_info=True)
        if os.path.exists(src_path):
            with open(src_path, 'rb') as f_in, gzip.open(dest_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            return True
        return False


def _backup_mysql(dest_path, dbname, host, port, user, pwd):
    """调用 mysqldump；失败回退 JSON。"""
    cmd = [_bin_tool('mysqldump', 'mysql'), '--default-character-set=utf8mb4']
    if host and host.startswith('/'):
        cmd.append(f'--socket={host}')
    else:
        cmd.extend([f'-h{host or "localhost"}', f'-P{port}'])
    cmd.append(f'-u{user or ""}')
    if pwd:
        cmd.append(f'-p{pwd}')
    cmd.append(dbname or '')
    return _run_dump_with_gzip(cmd, dest_path, fallback_json=True)


def _backup_pg(dest_path, dbname, host, port, user, pwd, db_type='postgresql'):
    """调用 pg_dump（PostgreSQL / PolarDB-PG）/ gs_dump（openGauss）/ sys_dump（KingbaseES）导出纯 SQL。"""
    is_og = db_type == 'opengauss'
    tool_name = ('sys_dump' if db_type == 'kingbase'
                 else 'gs_dump' if is_og else 'pg_dump')
    tool = _bin_tool(tool_name, db_type)
    env = _tool_env(db_type, pwd)
    cmd = [tool, f'--host={host or "localhost"}', f'--port={port}',
           f'--username={user or ""}', '--no-password']
    if is_og and pwd:
        # openGauss 的 gs_dump 不读取 PGPASSWORD，需显式 -W（M0 实测）。
        cmd.extend(['-W', pwd])
    # KingbaseES：sys_dump 不识别 PGPASSWORD，密码经 _tool_env 注入的
    # KINGBASE_PASSWORD 环境变量传递，不在命令行明文出现。
    if is_og:
        # gs_dump 会把进度日志写到 stdout，直接管道压缩会污染 SQL 流；
        # 改用 -f 输出到临时文件后再压缩。
        return _run_og_dump_with_gzip(cmd, dest_path, dbname, env)
    # pg_dump / sys_dump：stdout 为纯 SQL（KingbaseES V9 实测 sys_dump 无进度污染），
    # 直接管道压缩；数据库名作为位置参数（两者均支持）。
    cmd.append(dbname or '')
    return _run_dump_with_gzip(cmd, dest_path, env=env, fallback_json=True)


def _backup_dm(dest_path, schema, host, port, user, pwd):
    """调用达梦 ``dexp`` 导出 SCHEMAS 为二进制 DMP，再 gzip 压缩。

    dexp 无 ``PGPASSWORD`` 之类的环境变量密码机制，连接串只能通过
    ``USERID=user/pwd@host:port`` 传入（达梦工具固有约束）。
    """
    tool = _bin_tool('dexp', 'dm')
    if not (os.path.isfile(tool) or shutil.which(tool)):
        raise RuntimeError('未找到达梦 dexp 备份工具，请安装达梦客户端并配置 '
                           'ZHYCMS_DM_BIN（或 DM_HOME）')
    tmp_dmp = dest_path + '.tmp.dmp'
    tmp_log = dest_path + '.tmp.log'
    userid = f'{user or ""}{"/" + pwd if pwd else ""}@{host or "localhost"}:{port}'
    cmd = [tool, f'USERID={userid}', f'FILE={tmp_dmp}', f'LOG={tmp_log}']
    if schema:
        cmd.append(f'SCHEMAS={schema}')
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, err = proc.communicate(timeout=600)
        if (proc.returncode != 0 or not os.path.exists(tmp_dmp)
                or os.path.getsize(tmp_dmp) == 0):
            log_text = ''
            try:
                if os.path.exists(tmp_log):
                    with open(tmp_log, 'r', encoding='utf-8', errors='ignore') as f:
                        log_text = f.read()[:500]
            except OSError:
                pass
            err_text = (err or b'').decode('utf-8', errors='ignore')[:500]
            if pwd:
                # dexp 日志/标准错误可能回显 USERID，避免密码落盘到应用日志
                err_text = err_text.replace(pwd, '***')
                log_text = log_text.replace(pwd, '***')
            current_app.logger.warning(
                'dexp 失败（rc=%s）：%s %s', proc.returncode, err_text, log_text)
            return False
        with open(tmp_dmp, 'rb') as f_in, gzip.open(dest_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
        return True
    except Exception as e:
        current_app.logger.warning('dexp 执行失败：%s', e)
        return False
    finally:
        for _p in (tmp_dmp, tmp_log):
            try:
                if os.path.exists(_p):
                    os.remove(_p)
            except OSError:
                pass


def _run_og_dump_with_gzip(cmd, dest_path, dbname, env):
    """gs_dump 输出到临时文件，成功后 gzip 压缩并清理。"""
    tmp_sql = dest_path + '.tmp.sql'
    try:
        proc = subprocess.Popen(
            cmd + ['-f', tmp_sql, dbname or ''],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env)
        _, err = proc.communicate(timeout=600)
        if proc.returncode != 0:
            current_app.logger.warning(
                'gs_dump 失败：%s', (err or b'').decode('utf-8', errors='ignore')[:500])
        elif os.path.exists(tmp_sql) and os.path.getsize(tmp_sql) > 0:
            with open(tmp_sql, 'rb') as f_in, gzip.open(dest_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            return True
    except Exception as e:
        current_app.logger.warning('gs_dump 执行失败，尝试 JSON 兜底：%s', e)
    finally:
        try:
            if os.path.exists(tmp_sql):
                os.remove(tmp_sql)
        except OSError:
            pass
    return _backup_json(dest_path)


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
    except Exception as e:
        current_app.logger.warning('外部数据库导出命令失败，尝试 JSON 兜底：%s', e)
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
        if db_type in ('postgresql', 'opengauss', 'kingbase', 'polardb_pg'):
            return _restore_pg(path)
        if db_type == 'dm':
            return _restore_dm(path)
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
    except Exception as e:
        # 无法 backup 方法回写，直接尝试用文件覆盖（仅在文件路径模式可用）
        current_app.logger.warning('SQLite backup API 回写失败，尝试文件覆盖：%s', e, exc_info=True)
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
        except Exception as e:
            db.session.rollback()
            current_app.logger.warning('恢复前提交/结束会话失败：%s', e)
        db.engine.dispose()
        # --init-command 设置锁等待超时：并发连接持锁时 15 秒快速失败，
        # 避免恢复请求永久挂起（错误信息可通过返回值提示用户稍后重试）
        cmd = [_bin_tool('mysql', 'mysql'),
               '--init-command=SET SESSION lock_wait_timeout=15']
        if host and host.startswith('/'):
            cmd.append(f'--socket={host}')
        else:
            cmd.extend([f'-h{host or "localhost"}', f'-P{port or 3306}'])
        cmd.append(f'-u{user or ""}')
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
    is_og = db_type == 'opengauss'
    is_kb = db_type == 'kingbase'
    is_pdb = db_type == 'polardb_pg'
    sql_path = gz_path + '.sql'
    env = _tool_env(db_type, pwd)
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
        if is_og:
            # openGauss 备份由 gs_dump 生成纯 SQL，用 gsql 导入；库名走 -d
            cmd = [_bin_tool('gsql', 'opengauss'),
                   f'--host={host or "localhost"}', f'--port={port or 5432}',
                   f'--username={user or ""}',
                   '-d', dbname or '', '-f', sql_path]
            if pwd:
                cmd.extend(['-W', pwd])
        elif is_kb:
            # KingbaseES 用 ksql 导入；密码经 KINGBASE_PASSWORD 环境变量（env 中），
            # -w 禁止交互提示，避免无密码时挂起（默认端口 54321）。
            cmd = [_bin_tool('ksql', 'kingbase'),
                   f'--host={host or "localhost"}', f'--port={port or 54321}',
                   f'--username={user or ""}', '-w',
                   '-d', dbname or '', '-f', sql_path]
        else:
            cmd = [_bin_tool('psql', db_type),
                   f'--host={host or "localhost"}', f'--port={port or 5432}',
                   f'--username={user or ""}', '-w',
                   '-f', sql_path, dbname or '']
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        _, err = proc.communicate(timeout=600)
        if proc.returncode != 0:
            tool = 'gsql' if is_og else ('ksql' if is_kb else 'psql')
            return False, f'{tool} 导入失败: {(err or b"").decode("utf-8", errors="ignore")[:500]}'
        ok_msg = ('openGauss 恢复成功' if is_og
                  else 'KingbaseES 恢复成功' if is_kb
                  else 'PolarDB for PostgreSQL 恢复成功' if is_pdb
                  else 'PostgreSQL 恢复成功')
        return True, ok_msg
    finally:
        try:
            os.remove(sql_path)
        except OSError:
            pass


def _restore_dm(gz_path):
    """解压 ``.dmp.gz`` 后通过达梦 ``dimp`` 导入当前 Schema。"""
    _, schema, host, port, user, pwd = _db_type_and_path()
    tool = _bin_tool('dimp', 'dm')
    if not (os.path.isfile(tool) or shutil.which(tool)):
        return False, ('未找到达梦 dimp 恢复工具，请安装达梦客户端并配置 '
                       'ZHYCMS_DM_BIN（或 DM_HOME）')
    dmp_path = gz_path + '.dmp'
    log_path = gz_path + '.dimp.log'
    try:
        with gzip.open(gz_path, 'rb') as f_in, open(dmp_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    except Exception as e:
        current_app.logger.warning('达梦备份解压失败：%s', e)
        for _p in (dmp_path, log_path):
            try:
                if os.path.exists(_p):
                    os.remove(_p)
            except OSError:
                pass
        return False, '备份文件解压失败（文件损坏或格式不符）'
    try:
        # 结束当前会话事务并丢弃连接池，避免导入时被应用连接占用的对象锁阻塞
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.warning('恢复前提交/结束会话失败：%s', e)
        db.engine.dispose()
        userid = f'{user or ""}{"/" + pwd if pwd else ""}@{host or "localhost"}:{port}'
        cmd = [tool, f'USERID={userid}', f'FILE={dmp_path}', f'LOG={log_path}']
        if schema:
            cmd.append(f'SCHEMAS={schema}')
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, err = proc.communicate(timeout=600)
        if proc.returncode != 0:
            detail = (err or b'').decode('utf-8', errors='ignore')[:500]
            try:
                if os.path.exists(log_path):
                    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                        detail = (detail + ' ' + f.read()[:500]).strip()
            except OSError:
                pass
            if pwd:
                # dimp 日志可能回显 USERID，避免密码出现在页面错误信息中
                detail = detail.replace(pwd, '***')
            return False, f'dimp 导入失败: {detail}'
        return True, '达梦 DM8 恢复成功'
    finally:
        for _p in (dmp_path, log_path):
            try:
                if os.path.exists(_p):
                    os.remove(_p)
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
            except Exception as e:
                conn.rollback()
                current_app.logger.warning('恢复 JSON 备份时清空表 %s 失败：%s', t, e)
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
    except Exception as e:
        current_app.logger.warning('读取磁盘占用失败：%s', e)
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
        elif db_type in ('mysql', 'postgresql', 'opengauss', 'kingbase'):
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
            except Exception as e:
                current_app.logger.warning('查询数据库大小失败：%s', e)
    except Exception as e:
        current_app.logger.warning('读取数据库大小失败：%s', e)
    # 站点运行时长：从最早用户创建时间 / 或用当前进程启动时间近似
    try:
        from ..models.user import User
        first = User.query.order_by(User.created_at.asc()).first()
        if first:
            res['uptime_seconds'] = int((datetime.now() - first.created_at).total_seconds())
    except Exception as e:
        current_app.logger.warning('计算站点运行时长失败：%s', e)
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
    except Exception as e:
        current_app.logger.warning('读取备份目录统计失败：%s', e)
    # DB 健康状态
    try:
        db.session.execute(db.text('SELECT 1'))
        res['db_alive'] = True
    except Exception as e:
        res['db_alive'] = False
        current_app.logger.warning('数据库健康检查失败：%s', e)
    return res
