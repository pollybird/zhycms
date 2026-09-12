"""初始化数据库默认数据与演示内容。

支持两套演示数据：
- generate_demo_data('manufacturing') 制造业演示数据
- generate_demo_data('service')        服务业演示数据

所有公司名称、品牌名称均为虚构，与现实企业无关。
"""
from datetime import datetime, timedelta

from ..extensions import db
from ..models.user import User
from ..models.setting import Setting
from ..models.column import Column, ColumnField, ColumnFieldValue
from ..models.article import Article, ArticleFieldValue
from ..models.fragment import Fragment, FragmentGroup
# 自定义表单 v2.3.0 起转为内置插件 plugins/form，演示数据由插件 demo.py 钩子生成


# 演示图片根路径（/static/uploads/demo/ 下的文件）
_DEMO_IMG = '/static/uploads/demo'


def init_default_settings():
    """初始化默认站点配置（不创建管理员）。"""
    for key, value in Setting.DEFAULTS.items():
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(key=key, value=str(value), description=key))
    # 标记为新装站点：v2.2/v2.3 升级兼容逻辑（create_app 中老站自动启用
    # 友情链接/自定义表单插件）仅对没有本标记的已初始化站点生效
    Setting.set('friend_link_plugin_migrated', '1')
    Setting.set('form_plugin_migrated', '1')
    db.session.commit()


def create_admin(username, password, nickname='超级管理员'):
    """创建第一个管理员账号（超级管理员），并分配 RBAC 超级管理员角色。"""
    if User.query.filter_by(is_deleted=False).first():
        return None
    admin = User(
        username=username,
        nickname=nickname,
        email='',
        is_super=True,   # 兜底全权限
        is_active_flag=True,
    )
    admin.set_password(password)
    db.session.add(admin)
    db.session.flush()

    # 确保 RBAC 预设已写入（首次初始化不一定触发 app/__init__.py 的 ensure_presets）
    from app.models import rbac as _rbac_mod
    try:
        _rbac_mod.Permission.ensure_presets()
        _rbac_mod.Role.ensure_presets()
        db.session.flush()
    except Exception:
        db.session.rollback()

    # 给首个管理员绑定 super_admin 角色
    try:
        super_role = _rbac_mod.Role.get_by_code(_rbac_mod.ROLE_SUPER_ADMIN)
        if super_role:
            from app.models.rbac import UserRole
            ur = UserRole.query.filter_by(user_id=admin.id, role_id=super_role.id).first()
            if not ur:
                db.session.add(UserRole(user_id=admin.id, role_id=super_role.id))
    except Exception:
        db.session.rollback()

    db.session.commit()
    return admin


def generate_demo_data(industry='manufacturing'):
    """生成演示数据。

    industry: 'manufacturing' 制造业 / 'service' 服务业
              'manufacturing_en' 英文制造业
              'education' 教育行业（v2.6.3）
              'catering' 餐饮行业（v2.6.3）
    """
    _clean_demo_data()
    if industry == 'service':
        _generate_service_demo()
    elif industry == 'manufacturing_en':
        _generate_manufacturing_demo_en()
    elif industry == 'education':
        _generate_education_demo()
    elif industry == 'catering':
        _generate_catering_demo()
    else:
        _generate_manufacturing_demo()


def _clean_demo_data():
    """清理旧的演示数据（栏目/文章/碎片），保留用户与站点设置。

    友情链接/自定义表单改由对应插件演示数据钩子负责清理与重建。
    """
    # 按外键依赖顺序删除
    ArticleFieldValue.query.delete()
    Article.query.delete()
    ColumnFieldValue.query.delete()
    ColumnField.query.delete()
    Column.query.delete()
    Fragment.query.delete()
    FragmentGroup.query.delete()
    db.session.commit()


# ============================================================
# 制造业演示数据：虚构企业「瑞景精工有限公司」
# ============================================================

def _generate_manufacturing_demo():
    """制造业演示数据：精密机械制造企业。"""
    now = datetime.now()

    company = '瑞景精工有限公司'
    brand = '瑞景精工'

    # 更新站点设置：site_name/footer_copyright 为前台“网站名称/企业版权”，写入企业信息。
    # 后台的 CMS 名称与版权由 Setting.CMS_NAME / CMS_COPYRIGHT 固定，不受此处影响。
    Setting.set('site_name', company)
    Setting.set('site_subtitle', '专注精密机械制造二十余年')
    Setting.set('footer_copyright', f'版权所有 © {company}')
    Setting.set('site_theme', 'manufacturing')
    Setting.set('seo_title', f'{brand} - 精密机械制造专家')
    Setting.set('seo_keywords', '精密机械,零部件加工,自动化设备,智能制造')
    Setting.set('seo_description', f'{brand}专注于精密机械零部件研发与制造，提供自动化设备与一站式解决方案。')

    # ============ 栏目结构 ============
    about = Column(name='关于我们', slug='about', type='page', sort_order=100,
                   is_enabled=True, parent_mode='first_child',
                   summary=f'了解{brand}的发展历程与企业理念',
                   page_content=_mfg_about_content())
    db.session.add(about)

    news = Column(name='新闻中心', slug='news', type='list', sort_order=90,
                  is_enabled=True, parent_mode='first_child',
                  summary='企业新闻与行业动态', page_size=10)
    db.session.add(news)

    company_news = Column(name='公司新闻', slug='company-news', type='list',
                          parent_id=None, sort_order=95, is_enabled=True,
                          parent_mode='first_child', page_size=10,
                          summary='公司内部新闻动态')
    industry_news = Column(name='行业动态', slug='industry-news', type='list',
                           parent_id=None, sort_order=90, is_enabled=True,
                           parent_mode='first_child', page_size=10,
                           summary='行业前沿资讯')
    db.session.add_all([company_news, industry_news])
    db.session.flush()
    company_news.parent_id = news.id
    industry_news.parent_id = news.id

    products = Column(name='产品中心', slug='products', type='list', sort_order=80,
                      is_enabled=True, parent_mode='list_children',
                      summary='我们的产品与解决方案', page_size=12)
    db.session.add(products)

    precision_parts = Column(name='精密零部件', slug='precision-parts', type='list',
                             sort_order=95, is_enabled=True,
                             parent_mode='first_child', page_size=12,
                             summary='高精度机械零部件')
    automation = Column(name='自动化设备', slug='automation', type='list',
                        sort_order=90, is_enabled=True,
                        parent_mode='first_child', page_size=12,
                        summary='工业自动化设备与生产线')
    db.session.add_all([precision_parts, automation])
    db.session.flush()
    precision_parts.parent_id = products.id
    automation.parent_id = products.id

    service = Column(name='服务支持', slug='service', type='page', sort_order=70,
                     is_enabled=True, parent_mode='first_child',
                     summary='专业的技术服务与售后支持',
                     page_content=_mfg_service_content())
    db.session.add(service)

    contact = Column(name='联系我们', slug='contact', type='page', sort_order=60,
                     is_enabled=True, parent_mode='first_child',
                     summary='联系方式与地址信息',
                     page_content=_mfg_contact_content())
    db.session.add(contact)

    db.session.flush()

    # ============ 公司新闻文章 ============
    _add_article(company_news, f'{brand}通过ISO 9001质量管理体系认证',
                 f'近日，{company}正式通过ISO 9001:2015质量管理体系认证，标志着公司在质量管理方面获得权威认可。',
                 _mfg_news_content_1(), now - timedelta(days=2), sort_order=100,
                 cover=f'{_DEMO_IMG}/mfg_news1.jpg')
    _add_article(company_news, '我司新增五轴加工中心，产能提升40%',
                 '为满足日益增长的客户订单需求，公司新引进两台五轴联动加工中心，产能进一步提升。',
                 _mfg_news_content_2(), now - timedelta(days=5), sort_order=90,
                 cover=f'{_DEMO_IMG}/mfg_news2.jpg')
    _add_article(company_news, '2026年度技术交流大会圆满召开',
                 '本次大会以"精益制造·智造未来"为主题，全体员工共同探讨技术发展方向。',
                 _mfg_news_content_3(), now - timedelta(days=10), sort_order=80,
                 cover=f'{_DEMO_IMG}/mfg_news3.jpg')

    # ============ 行业动态文章 ============
    _add_article(industry_news, '工信部发布智能制造发展规划（2026-2030）',
                 '工业和信息化部近日发布智能制造发展规划，提出多项支持政策。',
                 _mfg_industry_content_1(), now - timedelta(days=3), sort_order=100)
    _add_article(industry_news, '工业4.0浪潮下，中小企业如何迈向智能制造',
                 '随着工业4.0的深入推进，越来越多的制造企业开始探索智能化转型路径。',
                 _mfg_industry_content_2(), now - timedelta(days=7), sort_order=90)
    _add_article(industry_news, '高端装备制造业保持稳健增长态势',
                 '根据最新市场研究报告，高端装备制造业保持稳健增长态势。',
                 _mfg_industry_content_3(), now - timedelta(days=12), sort_order=80)

    # ============ 精密零部件文章 ============
    _add_article(precision_parts, '高精度主轴',
                 '适用于数控机床的高精度主轴，回转精度≤0.003mm。',
                 _mfg_product_shaft(), now - timedelta(days=1), sort_order=100,
                 cover=f'{_DEMO_IMG}/mfg_product_a.jpg')
    _add_article(precision_parts, '精密齿轮组件',
                 '采用优质合金钢材料，经过渗碳淬火工艺，传动平稳、噪音低。',
                 _mfg_product_gear(), now - timedelta(days=4), sort_order=90,
                 cover=f'{_DEMO_IMG}/mfg_product_b.jpg')

    # ============ 自动化设备文章 ============
    _add_article(automation, '自动化装配生产线',
                 '为电子、汽车零部件等行业定制的自动化装配生产线。',
                 _mfg_product_line(), now - timedelta(days=2), sort_order=100,
                 cover=f'{_DEMO_IMG}/mfg_factory.jpg')
    _add_article(automation, '工业机器人工作站',
                 '六轴工业机器人工作站，支持焊接、搬运、码垛等多种工艺。',
                 _mfg_product_robot(), now - timedelta(days=6), sort_order=90,
                 cover=f'{_DEMO_IMG}/mfg_workshop.jpg')

    # ============ 碎片 ============
    _mfg_init_fragments(company, brand)

    db.session.commit()


