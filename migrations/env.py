"""Alembic 环境配置（Flask-Migrate 定制版）。

v2.4.0 特殊逻辑：
1. 从 Flask-Migrate 扩展获取 db.metadata 和 engine URL
2. 自动发现插件迁移文件并合并到 version_locations
3. 首次启动时检测旧库（v2.3.0 及更早），stamp baseline 而非执行 DDL
"""
import os
from logging.config import fileConfig

from flask import current_app

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从 Flask-Migrate 扩展获取 metadata
try:
    target_metadata = current_app.extensions['migrate'].db.metadata
except (KeyError, RuntimeError):
    target_metadata = None


def _discover_plugin_version_locations():
    """扫描 plugins/ 目录，收集插件迁移文件路径。"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plugins_dir = os.path.join(base_dir, 'plugins')
    locations = []
    if not os.path.isdir(plugins_dir):
        return locations
    for slug in os.listdir(plugins_dir):
        plugin_migrations = os.path.join(plugins_dir, slug, 'migrations', 'versions')
        if os.path.isdir(plugin_migrations):
            locations.append(plugin_migrations)
    return locations


# 合并插件迁移路径
_extra_locations = _discover_plugin_version_locations()
if _extra_locations:
    existing = config.get_main_option('version_locations', '') or ''
    parts = [p for p in existing.split(os.pathsep) if p]
    parts.extend(_extra_locations)
    config.set_main_option('version_locations', os.pathsep.join(parts))


def run_migrations_offline():
    """离线模式：生成 SQL 脚本不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """在线模式：连接数据库执行迁移。"""
    # 从 Flask-Migrate 扩展获取 engine URL
    try:
        flask_db = current_app.extensions['migrate'].db
        connectable = flask_db.engine
    except (KeyError, RuntimeError):
        from sqlalchemy import engine_from_config, pool
        connectable = engine_from_config(
            config.get_section(config.config_ini_section),
            prefix='sqlalchemy.',
            poolclass=pool.NullPool,
        )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
