# -*- coding: utf-8 -*-
"""数据库迁移插件：后台页面与迁移执行路由。

路由挂在核心 admin_bp 上（endpoint 归入 admin.*，自动获得后台地址前缀
即时生效机制），路径 /db-migrator（实际访问 /<后台前缀>/db-migrator）；
插件未启用时 404（不暴露存在性）。

生效机制（复用核心 setup 向导同款工具）：
  - save_db_config：把目标库 URI 落盘 instance/db_config.json（chmod 600），
    应用下次启动自动使用新库
  - switch_engine：运行时热切换 SQLAlchemy 引擎，勾选「立即切换」时免重启
    即时生效；切换失败自动回滚配置继续用旧库
"""
from functools import wraps

from flask import (
    render_template, redirect, url_for, request, flash, abort, jsonify,
    current_app,
)
from flask_babel import gettext as _gettext

from app.extensions import db
from app.admin import admin_bp
from app.models.audit import OP_CONFIG_CHANGE
from app.utils.helpers import permission_required, audit_log
from app.utils.dbconfig import (
    build_uri, test_connection, save_db_config, switch_engine, clear_db_config,
)
from app.plugin_system import plugin_enabled

from .migrate import run_migration, MigrationError

AUDIT_MODULE = 'db_migrator'

# 支持的目标数据库类型（label 用于页面下拉）
DB_TYPES = [
    ('mysql', 'MySQL 5.7+ / 8.x / MariaDB 10.4+'),
    ('postgresql', 'PostgreSQL 12+'),
]


def _gate(view):
    """插件启用守卫：未启用 → 404。"""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not plugin_enabled('db_migrator'):
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def _build_target_uri():
    """从表单构造目标库 URI（复用 setup 向导的 build_uri，密码特殊字符已转义）。"""
    return build_uri(
        request.form.get('db_type') or '',
        request.form.get('host') or '',
        request.form.get('port') or '',
        request.form.get('database') or '',
        request.form.get('user') or '',
        request.form.get('password') or '',
    )


def _current_db_label():
    """当前数据库的展示信息（方言 + 主机/库名，不含凭据）。"""
    url = db.engine.url
    name = url.drivername
    where = url.host or url.database or ''
    return '{0}（{1}）'.format(name, where) if where else name


@admin_bp.route('/db-migrator', methods=['GET'])
@_gate
@permission_required('db_migrator:manage')
def db_migrator_index():
    """迁移页面：展示当前库信息 + 目标库连接表单。"""
    return render_template(
        'db_migrator/index.html',
        db_types=DB_TYPES,
        current_db=_current_db_label(),
    )


@admin_bp.route('/db-migrator/test', methods=['POST'])
@_gate
@permission_required('db_migrator:manage')
def db_migrator_test():
    """测试目标库连接（页面 AJAX 调用，返回 JSON）。"""
    try:
        uri = _build_target_uri()
    except ValueError as e:
        return jsonify({'ok': False, 'message': str(e)})
    ok, message = test_connection(uri)
    return jsonify({'ok': ok, 'message': message})


@admin_bp.route('/db-migrator/migrate', methods=['POST'])
@_gate
@permission_required('db_migrator:manage')
def db_migrator_migrate():
    """执行迁移（同步请求；CMS 规模数据量秒级完成）。"""
    try:
        uri = _build_target_uri()
    except ValueError as e:
        flash(_gettext('数据库连接信息有误：{0}').format(e), 'danger')
        return redirect(url_for('admin.db_migrator_index'))

    db_type = (request.form.get('db_type') or '').strip().lower()
    overwrite = request.form.get('overwrite') == 'on'
    switch_now = request.form.get('switch_now') == 'on'

    # 先确认目标库可达，避免建表/迁移中途才报连接错误
    ok, message = test_connection(uri)
    if not ok:
        flash(_gettext('目标数据库连接失败：{0}').format(message), 'danger')
        return redirect(url_for('admin.db_migrator_index'))

    try:
        result = run_migration(uri, overwrite=overwrite)
    except MigrationError as e:
        flash(_gettext('迁移失败：{0}').format(e), 'danger')
        return redirect(url_for('admin.db_migrator_index'))
    except Exception as e:  # noqa: BLE001
        current_app.logger.exception('数据库迁移失败')
        flash(_gettext('迁移失败：{0}').format(e), 'danger')
        return redirect(url_for('admin.db_migrator_index'))

    tables = len(result['tables'])
    rows = result['total_rows']
    audit_log(OP_CONFIG_CHANGE, AUDIT_MODULE, None, '数据库迁移', {
        'action': 'migrate', 'db_type': db_type,
        'tables': tables, 'rows': rows,
        'overwrite': overwrite, 'switch_now': switch_now,
    })

    # 落盘 db_config.json（下次启动自动使用新库；删除该文件即可放弃）
    save_db_config(db_type, uri, meta={
        'host': request.form.get('host'),
        'port': request.form.get('port'),
        'database': request.form.get('database'),
        'user': request.form.get('user'),
    })

    if not switch_now:
        flash(_gettext(
            '迁移完成：{0} 张表 / {1} 行数据已写入目标库，且配置已保存。'
            '重启应用后即使用新数据库；如需放弃，删除 instance/db_config.json 即可。'
        ).format(tables, rows), 'success')
        return redirect(url_for('admin.db_migrator_index'))

    # 勾选「立即切换」：热切换引擎免重启（切换失败自动回滚配置继续用旧库）
    old_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI')
    try:
        switch_engine(current_app, db, uri)
    except Exception:  # noqa: BLE001
        clear_db_config()
        try:
            switch_engine(current_app, db, old_uri)
        except Exception:  # noqa: BLE001
            pass
        current_app.logger.exception('切换到新数据库失败')
        flash(_gettext('数据迁移成功，但引擎切换失败：请重启应用以使用新数据库'), 'warning')
        return redirect(url_for('admin.db_migrator_index'))
    # 清整站缓存（旧库数据的整页缓存已全部失效）
    try:
        from app.extensions import cache
        cache.clear()
    except Exception:  # noqa: BLE001
        pass
    flash(_gettext(
        '迁移完成：{0} 张表 / {1} 行数据已写入新库，应用已即时切换到新数据库，'
        '无需重启（旧库文件保留作为备份）。'
    ).format(tables, rows), 'success')
    return redirect(url_for('admin.db_migrator_index'))