# ============ 制造业内容 ============

def _mfg_about_content():
    return '''<p>瑞景精工有限公司成立于2003年，是一家专注于精密机械零部件研发与制造的高新技术企业，总部位于长三角制造业核心区域。</p>
<h3>公司简介</h3>
<p>瑞景精工致力于为装备制造、汽车工业、电子信息等行业提供高品质的精密零部件与自动化解决方案。公司占地3万平方米，拥有现代化恒温车间与完善的检测中心，员工300余人，其中技术研发团队40余人。</p>
<h3>企业文化</h3>
<p>我们秉承"精益求精·匠心制造"的理念，以品质为生命，以创新为动力，持续为客户创造价值。</p>
<h3>业务范围</h3>
<ul>
  <li>精密机械零部件加工（CNC车铣、五轴加工）</li>
  <li>工业自动化设备研发与集成</li>
  <li>非标定制装备设计与制造</li>
  <li>机械装配与测试服务</li>
  <li>技术咨询服务</li>
</ul>
<h3>企业愿景</h3>
<p>成为国内领先的精密制造解决方案提供商，助力中国制造业转型升级。</p>'''


def _mfg_service_content():
    return '''<h3>服务承诺</h3>
<p>我们提供 7×24 小时技术支持服务，承诺工作时间内 2 小时响应，紧急问题 4 小时内提供解决方案。</p>
<h3>服务内容</h3>
<ul>
  <li><strong>售前咨询</strong>：根据客户需求提供专业选型建议与方案设计</li>
  <li><strong>售中支持</strong>：全程跟踪订单进度，提供技术交底</li>
  <li><strong>售后维护</strong>：设备安装调试、操作培训、定期回访</li>
  <li><strong>备件供应</strong>：长期供应原厂备件，保证设备稳定运行</li>
  <li><strong>技术升级</strong>：根据工艺发展提供设备升级方案</li>
</ul>
<h3>联系方式</h3>
<p>技术服务热线：400-888-8888<br>
服务邮箱：service@ruijing-jinggong.com</p>'''


def _mfg_contact_content():
    return '''<h3>联系我们</h3>
<p><strong>公司名称：</strong>瑞景精工有限公司</p>
<p><strong>地　　址：</strong>江苏省苏州市工业园区XX路XX号</p>
<p><strong>电　　话：</strong>0512-88888888</p>
<p><strong>传　　真：</strong>0512-88888889</p>
<p><strong>服务热线：</strong>400-888-8888</p>
<p><strong>邮　　箱：</strong>contact@ruijing-jinggong.com</p>
<p><strong>邮　　编：</strong>215000</p>
<p><strong>工作时间：</strong>周一至周五 8:30-17:30</p>'''


def _mfg_news_content_1():
    return f'''<p>近日，经权威认证机构审核，瑞景精工有限公司正式通过 ISO 9001:2015 质量管理体系认证，标志着公司在质量管理方面获得权威认可。</p>
<p>ISO 9001 是国际通用的质量管理体系标准，其认证过程严格审核企业的设计开发、采购、生产、检验、销售服务等全过程。此次获评，是瑞景精工长期坚持质量第一方针的成果。</p>
<p>公司负责人表示，将以此次认证为契机，持续完善质量管理体系，为客户提供更优质的产品与服务。</p>'''


def _mfg_news_content_2():
    return '''<p>为满足日益增长的客户订单需求，公司近期新引进两台进口五轴联动加工中心，进一步提升了复杂零部件的加工能力。</p>
<p>新设备具备高刚性、高精度特点，可一次装夹完成多面加工，显著提升加工效率与一致性。投产后，公司精密零部件产能预计提升40%。</p>
<p>这是公司2026年度产能扩充计划的重要一步，未来还将根据市场需求持续投入先进设备。</p>'''


def _mfg_news_content_3():
    return '''<p>瑞景精工2026年度技术交流大会在总部圆满召开，本次大会以"精益制造·智造未来"为主题，全体员工参加了此次活动。</p>
<p>大会回顾了过去一年公司取得的成绩，并对优秀团队和个人进行了表彰。技术部门负责人分享了精密加工领域的前沿趋势，多个项目团队进行了工艺改进案例分享。</p>
<p>公司总经理在总结发言中明确了新一年的发展方向，鼓励全体员工继续以技术创新为核心，为客户创造更大价值。</p>'''


def _mfg_industry_content_1():
    return '''<p>近日，工业和信息化部正式发布《智能制造发展规划（2026-2030年）》，提出到2030年实现制造业数字化、网络化、智能化全面普及的目标。</p>
<p>规划明确提出多项支持政策，包括加大技改投入、鼓励智能制造装备研发、推动工业互联网应用、加强人才培养等。规划特别强调要支持中小企业智能化改造，鼓励专业服务商提供整体解决方案。</p>
<p>业内专家表示，该规划的发布将为装备制造业带来新的发展机遇，尤其是高端装备与精密制造领域前景广阔。</p>'''


def _mfg_industry_content_2():
    return '''<p>随着工业4.0的深入推进，越来越多的制造企业开始探索智能化转型路径。智能制造已成为提升企业竞争力的关键。</p>
<p>目前，智能制造在中小企业中的应用场景主要包括：数字化车间、智能产线、设备远程监控、质量追溯等。通过智能化改造，企业可以显著提升生产效率，降低运营成本。</p>
<p>专家指出，中小企业在智能制造转型方面面临资金、人才等挑战，建议分阶段实施，优先选择回报周期短的项目。</p>'''


def _mfg_industry_content_3():
    return '''<p>根据最新发布的市场研究报告，高端装备制造业保持稳健增长态势，成为制造业转型升级的重要支撑。</p>
<p>报告显示，2025年高端装备制造业增加值同比增长超过10%，其中工业机器人、数控机床、自动化生产线等细分领域表现亮眼。政策支持与市场需求双轮驱动，行业景气度持续提升。</p>
<p>对于精密零部件制造企业而言，高端装备的快速发展意味着更多配套机会与更高技术要求。</p>'''


def _mfg_product_shaft():
    return '''<h3>产品简介</h3>
<p>高精度主轴是数控机床的核心部件，采用优质合金钢材料，经过精密磨削与动平衡校正，回转精度≤0.003mm。</p>
<h3>技术参数</h3>
<ul>
  <li>主轴直径：φ40 - φ200mm（可定制）</li>
  <li>回转精度：≤0.003mm</li>
  <li>径向跳动：≤0.005mm</li>
  <li>最高转速：8000 rpm</li>
  <li>表面粗糙度：Ra 0.4</li>
  <li>动平衡等级：G2.5</li>
</ul>
<h3>应用领域</h3>
<p>广泛应用于数控车床、加工中心、磨床等精密机床，以及精密测量设备。</p>'''


