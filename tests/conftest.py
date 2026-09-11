"""Pytest 公共 fixture（v2.6.0）。

隔离策略：
  - SQLite 临时库（ZHYCMS_DB_URI 环境变量），每个测试 session 共享一个库；
  - 临时 instance 目录（搜索索引、上传文件、备份均指向临时路径）；
  - TESTING 模式关闭 APScheduler、邮件发送；
  - 搜索索引根目录 monkeypatch 到临时目录。

用法：
  client       → 未登录测试客户端
  admin_client → 超管登录的客户端（session 注入，绕验证码）
  app          → Flask 应用实例
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 确保项目根目录在 PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 测试环境变量（在 import app 之前设置）
_TMP_INSTANCE = tempfile.mkdtemp(prefix='zhycms_test_instance_')
_TMP_DB = os.path.join(_TMP_INSTANCE, 'test.db')
os.environ['ZHYCMS_DB_URI'] = f'sqlite:///{_TMP_DB}'
os.environ['ZHYCMS_ENV'] = 'testing'  # 不触发 ProductionConfig
os.environ.setdefault('ZHYCMS_SECRET_KEY', 'test-secret-key-for-pytest-only')

# 搜索索引隔离
_SEARCH_INDEX_DIR = os.path.join(_TMP_INSTANCE, 'search_index')
os.makedirs(_SEARCH_INDEX_DIR, exist_ok=True)


@pytest.fixture(scope='session')
def app():
    """创建测试应用（session 级单例）。"""
    from app import create_app
    from app.extensions import db

    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{_TMP_DB}'

    # 搜索索引根目录隔离
    import app.utils.search as search_mod
    search_mod._get_index_root = lambda: _SEARCH_INDEX_DIR

    # 种子数据放在独立 context 中完成并**及时关闭**：
    # Flask RequestContext.push() 会复用同 app 的活动 app context，
    # 若 fixture 跨 yield 持有 context，整个测试 session 的请求将共享
    # 同一个 g，flask-login 的 g._login_user 会被首个请求永久缓存，
    # 导致 session 注入式登录（_user_id）在第二次起全部失效。
    with app.app_context():
        db.create_all()
        # 种子数据（先建权限点，再建角色，保证角色-权限关联可 join）
        from app.models.rbac import Permission, Role
        from app.models.setting import Setting
        from app.models.user import User
        Permission.ensure_presets()
        Role.ensure_presets()
        Setting.set('site_initialized', '1')
        Setting.set('i18n_enable', '0')
        # 超管用户
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', is_super=True, is_deleted=False)
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
    yield app

    # 清理
    import shutil
    shutil.rmtree(_TMP_INSTANCE, ignore_errors=True)


@pytest.fixture
def client(app):
    """未登录测试客户端。"""
    return app.test_client()


@pytest.fixture
def admin_client(app, client):
    """超管登录的客户端（绕验证码，直接 session 注入）。"""
    from app.extensions import db
    from app.models.user import User

    with app.app_context():
        admin = User.query.filter_by(username='admin', is_deleted=False).first()
        uid = str(admin.id)

    with client.session_transaction() as sess:
        sess['_user_id'] = uid
        sess['_fresh'] = True

    return client


@pytest.fixture(autouse=True)
def _reset_db(app):
    """每用例后回滚未提交的事务，保持 DB 干净。"""
    yield
    from app.extensions import db
    with app.app_context():
        db.session.rollback()


@pytest.fixture
def db_session(app):
    """每用例独立事务回滚（快速隔离，不互相污染）。"""
    from app.extensions import db
    with app.app_context():
        yield db.session
        db.session.rollback()
