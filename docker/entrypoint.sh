#!/bin/sh
set -e

# ---- 特权初始化（root 启动时自愈挂载目录属主）----
# 宿主机 ./instance 若由 Docker 自动创建（如新 clone 首次部署）会是 root 属主，
# 应用进程以 uid 1000 运行无权写入，导致 worker 启动失败。
# 此处以 root 完成属主修正后降权到 uid 1000 运行应用。
if [ "$(id -u)" = "0" ]; then
    chown -R 1000:1000 /app/instance /app/app/static/uploads 2>/dev/null || true
    exec gosu zhycms "$0" "$@"
fi

# ---- 演示图片恢复（volume 挂载 uploads/ 时遮盖 demo/）----
if [ -d /opt/demo-stash ] && [ ! -d /app/app/static/uploads/demo ]; then
    cp -r /opt/demo-stash /app/app/static/uploads/demo
fi

# ---- 等待数据库就绪 ----
# MySQL/PostgreSQL 首次初始化期间（临时服务器阶段）healthcheck 可能提前通过，
# 此时应用连接会被拒绝；此处显式等待，避免 worker 启动失败。
if [ -n "$ZHYCMS_DB_URI" ]; then
    python - <<'PYEOF'
import os
import sys
import time

from sqlalchemy import create_engine, text

uri = os.environ['ZHYCMS_DB_URI']
deadline = time.time() + 60
attempt = 0
while True:
    attempt += 1
    try:
        engine = create_engine(uri, pool_pre_ping=True, connect_args={'connect_timeout': 5})
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print('[entrypoint] Database ready (attempt {})'.format(attempt))
        break
    except Exception as exc:
        if time.time() > deadline:
            print('[entrypoint] ERROR: database not reachable after 60s: {}'.format(exc), file=sys.stderr)
            sys.exit(1)
        if 'Access denied' in str(exc):
            # 认证失败是确定性错误，重试无意义：数据卷由旧密码初始化，与当前密码不匹配
            print('[entrypoint] ERROR: database auth failed (Access denied).', file=sys.stderr)
            print('[entrypoint] The data volume was initialized with a different password.', file=sys.stderr)
            print('[entrypoint] Fix A: rerun install.sh, choose "reuse existing data" and enter the old password.', file=sys.stderr)
            print('[entrypoint] Fix B (data loss): docker compose --profile mysql down -v, then reinstall.', file=sys.stderr)
            sys.exit(1)
        print('[entrypoint] Waiting for database... (attempt {})'.format(attempt))
        time.sleep(2)
PYEOF
fi

# ---- 执行数据库迁移（安全幂等）----
python -c "
from app import create_app
app = create_app()
print('[entrypoint] App initialized, migrations applied')
" || echo '[entrypoint] WARNING: migration check failed, continuing...'

# ---- 执行用户命令（默认 gunicorn）----
exec "$@"
