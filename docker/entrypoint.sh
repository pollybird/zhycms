#!/bin/sh
set -e

# 演示图片恢复（volume 挂载 uploads/ 时遮盖 demo/）
if [ -d /opt/demo-stash ] && [ ! -d /app/app/static/uploads/demo ]; then
    cp -r /opt/demo-stash /app/app/static/uploads/demo
fi

# 执行数据库迁移（安全幂等）
python -c "
from app import create_app
app = create_app()
print('[entrypoint] App initialized, migrations applied')
" || echo '[entrypoint] WARNING: migration check failed, continuing...'

# 执行用户命令（默认 gunicorn）
exec "$@"
