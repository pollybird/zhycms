"""教程插件：演示数据。

教育行业（education）生成示例分类与教程；其它行业暂不生成（避免污染
制造业/服务业演示数据）。生成前清理本插件全部数据，保证幂等。
"""
from datetime import datetime, timedelta

from app.extensions import db

from .models import TutorialCategory, Tutorial


def generate(industry):
    # 幂等：清理本插件全部数据
    Tutorial.query.delete()
    TutorialCategory.query.delete()
    db.session.flush()

    if industry != 'education':
        # 非教育行业不生成教程演示数据
        db.session.commit()
        return

    now = datetime.now()

    # 分类
    cat_programming = TutorialCategory(
        name='编程启蒙', slug='programming',
        description='Scratch 图形化编程与 Python 基础',
        sort_order=100, is_enabled=True)
    cat_english = TutorialCategory(
        name='英语口语', slug='oral-english',
        description='外教口语与听力训练',
        sort_order=90, is_enabled=True)
    cat_math = TutorialCategory(
        name='数学思维', slug='math-thinking',
        description='逻辑思维与奥数启蒙',
        sort_order=80, is_enabled=True)
    db.session.add_all([cat_programming, cat_english, cat_math])
    db.session.flush()

    tutorials = [
        Tutorial(
            category_id=cat_programming.id,
            title='Scratch 入门：让小猫动起来',
            slug='scratch-getting-started',
            summary='从零开始学习 Scratch 图形化编程，制作第一个动画',
            content='<p>本教程带你认识 Scratch 编程界面，学习运动、外观、事件等基础积木，'
                    '完成一个让小猫在舞台上移动并说话的动画作品。</p>'
                    '<h3>学习目标</h3><ul><li>认识 Scratch 界面</li>'
                    '<li>掌握运动与外观积木</li><li>理解事件触发机制</li></ul>',
            difficulty='beginner', duration=45, sort_order=100,
            is_enabled=True, view_count=128,
            created_at=now - timedelta(days=5)),
        Tutorial(
            category_id=cat_programming.id,
            title='Python 青少年编程：变量与循环',
            slug='python-variables-loops',
            summary='Python 基础语法：变量、数据类型、for/while 循环',
            content='<p>本教程介绍 Python 编程语言的基础概念，包括变量、数据类型、'
                    '条件判断与循环结构，通过趣味示例培养编程思维。</p>',
            difficulty='intermediate', duration=60, sort_order=90,
            is_enabled=True, view_count=96,
            created_at=now - timedelta(days=3)),
        Tutorial(
            category_id=cat_english.id,
            title='日常英语口语：自我介绍',
            slug='english-self-introduction',
            summary='学习地道的自我介绍表达，掌握常用句型',
            content='<p>本课程通过情景对话，教你如何用英语做自然流畅的自我介绍，'
                    '涵盖姓名、年龄、爱好、家庭等常用表达。</p>',
            difficulty='beginner', duration=30, sort_order=100,
            is_enabled=True, view_count=210,
            created_at=now - timedelta(days=7)),
        Tutorial(
            category_id=cat_english.id,
            title='英语听力训练：校园生活话题',
            slug='english-listening-campus',
            summary='围绕校园生活场景的听力练习，提升听力理解能力',
            content='<p>选取真实校园对话素材，训练听力理解与关键信息抓取能力，'
                    '配套词汇讲解与跟读练习。</p>',
            difficulty='intermediate', duration=50, sort_order=90,
            is_enabled=True, view_count=154,
            created_at=now - timedelta(days=2)),
        Tutorial(
            category_id=cat_math.id,
            title='数学思维训练：找规律',
            slug='math-pattern-finding',
            summary='通过数列与图形规律培养逻辑推理能力',
            content='<p>本教程通过趣味数学题，引导孩子观察、归纳、推理，'
                    '发现数列与图形中的规律，培养逻辑思维能力。</p>',
            difficulty='beginner', duration=40, sort_order=100,
            is_enabled=True, view_count=176,
            created_at=now - timedelta(days=4)),
        Tutorial(
            category_id=cat_math.id,
            title='奥数启蒙：巧算与速算',
            slug='math-speed-calculation',
            summary='学习巧算方法，提升计算速度与准确性',
            content='<p>介绍凑整、拆分、基准数等巧算技巧，通过大量练习'
                    '提升孩子的计算速度与心算能力。</p>',
            difficulty='intermediate', duration=55, sort_order=90,
            is_enabled=True, view_count=132,
            created_at=now - timedelta(days=1)),
    ]
    db.session.add_all(tutorials)
    db.session.commit()