def _mfg_product_gear():
    return '''<h3>产品简介</h3>
<p>精密齿轮组件采用优质合金钢材料，经过渗碳淬火工艺，齿轮精度可达 GB/T 10095 5级，传动平稳、噪音低、寿命长。</p>
<h3>技术参数</h3>
<ul>
  <li>模数：1 - 8（可定制）</li>
  <li>齿轮精度：5级（GB/T 10095）</li>
  <li>材料：20CrMnTi / 42CrMo</li>
  <li>热处理：渗碳淬火 HRC58-62</li>
  <li>表面处理：喷丸、磷化等可选</li>
</ul>
<h3>应用领域</h3>
<p>适用于工业机器人、精密减速机、自动化生产线、机床传动系统等场景。</p>'''


def _mfg_product_line():
    return '''<h3>产品简介</h3>
<p>自动化装配生产线为电子、汽车零部件等行业定制设计，集成上料、装配、检测、下料等工序，实现全自动化生产。</p>
<h3>系统特点</h3>
<ul>
  <li>模块化设计，可根据工艺灵活组合</li>
  <li>配备视觉检测系统，保证装配质量</li>
  <li>支持多品种切换，柔性化生产</li>
  <li>节拍时间可低至 3 秒/件</li>
  <li>集成 MES 系统，实现生产数据追溯</li>
</ul>
<h3>应用案例</h3>
<p>已成功应用于汽车传感器装配、电子连接器装配、家电控制器装配等多个领域。</p>'''


def _mfg_product_robot():
    return '''<h3>产品简介</h3>
<p>六轴工业机器人工作站支持焊接、搬运、码垛、涂胶等多种工艺，可根据客户工艺需求定制末端执行器与工装夹具。</p>
<h3>技术规格</h3>
<ul>
  <li>负载：10kg - 200kg 可选</li>
  <li>臂展：1.4m - 3.1m 可选</li>
  <li>重复定位精度：±0.05mm</li>
  <li>支持离线编程与示教编程</li>
  <li>集成安全防护系统</li>
</ul>
<h3>应用场景</h3>
<p>汽车制造、金属加工、电子装配、物流仓储等行业。</p>'''


def _mfg_init_fragments(company, brand):
    """初始化碎片数据（制造业）。"""
    grp_contact = FragmentGroup(name='联系方式', sort_order=100)
    grp_home = FragmentGroup(name='首页内容', sort_order=90)
    db.session.add_all([grp_contact, grp_home])
    db.session.flush()

    fragments = [
        Fragment(name='客服电话', slug='contact_phone', group_id=grp_contact.id,
                 field_type='text', value='400-888-8888', sort_order=100, is_enabled=True),
        Fragment(name='客服邮箱', slug='contact_email', group_id=grp_contact.id,
                 field_type='text', value='contact@ruijing-jinggong.com', sort_order=90, is_enabled=True),
        Fragment(name='公司地址', slug='contact_address', group_id=grp_contact.id,
                 field_type='textarea',
                 value='江苏省苏州市工业园区XX路XX号', sort_order=80, is_enabled=True),
        Fragment(name='ICP备案号', slug='icp', group_id=grp_contact.id,
                 field_type='text', value='苏ICP备2026000000号', sort_order=70, is_enabled=True),
        Fragment(name='微信二维码', slug='wechat_qrcode', group_id=grp_contact.id,
                 field_type='image', value='', sort_order=60, is_enabled=True),

        Fragment(name='首页公告', slug='home_notice', group_id=grp_home.id,
                 field_type='richtext',
                 value=f'<p>欢迎访问{company}官方网站！专注精密机械制造二十余年。</p>',
                 sort_order=100, is_enabled=True),
        # 首页轮播图 v2.2.0 起由 banner 插件演示钩子生成（home-hero 分组），
        # 不再写入 home_banner_* 碎片
    ]
    db.session.add_all(fragments)


# ============================================================
# 英文制造业演示数据：虚构企业「Ruijing Precision Works Co., Ltd.」
# ============================================================

def _generate_manufacturing_demo_en():
    """English manufacturing demo data: precision machinery company."""
    now = datetime.now()

    company = 'Ruijing Precision Works Co., Ltd.'
    brand = 'Ruijing Precision'

    Setting.set('site_name', company)
    Setting.set('site_subtitle', 'Dedicated to Precision Manufacturing for Over 20 Years')
    Setting.set('footer_copyright', f'Copyright © {company}')
    Setting.set('site_theme', 'manufacturing_en')
    Setting.set('seo_title', f'{brand} - Precision Manufacturing Expert')
    Setting.set('seo_keywords', 'precision machining,CNC parts,automation equipment,smart manufacturing')
    Setting.set('seo_description', f'{brand} specializes in R&D and manufacturing of precision mechanical components, providing automation equipment and one-stop solutions.')

    # ============ Column structure ============
    about = Column(name='About Us', slug='about', type='page', sort_order=100,
                   is_enabled=True, parent_mode='first_child',
                   summary=f'Learn about {brand}\'s history and philosophy',
                   page_content=_mfg_en_about_content())
    db.session.add(about)

    news = Column(name='News', slug='news', type='list', sort_order=90,
                  is_enabled=True, parent_mode='first_child',
                  summary='Company news and industry updates', page_size=10)
    db.session.add(news)

    company_news = Column(name='Company News', slug='company-news', type='list',
                          parent_id=None, sort_order=95, is_enabled=True,
                          parent_mode='first_child', page_size=10,
                          summary='Internal company news')
    industry_news = Column(name='Industry News', slug='industry-news', type='list',
                           parent_id=None, sort_order=90, is_enabled=True,
                           parent_mode='first_child', page_size=10,
                           summary='Industry trends and insights')
    db.session.add_all([company_news, industry_news])
    db.session.flush()
    company_news.parent_id = news.id
    industry_news.parent_id = news.id

    products = Column(name='Products', slug='products', type='list', sort_order=80,
                      is_enabled=True, parent_mode='list_children',
                      summary='Our products and solutions', page_size=12)
    db.session.add(products)

    precision_parts = Column(name='Precision Parts', slug='precision-parts', type='list',
                             sort_order=95, is_enabled=True,
                             parent_mode='first_child', page_size=12,
                             summary='High-precision mechanical components')
    automation = Column(name='Automation Equipment', slug='automation', type='list',
                        sort_order=90, is_enabled=True,
                        parent_mode='first_child', page_size=12,
                        summary='Industrial automation equipment and production lines')
    db.session.add_all([precision_parts, automation])
    db.session.flush()
    precision_parts.parent_id = products.id
    automation.parent_id = products.id

    service = Column(name='Service & Support', slug='service', type='page', sort_order=70,
                     is_enabled=True, parent_mode='first_child',
                     summary='Professional technical service and after-sales support',
                     page_content=_mfg_en_service_content())
    db.session.add(service)

    contact = Column(name='Contact Us', slug='contact', type='page', sort_order=60,
                     is_enabled=True, parent_mode='first_child',
                     summary='Contact information and address',
                     page_content=_mfg_en_contact_content())
    db.session.add(contact)

    db.session.flush()

    # ============ Company News ============
    _add_article(company_news, f'{brand} Passes ISO 9001 Quality Management Certification',
                 f'Recently, {company} officially passed the ISO 9001:2015 quality management certification.',
                 _mfg_en_news_content_1(), now - timedelta(days=2), sort_order=100,
                 cover=f'{_DEMO_IMG}/mfg_news1.jpg')
    _add_article(company_news, 'New Five-Axis Machining Center Installed, Capacity Up 40%',
                 'To meet growing customer demand, the company has added two five-axis machining centers.',
                 _mfg_en_news_content_2(), now - timedelta(days=5), sort_order=90,
                 cover=f'{_DEMO_IMG}/mfg_news2.jpg')
    _add_article(company_news, '2026 Annual Technology Exchange Conference Successfully Held',
                 'The conference themed "Lean Manufacturing · Smart Future" brought all employees together.',
                 _mfg_en_news_content_3(), now - timedelta(days=10), sort_order=80,
                 cover=f'{_DEMO_IMG}/mfg_news3.jpg')

    # ============ Industry News ============
    _add_article(industry_news, 'MIIT Releases Smart Manufacturing Development Plan (2026-2030)',
                 'The Ministry of Industry and Information Technology recently released the smart manufacturing development plan.',
                 _mfg_en_industry_content_1(), now - timedelta(days=3), sort_order=100)
    _add_article(industry_news, 'How SMEs Can Embrace Smart Manufacturing in the Industry 4.0 Era',
                 'As Industry 4.0 deepens, more manufacturers are exploring intelligent transformation.',
                 _mfg_en_industry_content_2(), now - timedelta(days=7), sort_order=90)
    _add_article(industry_news, 'High-End Equipment Manufacturing Maintains Steady Growth',
                 'According to a recent market research report, high-end equipment manufacturing maintains steady growth.',
                 _mfg_en_industry_content_3(), now - timedelta(days=12), sort_order=80)

    # ============ Precision Parts ============
    _add_article(precision_parts, 'High-Precision Spindle',
                 'High-precision spindle for CNC machine tools, rotational accuracy ≤0.003mm.',
                 _mfg_en_product_shaft(), now - timedelta(days=1), sort_order=100,
                 cover=f'{_DEMO_IMG}/mfg_product_a.jpg')
    _add_article(precision_parts, 'Precision Gear Assembly',
                 'Made of premium alloy steel with carburizing and quenching, smooth transmission and low noise.',
                 _mfg_en_product_gear(), now - timedelta(days=4), sort_order=90,
                 cover=f'{_DEMO_IMG}/mfg_product_b.jpg')

    # ============ Automation Equipment ============
    _add_article(automation, 'Automated Assembly Line',
                 'Custom automated assembly line for electronics and automotive parts industries.',
                 _mfg_en_product_line(), now - timedelta(days=2), sort_order=100,
                 cover=f'{_DEMO_IMG}/mfg_factory.jpg')
    _add_article(automation, 'Industrial Robot Workstation',
                 'Six-axis industrial robot workstation supporting welding, handling, palletizing and more.',
                 _mfg_en_product_robot(), now - timedelta(days=6), sort_order=90,
                 cover=f'{_DEMO_IMG}/mfg_workshop.jpg')

    # ============ Fragments ============
    _mfg_en_init_fragments(company, brand)

    db.session.commit()


