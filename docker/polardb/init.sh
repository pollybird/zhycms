#!/usr/bin/env bash
# ============================================================
# PolarDB for PostgreSQL 单机实例初始化脚本（v3.3.3）
#
# 用于 polardb/polardb_pg_binary 镜像：该镜像只含二进制、无 entrypoint，
# 官方做法是挂载 /var/polardb 后手工执行 initdb + pg_ctl。本脚本把该流程
# 幂等化，供 docker-compose.polardb.yml 直接使用。
#
# 环境变量：
#   POLARDB_PORT      服务端口，默认 5432
#   POLARDB_USER      应用账号，默认 zhycms
#   POLARDB_DB        应用数据库，默认 zhycms
#   POLARDB_PASSWORD  应用账号与 postgres 超级用户密码（建议字母/数字/连字符）
#
# 注意：脚本需以 root 启动（修正数据卷属主），内部通过 su postgres 降权执行
# initdb / pg_ctl，数据库进程不会以 root 运行。
# ============================================================
set -euo pipefail

BIN=/u01/polardb_pg/bin
DATA=/var/polardb
PORT="${POLARDB_PORT:-5432}"
APP_USER="${POLARDB_USER:-zhycms}"
APP_DB="${POLARDB_DB:-zhycms}"
APP_PASSWORD="${POLARDB_PASSWORD:-Zhycms-2026pdb}"

# SQL 单引号转义，避免密码中的 ' 破坏语句
SQL_PASSWORD="${APP_PASSWORD//\'/\'\'}"

mkdir -p "$DATA"
chown -R postgres:postgres "$DATA"

if [ ! -s "$DATA/PG_VERSION" ]; then
  echo "[polardb] 初始化数据目录 ${DATA} ..."
  su postgres -c "$BIN/initdb -k -A trust -D $DATA"
  {
    echo "listen_addresses = '*'"
    echo "port = ${PORT}"
  } >> "$DATA/postgresql.conf"
  # initdb 默认只放行本机回环地址；容器间需显式放行全部来源并使用密码认证。
  echo "host all all all scram-sha-256" >> "$DATA/pg_hba.conf"
fi

if ! su postgres -c "$BIN/pg_ctl -D $DATA status" >/dev/null 2>&1; then
  echo "[polardb] 启动实例（端口 ${PORT}）..."
  su postgres -c "$BIN/pg_ctl -D $DATA -l $DATA/server.log -w start"
fi

if [ ! -f "$DATA/.zhycms_inited" ]; then
  SQL_FILE="$(mktemp)"
  cat > "$SQL_FILE" <<SQL
ALTER ROLE postgres PASSWORD '${SQL_PASSWORD}';
CREATE ROLE "${APP_USER}" LOGIN PASSWORD '${SQL_PASSWORD}';
CREATE DATABASE "${APP_DB}" OWNER "${APP_USER}";
SQL
  chown postgres:postgres "$SQL_FILE"
  echo "[polardb] 创建应用账号 ${APP_USER} 与数据库 ${APP_DB} ..."
  su postgres -c "$BIN/psql -v ON_ERROR_STOP=1 -p ${PORT} -f ${SQL_FILE}"
  rm -f "$SQL_FILE"
  touch "$DATA/.zhycms_inited"
fi

echo "[polardb] 就绪：${APP_USER}@127.0.0.1:${PORT}/${APP_DB}"

# 容器停止时优雅关闭数据库，避免数据未落盘。
stop_db() {
  echo "[polardb] 收到停止信号，正在关闭实例 ..."
  su postgres -c "$BIN/pg_ctl -D $DATA -m fast -w stop" || true
}
trap stop_db TERM INT

# PID 1 不能退出，否则容器会被判定为已停止；跟随日志。
tail -f "$DATA/server.log" &
wait $!
