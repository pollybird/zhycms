"""轮播图插件：演示数据（manufacturing / service）。

仅生成「home-hero」演示分组与 3 张外链演示图（项目自带演示图路径）；
generate 前先清理本插件的同名分组，保证重复生成幂等（防 slug 唯一约束冲突）。
"""
from datetime import datetime

from app.extensions import db

from .models import BannerGroup, Banner

_DEMO_IMG = '/static/uploads/demo'


def generate(industry):
    # 幂等：先清理本插件演示分组（items 级联删除）
    for g in BannerGroup.query.filter_by(slug='home-hero').all():
        db.session.delete(g)
    db.session.flush()

    if industry == 'service':
        name, remark = '首页横幅', '服务业演示数据'
        imgs = [
            ('专业服务团队', f'{_DEMO_IMG}/svc_team.jpg'),
            ('高效办公协作', f'{_DEMO_IMG}/svc_office.jpg'),
            ('客户会议洽谈', f'{_DEMO_IMG}/svc_meeting.jpg'),
        ]
    elif industry == 'manufacturing_en':
        name, remark = 'Home Hero', 'Manufacturing demo (EN)'
        imgs = [
            ('Modern Production Workshop', f'{_DEMO_IMG}/mfg_workshop.jpg'),
            ('Smart Factory Overview', f'{_DEMO_IMG}/mfg_factory.jpg'),
            ('Featured Products', f'{_DEMO_IMG}/mfg_product_a.jpg'),
        ]
    else:
        name, remark = '首页大图', '制造业演示数据'
        imgs = [
            ('现代化生产车间', f'{_DEMO_IMG}/mfg_workshop.jpg'),
            ('智慧工厂全景', f'{_DEMO_IMG}/mfg_factory.jpg'),
            ('核心产品展示', f'{_DEMO_IMG}/mfg_product_a.jpg'),
        ]

    group = BannerGroup(name=name, slug='home-hero', remark=remark,
                        is_enabled=True,
                        created_at=datetime.now(), updated_at=datetime.now())
    db.session.add(group)
    db.session.flush()
    now = datetime.now()
    for i, (title, url) in enumerate(imgs):
        db.session.add(Banner(
            group_id=group.id, title=title, external_url=url,
            link_url='', link_target='_self',
            sort_order=30 - i * 10, is_enabled=True,
            created_at=now, updated_at=now))
    db.session.commit()