# ============ English Manufacturing Content ============

def _mfg_en_about_content():
    return '''<p>Ruijing Precision Works Co., Ltd. was established in 2003. It is a high-tech enterprise specializing in R&D and manufacturing of precision mechanical components, headquartered in the core manufacturing hub of the Yangtze River Delta.</p>
<h3>Company Overview</h3>
<p>Ruijing Precision is dedicated to providing high-quality precision components and automation solutions for equipment manufacturing, automotive, and electronics industries. The company covers 30,000 square meters, with modern climate-controlled workshops and a comprehensive testing center, employing over 300 people including a R&D team of more than 40.</p>
<h3>Corporate Culture</h3>
<p>We adhere to the philosophy of "Excellence in Every Detail · Craftsmanship in Manufacturing," taking quality as our lifeline and innovation as our driving force, continuously creating value for our customers.</p>
<h3>Business Scope</h3>
<ul>
  <li>Precision mechanical component machining (CNC turning, milling, five-axis)</li>
  <li>Industrial automation equipment R&D and integration</li>
  <li>Custom non-standard equipment design and manufacturing</li>
  <li>Mechanical assembly and testing services</li>
  <li>Technical consulting services</li>
</ul>
<h3>Vision</h3>
<p>To become a leading precision manufacturing solution provider, empowering the transformation and upgrading of China's manufacturing industry.</p>'''


def _mfg_en_service_content():
    return '''<h3>Service Commitment</h3>
<p>We provide 24/7 technical support, promising a 2-hour response during business hours and solutions within 4 hours for urgent issues.</p>
<h3>Service Scope</h3>
<ul>
  <li><strong>Pre-sales Consulting</strong>: Professional selection advice and solution design based on customer needs</li>
  <li><strong>In-sales Support</strong>: Full tracking of order progress with technical briefings</li>
  <li><strong>After-sales Maintenance</strong>: Equipment installation, commissioning, operator training, and regular follow-ups</li>
  <li><strong>Spare Parts Supply</strong>: Long-term supply of original parts to ensure stable equipment operation</li>
  <li><strong>Technical Upgrades</strong>: Equipment upgrade solutions based on process development</li>
</ul>
<h3>Contact</h3>
<p>Technical Service Hotline: 400-888-8888<br>
Service Email: service@ruijing-precision.com</p>'''


def _mfg_en_contact_content():
    return '''<h3>Contact Us</h3>
<p><strong>Company:</strong> Ruijing Precision Works Co., Ltd.</p>
<p><strong>Address:</strong> No. XX, XX Road, Industrial Park, Suzhou, Jiangsu Province</p>
<p><strong>Phone:</strong> 0512-88888888</p>
<p><strong>Fax:</strong> 0512-88888889</p>
<p><strong>Service Hotline:</strong> 400-888-8888</p>
<p><strong>Email:</strong> contact@ruijing-precision.com</p>
<p><strong>Postal Code:</strong> 215000</p>
<p><strong>Business Hours:</strong> Monday to Friday 8:30-17:30</p>'''


def _mfg_en_news_content_1():
    return f'''<p>Recently, following a rigorous audit by an authoritative certification body, Ruijing Precision Works Co., Ltd. officially passed the ISO 9001:2015 quality management certification, marking a recognized milestone in the company's quality management.</p>
<p>ISO 9001 is an internationally recognized quality management standard. The certification process rigorously audits the entire process including design, procurement, production, inspection, and sales. This achievement reflects Ruijing Precision's long-standing commitment to quality-first principles.</p>
<p>The company's leadership stated that this certification will serve as an opportunity to further improve the quality management system and provide customers with better products and services.</p>'''


def _mfg_en_news_content_2():
    return '''<p>To meet growing customer demand, the company has recently added two imported five-axis machining centers, further enhancing its capability for complex component machining.</p>
<p>The new equipment features high rigidity and precision, enabling multi-face machining in a single setup, significantly improving efficiency and consistency. After commissioning, the precision component production capacity is expected to increase by 40%.</p>
<p>This is an important step in the company's 2026 capacity expansion plan. The company will continue to invest in advanced equipment based on market demand.</p>'''


def _mfg_en_news_content_3():
    return '''<p>Ruijing Precision's 2026 Annual Technology Exchange Conference was successfully held at the headquarters. The conference themed "Lean Manufacturing · Smart Future" brought all employees together for this event.</p>
<p>The conference reviewed the achievements of the past year and recognized outstanding teams and individuals. The technical department heads shared cutting-edge trends in precision machining, and multiple project teams presented process improvement case studies.</p>
<p>In the closing remarks, the company's general manager outlined the development direction for the new year, encouraging all employees to continue focusing on technological innovation to create greater value for customers.</p>'''


def _mfg_en_industry_content_1():
    return '''<p>Recently, the Ministry of Industry and Information Technology officially released the "Smart Manufacturing Development Plan (2026-2030)," proposing the goal of achieving comprehensive digitization, networking, and intelligence in manufacturing by 2030.</p>
<p>The plan outlines multiple supportive policies, including increasing technological transformation investment, encouraging smart manufacturing equipment R&D, promoting industrial internet applications, and strengthening talent development. The plan specifically emphasizes supporting SMEs in intelligent transformation and encouraging professional service providers to offer comprehensive solutions.</p>
<p>Industry experts indicate that the release of this plan will bring new development opportunities for the equipment manufacturing industry, especially in high-end equipment and precision manufacturing.</p>'''


def _mfg_en_industry_content_2():
    return '''<p>As Industry 4.0 deepens, more manufacturing companies are exploring intelligent transformation paths. Smart manufacturing has become key to enhancing competitiveness.</p>
<p>Currently, the main application scenarios of smart manufacturing in SMEs include digital workshops, intelligent production lines, remote equipment monitoring, and quality traceability. Through intelligent transformation, companies can significantly improve production efficiency and reduce operating costs.</p>
<p>Experts point out that SMEs face challenges such as funding and talent in smart manufacturing transformation, and recommend implementing in phases, starting with projects that have short payback periods.</p>'''


def _mfg_en_industry_content_3():
    return '''<p>According to a recently released market research report, the high-end equipment manufacturing industry maintains steady growth, serving as an important pillar of manufacturing transformation and upgrading.</p>
<p>The report shows that in 2025, the value-added of high-end equipment manufacturing grew by over 10% year-on-year, with industrial robots, CNC machine tools, and automated production lines performing particularly well. Dual-driven by policy support and market demand, industry prosperity continues to rise.</p>
<p>For precision component manufacturers, the rapid development of high-end equipment means more supporting opportunities and higher technical requirements.</p>'''


def _mfg_en_product_shaft():
    return '''<h3>Product Overview</h3>
<p>The high-precision spindle is a core component of CNC machine tools, made of premium alloy steel, precision-ground and dynamically balanced, with rotational accuracy ≤0.003mm.</p>
<h3>Technical Specifications</h3>
<ul>
  <li>Spindle diameter: φ40 - φ200mm (customizable)</li>
  <li>Rotational accuracy: ≤0.003mm</li>
  <li>Radial runout: ≤0.005mm</li>
  <li>Max speed: 8000 rpm</li>
  <li>Surface roughness: Ra 0.4</li>
  <li>Dynamic balance grade: G2.5</li>
</ul>
<h3>Applications</h3>
<p>Widely used in CNC lathes, machining centers, grinding machines, and precision measuring equipment.</p>'''


