"""审计日志清理端点测试（v3.1.1 线上回归）。

历史缺陷：前端表单字段名 days，后端读 keep_days，用户选择的清理范围
被无视、永远按 Setting 默认 90 天清理；「清空全部」(days=0) 未处理。

断言按 username='tester' 过滤：清理动作本身会再写一条审计记录（操作人
admin），且 SQLite 删尾后 rowid 会复用，不能按裸 id 判断存在性。
"""
from datetime import datetime, timedelta

import pytest

from app.extensions import db
from app.models.audit import AuditLog

MARK = 'tester'


def _purge(app):
    """用例起始清空审计表，隔离用例间干扰。"""
    with app.app_context():
        db.session.query(AuditLog).delete(synchronize_session=False)
        db.session.commit()


def _seed(app, days_ago):
    with app.app_context():
        log = AuditLog(op_type='batch', module='audit', username=MARK,
                       created_at=datetime.now() - timedelta(days=days_ago))
        db.session.add(log)
        db.session.commit()
        return log.id


def _mark_ids(app):
    """当前 username=MARK 的行 id 集合（排除清理动作自身的审计行）。"""
    with app.app_context():
        return {r.id for r in
                AuditLog.query.filter_by(username=MARK).all()}


@pytest.mark.audit
class TestAuditClean:

    def test_clear_all(self, app, admin_client):
        """days=0 → 清空全部，提示语为「已清空全部」。"""
        _purge(app)
        _seed(app, 3650)
        _seed(app, 100)
        _seed(app, 1)
        resp = admin_client.post('/admin/audit-logs/clean',
                                 follow_redirects=True, data={'days': '0'})
        assert '已清空全部审计日志，共删除 3 条记录' in resp.get_data(as_text=True)
        assert _mark_ids(app) == set()

    def test_respects_selected_days(self, app, admin_client):
        """字段名 days 必须生效（此前被无视，永远按默认 90 天）。"""
        _purge(app)
        old = _seed(app, 60)    # 60 天前：days=30 应删，默认 90 则保留
        recent = _seed(app, 1)
        resp = admin_client.post('/admin/audit-logs/clean',
                                 follow_redirects=True, data={'days': '30'})
        assert '已清理 30 天前的审计日志，共删除 1 条记录' in resp.get_data(as_text=True)
        ids = _mark_ids(app)
        assert old not in ids
        assert recent in ids

    def test_missing_field_falls_back_to_setting(self, app, admin_client):
        """不带字段 → 按 Setting 默认 90 天清理（保留 60 天前的记录）。"""
        _purge(app)
        kept = _seed(app, 60)
        dropped = _seed(app, 120)
        resp = admin_client.post('/admin/audit-logs/clean',
                                 follow_redirects=True, data={})
        assert '已清理 90 天前的审计日志，共删除 1 条记录' in resp.get_data(as_text=True)
        ids = _mark_ids(app)
        assert kept in ids and dropped not in ids

    def test_negative_rejected(self, app, admin_client):
        _purge(app)
        resp = admin_client.post('/admin/audit-logs/clean',
                                 follow_redirects=True, data={'days': '-5'})
        assert '保留天数必须为非负整数' in resp.get_data(as_text=True)
