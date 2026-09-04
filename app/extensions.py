from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_caching import Cache
from flask_babel import Babel, lazy_gettext
from flask_migrate import Migrate

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'admin_auth.login'
login_manager.login_message = lazy_gettext('请先登录后再访问该页面')
login_manager.login_message_category = 'warning'

# 模块8：全站缓存（默认用 SimpleCache，生产环境可在 config 切 Redis/Filesystem）
cache = Cache()

# v2.3.0：国际化（Flask-Babel）。init_app 时传入 locale_selector；默认关闭
# （i18n_enable=0）时 localeselector 直接返回默认中文，全站渲染与 v2.2.0 一致
babel = Babel()

# v2.4.0：数据库迁移（Flask-Migrate / Alembic）
migrate = Migrate()

# 调度器（APScheduler）在 app/__init__.py 中延迟初始化，避免与多进程环境冲突
_scheduler_instance = {'scheduler': None}


def get_scheduler():
    """返回全局 scheduler 实例（懒加载）。"""
    return _scheduler_instance['scheduler']


def set_scheduler(sched):
    _scheduler_instance['scheduler'] = sched