def _mfg_en_product_gear():
    return '''<h3>Product Overview</h3>
<p>The precision gear assembly is made of premium alloy steel with carburizing and quenching, achieving gear accuracy of GB/T 10095 Grade 5, with smooth transmission, low noise, and long service life.</p>
<h3>Technical Specifications</h3>
<ul>
  <li>Module: 1 - 8 (customizable)</li>
  <li>Gear accuracy: Grade 5 (GB/T 10095)</li>
  <li>Material: 20CrMnTi / 42CrMo</li>
  <li>Heat treatment: Carburizing and quenching HRC58-62</li>
  <li>Surface treatment: Shot peening, phosphating, etc.</li>
</ul>
<h3>Applications</h3>
<p>Suitable for industrial robots, precision reducers, automated production lines, machine tool transmission systems, etc.</p>'''


def _mfg_en_product_line():
    return '''<h3>Product Overview</h3>
<p>The automated assembly line is custom-designed for electronics and automotive parts industries, integrating feeding, assembly, inspection, and unloading processes for fully automated production.</p>
<h3>System Features</h3>
<ul>
  <li>Modular design, flexible combination based on process requirements</li>
  <li>Equipped with vision inspection system to ensure assembly quality</li>
  <li>Supports multi-variant switching for flexible production</li>
  <li>Cycle time as low as 3 seconds per unit</li>
  <li>Integrated MES system for production data traceability</li>
</ul>
<h3>Application Cases</h3>
<p>Successfully applied in automotive sensor assembly, electronic connector assembly, home appliance controller assembly, and more.</p>'''


def _mfg_en_product_robot():
    return '''<h3>Product Overview</h3>
<p>The six-axis industrial robot workstation supports welding, handling, palletizing, dispensing, and other processes. End effectors and fixtures can be customized based on customer process requirements.</p>
<h3>Technical Specifications</h3>
<ul>
  <li>Payload: 10kg - 200kg options</li>
  <li>Reach: 1.4m - 3.1m options</li>
  <li>Repeatability: ±0.05mm</li>
  <li>Supports offline programming and teach pendant programming</li>
  <li>Integrated safety protection system</li>
</ul>
<h3>Applications</h3>
<p>Automotive manufacturing, metal processing, electronic assembly, logistics and warehousing, etc.</p>'''


def _mfg_en_init_fragments(company, brand):
    """Initialize fragments (English manufacturing)."""
    grp_contact = FragmentGroup(name='Contact Info', sort_order=100)
    grp_home = FragmentGroup(name='Home Content', sort_order=90)
    db.session.add_all([grp_contact, grp_home])
    db.session.flush()

    fragments = [
        Fragment(name='Service Phone', slug='contact_phone', group_id=grp_contact.id,
                 field_type='text', value='400-888-8888', sort_order=100, is_enabled=True),
        Fragment(name='Service Email', slug='contact_email', group_id=grp_contact.id,
                 field_type='text', value='contact@ruijing-precision.com', sort_order=90, is_enabled=True),
        Fragment(name='Company Address', slug='contact_address', group_id=grp_contact.id,
                 field_type='textarea',
                 value='No. XX, XX Road, Industrial Park, Suzhou, Jiangsu Province', sort_order=80, is_enabled=True),
        Fragment(name='ICP Filing', slug='icp', group_id=grp_contact.id,
                 field_type='text', value='SuICP No. 2026000000', sort_order=70, is_enabled=True),
        Fragment(name='WeChat QR Code', slug='wechat_qrcode', group_id=grp_contact.id,
                 field_type='image', value='', sort_order=60, is_enabled=True),

        Fragment(name='Home Notice', slug='home_notice', group_id=grp_home.id,
                 field_type='richtext',
                 value=f'<p>Welcome to {company} official website! Dedicated to precision manufacturing for over 20 years.</p>',
                 sort_order=100, is_enabled=True),
    ]
    db.session.add_all(fragments)


# ============================================================
# 服务业演示数据：虚构企业「云岚咨询管理有限公司」
# ============================================================

def _generate_service_demo():
    """服务业演示数据：企业管理咨询服务公司。"""
    now = datetime.now()

    company = '云岚咨询管理有限公司'
    brand = '云岚咨询'

    # 更新站点设置：site_name/footer_copyright 为前台“网站名称/企业版权”，写入企业信息。
    # 后台的 CMS 名称与版权由 Setting.CMS_NAME / CMS_COPYRIGHT 固定，不受此处影响。
    Setting.set('site_name', company)
    Setting.set('site_subtitle', '专业企业管理咨询服务商')
    Setting.set('footer_copyright', f'版权所有 © {company}')
    Setting.set('site_theme', 'service')
    Setting.set('seo_title', f'{brand} - 企业管理咨询专家')
    Setting.set('seo_keywords', '企业管理咨询,人力资源咨询,战略咨询,组织优化,培训服务')
    Setting.set('seo_description', f'{brand}提供战略咨询、人力资源、组织发展、企业培训等专业服务，助力企业持续成长。')

    # ============ 栏目结构 ============
    about = Column(name='关于我们', slug='about', type='page', sort_order=100,
                   is_enabled=True, parent_mode='first_child',
                   summary=f'了解{brand}的团队与服务理念',
                   page_content=_svc_about_content())
    db.session.add(about)

    news = Column(name='新闻动态', slug='news', type='list', sort_order=90,
                  is_enabled=True, parent_mode='first_child',
                  summary='公司动态与行业洞察', page_size=10)
    db.session.add(news)

    company_news = Column(name='公司动态', slug='company-news', type='list',
                          parent_id=None, sort_order=95, is_enabled=True,
                          parent_mode='first_child', page_size=10,
                          summary='公司内部动态')
    insights = Column(name='行业洞察', slug='industry-news', type='list',
                      parent_id=None, sort_order=90, is_enabled=True,
                      parent_mode='first_child', page_size=10,
                      summary='管理咨询行业前沿观点')
    db.session.add_all([company_news, insights])
    db.session.flush()
    company_news.parent_id = news.id
    insights.parent_id = news.id

    services = Column(name='服务项目', slug='services', type='list', sort_order=80,
                      is_enabled=True, parent_mode='list_children',
                      summary='我们的专业服务', page_size=12)
    db.session.add(services)

    strategy = Column(name='战略咨询', slug='strategy', type='list',
                      sort_order=95, is_enabled=True,
                      parent_mode='first_child', page_size=12,
                      summary='企业战略规划与落地')
    hr = Column(name='人力资源', slug='hr', type='list',
                sort_order=90, is_enabled=True,
                parent_mode='first_child', page_size=12,
                summary='人力资源体系建设')
    training = Column(name='企业培训', slug='training', type='list',
                      sort_order=85, is_enabled=True,
                      parent_mode='first_child', page_size=12,
                      summary='管理层与员工培训')
    db.session.add_all([strategy, hr, training])
    db.session.flush()
    strategy.parent_id = services.id
    hr.parent_id = services.id
    training.parent_id = services.id

    cases = Column(name='客户案例', slug='cases', type='list', sort_order=70,
                   is_enabled=True, parent_mode='first_child', page_size=12,
                   summary='我们的客户案例')
    db.session.add(cases)

    contact = Column(name='联系我们', slug='contact', type='page', sort_order=60,
                     is_enabled=True, parent_mode='first_child',
                     summary='联系方式与地址信息',
                     page_content=_svc_contact_content())
    db.session.add(contact)

    db.session.flush()

    # ============ 公司动态文章 ============
    _add_article(company_news, f'{brand}发布2026年企业管理咨询行业白皮书',
                 f'近日，{company}正式发布《2026企业管理咨询行业白皮书》，深度解析行业趋势。',
                 _svc_news_content_1(), now - timedelta(days=2), sort_order=100,
                 cover=f'{_DEMO_IMG}/svc_news1.jpg')
    _add_article(company_news, '我司新增深圳办公室，业务版图再扩展',
                 '为更好服务华南地区客户，公司深圳办公室正式投入运营。',
                 _svc_news_content_2(), now - timedelta(days=5), sort_order=90,
                 cover=f'{_DEMO_IMG}/svc_news2.jpg')
    _add_article(company_news, '2026年度咨询师大会圆满召开',
                 '本次大会以"智汇未来·共启新程"为主题，全体咨询师共同探讨行业发展。',
                 _svc_news_content_3(), now - timedelta(days=10), sort_order=80,
                 cover=f'{_DEMO_IMG}/svc_news3.jpg')

    # ============ 行业洞察文章 ============
    _add_article(insights, '数字化转型浪潮下，企业如何重塑组织能力',
                 '数字化转型不仅是技术升级，更是组织能力与人才体系的全面重塑。',
                 _svc_insight_content_1(), now - timedelta(days=3), sort_order=100)
    _add_article(insights, '新经济形势下，中小企业的人才战略',
                 '面对复杂多变的市场环境，中小企业如何吸引与留住核心人才。',
                 _svc_insight_content_2(), now - timedelta(days=7), sort_order=90)
    _add_article(insights, '从绩效管理到绩效赋能：HR的新角色',
                 '现代人力资源管理者正从考核者转变为业务伙伴与赋能者。',
                 _svc_insight_content_3(), now - timedelta(days=12), sort_order=80)

    # ============ 战略咨询文章 ============
    _add_article(strategy, '企业战略规划咨询',
                 '帮助企业明确发展方向，制定可落地的战略规划。',
                 _svc_service_strategy(), now - timedelta(days=1), sort_order=100,
                 cover=f'{_DEMO_IMG}/svc_meeting.jpg')
    _add_article(strategy, '商业模式设计与优化',
                 '通过商业模式画布等工具，帮助企业找到新的增长点。',
                 _svc_service_business_model(), now - timedelta(days=4), sort_order=90,
                 cover=f'{_DEMO_IMG}/svc_office.jpg')

    # ============ 人力资源文章 ============
    _add_article(hr, '人力资源体系建设',
                 '从组织架构、岗位体系到薪酬激励，打造完善的人力资源体系。',
                 _svc_service_hr(), now - timedelta(days=2), sort_order=100,
                 cover=f'{_DEMO_IMG}/svc_team.jpg')
    _add_article(hr, '股权激励方案设计',
                 '为成长型企业设计科学的股权激励方案，吸引并留住核心人才。',
                 _svc_service_equity(), now - timedelta(days=6), sort_order=90,
                 cover=f'{_DEMO_IMG}/svc_service_a.jpg')

    # ============ 企业培训文章 ============
    _add_article(training, '管理层领导力培训',
                 '针对中高层管理者设计的系统化领导力提升项目。',
                 _svc_service_leadership(), now - timedelta(days=3), sort_order=100,
                 cover=f'{_DEMO_IMG}/svc_service_b.jpg')

    # ============ 客户案例文章 ============
    _add_article(cases, '某科技企业组织优化项目',
                 '通过组织诊断与流程梳理，帮助客户提升运营效率30%。',
                 _svc_case_tech(), now - timedelta(days=8), sort_order=100,
                 cover=f'{_DEMO_IMG}/svc_office.jpg')
    _add_article(cases, '某制造企业数字化转型项目',
                 '协助客户完成从战略规划到落地实施的全流程数字化转型。',
                 _svc_case_mfg(), now - timedelta(days=15), sort_order=90,
                 cover=f'{_DEMO_IMG}/svc_meeting.jpg')

    # ============ 碎片 ============
    _svc_init_fragments(company, brand)

    db.session.commit()


