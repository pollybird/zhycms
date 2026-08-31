"""友情链接插件：演示数据（manufacturing / service）。

沿用核心演示数据的链接内容；generate 前先清理本插件全部数据，
保证重复生成幂等（替代核心 _clean_demo_data 原有的 FriendLink 清理）。
"""
from datetime import datetime

from app.extensions import db

from .models import FriendLink

_DEMO_LINKS = {
    'service': [
        ('中国管理咨询网', 'https://www.mckinsey.com.cn/'),
        ('中国企业联合会', 'https://www.cec-ceda.org.cn/'),
        ('人力资源市场', 'https://www.zhaopin.com/'),
    ],
    'manufacturing': [
        ('工业和信息化部', 'https://www.miit.gov.cn/'),
        ('国家市场监督管理总局', 'https://www.samr.gov.cn/'),
        ('中国机械工业联合会', 'https://www.cmif.org.cn/'),
    ],
}


def generate(industry):
    # 幂等：先清理本插件全部数据
    FriendLink.query.delete()
    db.session.flush()

    now = datetime.now()
    links = []
    for i, (name, url) in enumerate(_DEMO_LINKS.get(industry, _DEMO_LINKS['manufacturing'])):
        links.append(FriendLink(
            name=name, url=url, target='_blank',
            sort_order=100 - i * 10, is_enabled=True,
            created_at=now, updated_at=now))
    db.session.add_all(links)
    db.session.commit()