# ============ 服务业内容 ============

def _svc_about_content():
    return '''<p>云岚咨询管理有限公司成立于2015年，是一家专注于企业管理咨询的专业服务机构，总部位于上海。</p>
<h3>公司简介</h3>
<p>云岚咨询致力于为成长型企业提供战略咨询、人力资源、组织发展、企业培训等专业服务。公司拥有一支由资深顾问与行业专家组成的团队，累计服务客户超过200家，覆盖制造、科技、金融、零售等多个行业。</p>
<h3>企业文化</h3>
<p>我们秉承"专业·务实·共创价值"的理念，以客户成功为使命，以专业能力为根基，与客户携手成长。</p>
<h3>服务范围</h3>
<ul>
  <li>战略咨询：战略规划、商业模式设计、业务转型</li>
  <li>人力资源：组织设计、薪酬绩效、股权激励</li>
  <li>企业培训：领导力、管理技能、专业能力</li>
  <li>组织发展：文化诊断、流程优化、变革管理</li>
  <li>数字化转型：业务诊断、流程重塑、系统选型</li>
</ul>
<h3>企业愿景</h3>
<p>成为最受企业信赖的管理咨询合作伙伴，助力中国成长型企业持续成长。</p>'''


def _svc_contact_content():
    return '''<h3>联系我们</h3>
<p><strong>公司名称：</strong>云岚咨询管理有限公司</p>
<p><strong>地　　址：</strong>上海市浦东新区XX路XX号XX大厦X楼</p>
<p><strong>电　　话：</strong>021-88888888</p>
<p><strong>传　　真：</strong>021-88888889</p>
<p><strong>服务热线：</strong>400-666-8888</p>
<p><strong>邮　　箱：</strong>contact@yunlan-consulting.com</p>
<p><strong>邮　　编：</strong>200120</p>
<p><strong>工作时间：</strong>周一至周五 9:00-18:00</p>'''


def _svc_news_content_1():
    return '''<p>近日，云岚咨询管理有限公司正式发布《2026企业管理咨询行业白皮书》，深度解析行业趋势与服务模式创新。</p>
<p>本白皮书基于对全国300余家企业调研数据，结合云岚咨询多年实战经验，从战略、人力、组织、数字化等维度系统分析了企业管理咨询行业的发展现状与未来趋势。</p>
<p>白皮书指出，随着经济环境变化与数字化转型深入，企业对管理咨询的需求正从单一项目向长期陪跑式服务转变，咨询机构需要具备更强的行业洞察与落地能力。</p>'''


def _svc_news_content_2():
    return '''<p>为更好服务华南地区客户，云岚咨询深圳办公室正式投入运营，标志着公司业务版图进一步扩展。</p>
<p>新办公室位于深圳市福田中心区，配备了完整的咨询团队与项目支持体系，可就近为珠三角地区客户提供战略咨询、人力资源、企业培训等全系列服务。</p>
<p>这是公司继北京、杭州之后设立的第三个区域办公室，未来还将根据业务发展需要继续完善全国服务网络。</p>'''


def _svc_news_content_3():
    return '''<p>云岚咨询2026年度咨询师大会在上海总部圆满召开，本次大会以"智汇未来·共启新程"为主题，全体咨询师共同参加了此次活动。</p>
<p>大会回顾了过去一年公司取得的成绩，并对优秀项目团队进行了表彰。多位资深合伙人分享了咨询服务方法论与典型案例，新入职顾问也进行了交流发言。</p>
<p>公司创始人在总结发言中明确了新一年的发展方向，鼓励全体顾问持续学习，以专业能力为客户创造更大价值。</p>'''


def _svc_insight_content_1():
    return '''<p>数字化转型已成为企业发展的必选项，但许多企业在转型过程中只关注技术升级，忽视了组织能力与人才体系的同步重塑，导致转型效果不及预期。</p>
<p>成功的数字化转型需要"技术+组织+人才"三位一体推进：在引入数字化工具的同时，重塑业务流程、调整组织架构、培养数字化人才。这对HR与管理层提出了新的要求。</p>
<p>建议企业从战略高度统筹数字化转型，避免技术先行、组织滞后的失衡局面。</p>'''


def _svc_insight_content_2():
    return '''<p>面对复杂多变的市场环境，中小企业在人才竞争上面临更大挑战。如何吸引与留住核心人才，成为决定企业能否持续成长的关键。</p>
<p>相比大型企业，中小企业难以单纯依靠薪酬竞争。更可行的路径是：清晰的成长愿景、灵活的发展空间、有竞争力的长期激励（如股权激励）、以及良好的企业文化。</p>
<p>建议中小企业从战略高度规划人才体系，将人才管理与企业发展战略紧密结合，避免临时性与被动应对。</p>'''


def _svc_insight_content_3():
    return '''<p>随着企业管理理念的演进，人力资源管理者的角色正在发生深刻变化：从传统的考核者，转变为业务伙伴与赋能者。</p>
<p>现代绩效管理不再局限于年度考核与打分，更强调持续反馈、能力发展与目标对齐。OKR、持续反馈、发展性评估等新工具日益普及。</p>
<p>这对HR的专业能力提出了更高要求：需要深入理解业务，具备数据洞察与变革推动能力，真正成为业务的战略合作伙伴。</p>'''


def _svc_service_strategy():
    return '''<h3>服务简介</h3>
<p>战略规划咨询帮助企业系统梳理内外部环境，明确发展方向与路径，制定可落地的战略规划。</p>
<h3>服务内容</h3>
<ul>
  <li>外部环境分析：宏观环境、行业趋势、竞争格局</li>
  <li>内部能力诊断：资源能力、组织能力、核心优势</li>
  <li>战略方向制定：愿景使命、业务定位、发展目标</li>
  <li>战略路径设计：业务组合、增长路径、关键举措</li>
  <li>战略落地保障：组织调整、资源规划、考核机制</li>
</ul>
<h3>服务成果</h3>
<p>《战略规划报告》《战略落地实施计划》《关键举措清单》</p>'''


def _svc_service_business_model():
    return '''<h3>服务简介</h3>
<p>通过商业模式画布等工具，帮助企业审视现有模式，找到新的增长点与价值创造方式。</p>
<h3>服务内容</h3>
<ul>
  <li>现有商业模式诊断</li>
  <li>客户价值主张重塑</li>
  <li>盈利模式设计</li>
  <li>关键资源与能力梳理</li>
  <li>新业务孵化路径</li>
</ul>
<h3>适用场景</h3>
<p>业务增长乏力、寻求第二曲线、进入新市场、应对行业变革等。</p>'''


def _svc_service_hr():
    return '''<h3>服务简介</h3>
<p>从组织架构、岗位体系到薪酬激励，帮助企业打造完善的人力资源体系，支撑业务发展。</p>
<h3>服务内容</h3>
<ul>
  <li>组织架构设计与优化</li>
  <li>岗位体系与职级体系搭建</li>
  <li>薪酬体系设计（岗位价值评估、薪酬结构、激励方案）</li>
  <li>绩效管理体系设计（KPI/OKR、考核流程、结果应用）</li>
  <li>任职资格与能力模型建设</li>
</ul>
<h3>服务成果</h3>
<p>《组织架构方案》《岗位说明书》《薪酬体系方案》《绩效管理制度》</p>'''


def _svc_service_equity():
    return '''<h3>服务简介</h3>
<p>为成长型企业设计科学的股权激励方案，吸引并留住核心人才，实现企业与员工共赢。</p>
<h3>服务内容</h3>
<ul>
  <li>股权激励模式选择（期权、限制性股票、分红权等）</li>
  <li>激励对象确定与额度分配</li>
  <li>行权条件与考核机制设计</li>
  <li>股权管理机制（退出、回购、转让等）</li>
  <li>法律文件与实施方案</li>
</ul>
<h3>适用对象</h3>
<p>拟上市企业、成长型科技企业、合伙人制企业等。</p>'''


def _svc_service_leadership():
    return '''<h3>服务简介</h3>
<p>针对中高层管理者设计的系统化领导力提升项目，帮助管理者从业务骨干成长为卓越领导。</p>
<h3>课程模块</h3>
<ul>
  <li>战略思维与商业洞察</li>
  <li>组织管理与团队建设</li>
  <li>人才识别与培养</li>
  <li>变革管理与文化塑造</li>
  <li>沟通与影响力</li>
</ul>
<h3>培训形式</h3>
<p>主题讲授、案例研讨、行动学习、教练辅导、复盘反思相结合，周期3-6个月。</p>'''


def _svc_case_tech():
    return '''<h3>项目背景</h3>
<p>某科技企业经过快速扩张后，组织架构臃肿、流程冗长、决策效率低下，影响业务发展。</p>
<h3>解决方案</h3>
<ul>
  <li>组织诊断：通过访谈、问卷、数据分析识别核心问题</li>
  <li>组织重构：扁平化组织架构，明确职责边界</li>
  <li>流程优化：梳理核心业务流程，去除冗余环节</li>
  <li>机制设计：建立清晰的决策机制与协作机制</li>
</ul>
<h3>项目成果</h3>
<p>决策周期缩短50%，跨部门协作效率提升30%，员工满意度显著提升。</p>'''


def _svc_case_mfg():
    return '''<h3>项目背景</h3>
<p>某传统制造企业希望借助数字化提升运营效率，但缺乏清晰路径与内部能力。</p>
<h3>解决方案</h3>
<ul>
  <li>数字化战略规划：明确愿景、目标与路径</li>
  <li>业务流程重塑：以数字化思维重新设计核心流程</li>
  <li>系统选型与实施：协助选型并陪伴实施</li>
  <li>组织能力建设：培养数字化人才与团队</li>
</ul>
<h3>项目成果</h3>
<p>生产效率提升25%，库存周转提升40%，订单交付周期缩短30%。</p>'''


def _svc_init_fragments(company, brand):
    """初始化碎片数据（服务业）。"""
    grp_contact = FragmentGroup(name='联系方式', sort_order=100)
    grp_home = FragmentGroup(name='首页内容', sort_order=90)
    db.session.add_all([grp_contact, grp_home])
    db.session.flush()

    fragments = [
        Fragment(name='客服电话', slug='contact_phone', group_id=grp_contact.id,
                 field_type='text', value='400-666-8888', sort_order=100, is_enabled=True),
        Fragment(name='客服邮箱', slug='contact_email', group_id=grp_contact.id,
                 field_type='text', value='contact@yunlan-consulting.com', sort_order=90, is_enabled=True),
        Fragment(name='公司地址', slug='contact_address', group_id=grp_contact.id,
                 field_type='textarea',
                 value='上海市浦东新区XX路XX号XX大厦X楼', sort_order=80, is_enabled=True),
        Fragment(name='ICP备案号', slug='icp', group_id=grp_contact.id,
                 field_type='text', value='沪ICP备2026000000号', sort_order=70, is_enabled=True),
        Fragment(name='微信二维码', slug='wechat_qrcode', group_id=grp_contact.id,
                 field_type='image', value='', sort_order=60, is_enabled=True),

        Fragment(name='首页公告', slug='home_notice', group_id=grp_home.id,
                 field_type='richtext',
                 value=f'<p>欢迎访问{company}官方网站！专业企业管理咨询服务商。</p>',
                 sort_order=100, is_enabled=True),
        # 首页轮播图 v2.2.0 起由 banner 插件演示钩子生成（home-hero 分组），
        # 不再写入 home_banner_* 碎片
    ]
    db.session.add_all(fragments)


# ============================================================
# 共用工具函数
# ============================================================

def _add_article(column, title, summary, content, published_at, sort_order=50, cover=None):
    """添加文章。"""
    article = Article(
        column_id=column.id,
        title=title,
        summary=summary,
        content=content,
        author='管理员',
        source='本站',
        sort_order=sort_order,
        is_enabled=True,
        published_at=published_at,
        cover=cover,
    )
    db.session.add(article)


# ============================================================
# 教育行业演示数据：虚构机构「启明教育培训学校」（v2.6.3）
# ============================================================

def _generate_education_demo():
    """教育行业演示数据：K12 课外辅导与素质教育培训机构。"""
    now = datetime.now()

    school = '启明教育培训学校'
    brand = '启明教育'

    Setting.set('site_name', school)
    Setting.set('site_subtitle', '用心做教育，用爱育未来')
    Setting.set('footer_copyright', f'版权所有 © {school}')
    Setting.set('site_theme', 'education')
    Setting.set('seo_title', f'{brand} - 专注K12课外辅导与素质教育')
    Setting.set('seo_keywords', '教育培训,课外辅导,少儿编程,英语口语,数学思维,素质教育')
    Setting.set('seo_description', f'{brand}专注K12课外辅导，提供少儿编程、英语口语、数学思维等素质教育课程，助力孩子全面成长。')

    # ============ 栏目结构 ============
    about = Column(name='关于我们', slug='about', type='page', sort_order=100,
                   is_enabled=True, parent_mode='first_child',
                   summary=f'了解{brand}的办学理念与师资团队',
                   page_content=f'<h3>关于{brand}</h3><p>{brand}成立于2010年，是一家专注于K12课外辅导与素质教育的综合性培训机构。'
                               f'学校秉承"用心做教育，用爱育未来"的办学理念，致力于为6-18岁学生提供优质的教育服务。</p>'
                               f'<p>我们拥有一支经验丰富、富有爱心的教师团队，开设少儿编程、英语口语、数学思维等特色课程，'
                               f'采用小班教学与个性化辅导相结合的模式，关注每一位学生的成长。</p>')
    db.session.add(about)

    courses = Column(name='课程中心', slug='courses', type='list', sort_order=90,
                     is_enabled=True, parent_mode='list_children',
                     summary='丰富的素质教育课程', page_size=12)
    db.session.add(courses)

    coding = Column(name='少儿编程', slug='coding', type='list',
                    sort_order=95, is_enabled=True,
                    parent_mode='first_child', page_size=12,
                    summary='Scratch / Python 编程启蒙')
    english = Column(name='英语口语', slug='oral-english', type='list',
                     sort_order=90, is_enabled=True,
                     parent_mode='first_child', page_size=12,
                     summary='外教口语与听力训练')
    math = Column(name='数学思维', slug='math-thinking', type='list',
                  sort_order=85, is_enabled=True,
                  parent_mode='first_child', page_size=12,
                  summary='逻辑思维与奥数启蒙')
    db.session.add_all([coding, english, math])
    db.session.flush()
    coding.parent_id = courses.id
    english.parent_id = courses.id
    math.parent_id = courses.id

    teachers = Column(name='师资力量', slug='teachers', type='list', sort_order=80,
                      is_enabled=True, parent_mode='first_child',
                      summary='优秀教师团队介绍', page_size=12)
    db.session.add(teachers)

    news = Column(name='校园动态', slug='campus-news', type='list', sort_order=70,
                  is_enabled=True, parent_mode='first_child',
                  summary='学校新闻与活动', page_size=10)
    db.session.add(news)

    contact = Column(name='联系我们', slug='contact', type='page', sort_order=60,
                     is_enabled=True, parent_mode='first_child',
                     summary='校区地址与联系方式',
                     page_content=f'<h3>联系我们</h3><p><strong>校区地址：</strong>泰州市海陵区教育路88号</p>'
                               f'<p><strong>咨询电话：</strong>0523-8888-6666</p>'
                               f'<p><strong>电子邮箱：</strong>contact@qiming-edu.example.com</p>'
                               f'<p><strong>营业时间：</strong>周一至周日 8:30 - 21:00</p>')
    db.session.add(contact)

    db.session.flush()

    # ============ 课程文章 ============
    _add_article(coding, 'Scratch 图形化编程启蒙班',
                 '适合7-12岁，从零开始学习编程思维',
                 f'<p>{brand}少儿编程课程采用 Scratch 图形化编程语言，让孩子在游戏化学习中掌握编程思维。</p>'
                 f'<p>课程内容：动画制作、游戏设计、数学逻辑</p>',
                 now, sort_order=100)
    _add_article(coding, 'Python 青少年编程进阶',
                 '适合12-16岁，Python语言基础与项目实践',
                 f'<p>从Python基础语法到完整项目开发，培养孩子的逻辑思维与问题解决能力。</p>',
                 now, sort_order=90)
    _add_article(english, '外教英语口语精品班',
                 '小班教学，纯外教沉浸式口语训练',
                 f'<p>由经验丰富的外教授课，注重听说能力培养，让孩子敢说、会说、爱说英语。</p>',
                 now, sort_order=100)
    _add_article(math, '数学思维训练班',
                 '逻辑思维培养，奥数启蒙',
                 f'<p>通过趣味数学题与思维游戏，培养孩子的逻辑推理能力与数学兴趣。</p>',
                 now, sort_order=100)

    # ============ 师资文章 ============
    _add_article(teachers, '金牌教师团队介绍',
                 '经验丰富、富有爱心的教师队伍',
                 f'<p>{brand}拥有一支由名校毕业生和资深教育工作者组成的教师团队，平均教龄8年以上。</p>',
                 now, sort_order=100)

    # ============ 校园动态文章 ============
    _add_article(news, f'{brand}2026年春季招生开始啦',
                 '新学期课程全面升级，报名享优惠',
                 f'<p>{brand}2026年春季招生正式启动！少儿编程、英语口语、数学思维等课程全面升级。</p>',
                 now, sort_order=100)
    _add_article(news, '校园编程大赛圆满落幕',
                 '我校学员在市级编程比赛中获奖',
                 f'<p>在刚刚结束的泰州市青少年编程大赛中，我校学员取得了优异成绩。</p>',
                 now, sort_order=90)

    db.session.commit()


# ============================================================
# 餐饮行业演示数据：虚构餐厅「鲜味居酒楼」（v2.6.3）
# ============================================================

def _generate_catering_demo():
    """餐饮行业演示数据：中餐馆/酒楼。"""
    now = datetime.now()

    restaurant = '鲜味居酒楼'
    brand = '鲜味居'

    Setting.set('site_name', restaurant)
    Setting.set('site_subtitle', '传承经典味道，款待八方来客')
    Setting.set('footer_copyright', f'版权所有 © {restaurant}')
    Setting.set('site_theme', 'catering')
    Setting.set('seo_title', f'{brand} - 经典本帮菜与特色餐饮')
    Setting.set('seo_keywords', '中餐,本帮菜,特色菜,酒楼,宴席预订,餐饮')
    Setting.set('seo_description', f'{brand}传承经典本帮菜，提供特色菜品与宴席预订服务，选用新鲜食材，匠心烹制。')

    # ============ 栏目结构 ============
    about = Column(name='关于我们', slug='about', type='page', sort_order=100,
                   is_enabled=True, parent_mode='first_child',
                   summary=f'了解{brand}的历史与特色',
                   page_content=f'<h3>关于{brand}</h3><p>{brand}始创于1998年，是一家以本帮菜为主的特色酒楼。'
                               f'二十余年来，我们坚持选用新鲜食材，传承经典烹饪技艺，为顾客呈现地道美味。</p>'
                               f'<p>酒楼环境雅致，设有多个包间，适合家庭聚餐、商务宴请与各类宴席。</p>')
    db.session.add(about)

    dishes = Column(name='招牌菜品', slug='dishes', type='list', sort_order=90,
                    is_enabled=True, parent_mode='list_children',
                    summary='精选招牌菜式', page_size=12)
    db.session.add(dishes)

    hot = Column(name='热菜系列', slug='hot-dishes', type='list',
                 sort_order=95, is_enabled=True,
                 parent_mode='first_child', page_size=12,
                 summary='招牌热菜')
    cold = Column(name='凉菜系列', slug='cold-dishes', type='list',
                  sort_order=90, is_enabled=True,
                  parent_mode='first_child', page_size=12,
                  summary='开胃凉菜')
    soup = Column(name='汤品系列', slug='soups', type='list',
                  sort_order=85, is_enabled=True,
                  parent_mode='first_child', page_size=12,
                  summary='滋补汤品')
    db.session.add_all([hot, cold, soup])
    db.session.flush()
    hot.parent_id = dishes.id
    cold.parent_id = dishes.id
    soup.parent_id = dishes.id

    stores = Column(name='门店信息', slug='stores', type='page', sort_order=80,
                    is_enabled=True, parent_mode='first_child',
                    summary='门店地址与营业时间',
                    page_content=f'<h3>门店信息</h3><p><strong>总店地址：</strong>泰州市海陵区美食街18号</p>'
                               f'<p><strong>订座电话：</strong>0523-8666-8888</p>'
                               f'<p><strong>营业时间：</strong>10:00 - 22:00（全年无休）</p>'
                               f'<p><strong>包间数量：</strong>12间（可容纳10-20人）</p>')
    db.session.add(stores)

    news = Column(name='美食资讯', slug='food-news', type='list', sort_order=70,
                  is_enabled=True, parent_mode='first_child',
                  summary='新品上市与优惠活动', page_size=10)
    db.session.add(news)

    contact = Column(name='联系我们', slug='contact', type='page', sort_order=60,
                     is_enabled=True, parent_mode='first_child',
                     summary='订座与联系方式',
                     page_content=f'<h3>联系我们</h3><p><strong>订座热线：</strong>0523-8666-8888</p>'
                               f'<p><strong>门店地址：</strong>泰州市海陵区美食街18号</p>'
                               f'<p><strong>营业时间：</strong>10:00 - 22:00</p>'
                               f'<p><strong>宴席预订：</strong>欢迎来电咨询各类宴席包桌服务</p>')
    db.session.add(contact)

    db.session.flush()

    # ============ 菜品文章 ============
    _add_article(hot, '红烧狮子头',
                 '淮扬经典，肥而不腻',
                 f'<p>{brand}招牌红烧狮子头，选用三分肥七分瘦五花肉，手工剁制，慢火细炖。</p>',
                 now, sort_order=100)
    _add_article(hot, '松鼠桂鱼',
                 '外酥里嫩，酸甜可口',
                 f'<p>经典苏帮菜，桂鱼改刀炸至金黄，浇上秘制酸甜酱汁。</p>',
                 now, sort_order=90)
    _add_article(cold, '水晶肴肉',
                 '晶莹剔透，入口即化',
                 f'<p>选用猪蹄髈肉，秘制腌制，切片晶莹剔透，蘸醋食用风味更佳。</p>',
                 now, sort_order=100)
    _add_article(soup, '佛跳墙',
                 '山珍海味，滋补养生',
                 f'<p>鲍鱼、海参、鱼翅等十余种食材，文火慢炖，汤浓味醇。</p>',
                 now, sort_order=100)

    # ============ 美食资讯文章 ============
    _add_article(news, f'{brand}2026年夜饭预订开始',
                 '除夕团圆饭，火热预订中',
                 f'<p>{brand}2026年年夜饭预订正式开始！多种套餐可选，包间有限，先到先得。</p>',
                 now, sort_order=100)
    _add_article(news, '秋季时令新菜上市',
                 '应季而食，尝鲜正当时',
                 f'<p>秋季时令新菜已上市，蟹粉豆腐、板栗烧鸡等应季佳肴等您品尝。</p>',
                 now, sort_order=90)

    db.session.commit()
