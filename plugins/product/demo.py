"""产品插件：演示数据（manufacturing / service）。

manufacturing：在核心演示的「产品中心」两个子栏目（precision-parts /
automation）内各生成 3 个产品（3 张相册、两组规格参数），并把子栏目
列表模板切换为 list_product；service 行业仅清理本插件产品（服务业无产品）。

generate 前先清理本插件旧产品，保证重复生成幂等（防 slug 类冲突）。
"""
import json
from datetime import datetime

from app.extensions import db

from .models import Product

_DEMO_IMG = '/static/uploads/demo'


def _demo_specs(model, power, material):
    return json.dumps([
        {'group': '基本参数', 'items': [
            {'name': '型号', 'value': model},
            {'name': '材质', 'value': material},
        ]},
        {'group': '技术参数', 'items': [
            {'name': '额定功率', 'value': power},
            {'name': '防护等级', 'value': 'IP54'},
        ]},
    ], ensure_ascii=False)


def _demo_specs_en(model, power, material):
    return json.dumps([
        {'group': 'Basic Parameters', 'items': [
            {'name': 'Model', 'value': model},
            {'name': 'Material', 'value': material},
        ]},
        {'group': 'Technical Parameters', 'items': [
            {'name': 'Rated Power', 'value': power},
            {'name': 'Protection Rating', 'value': 'IP54'},
        ]},
    ], ensure_ascii=False)


def _generate(column, title, summary, content, gallery, specs,
              sort_order, now):
    db.session.add(Product(
        column_id=column.id, title=title, summary=summary,
        content=content, gallery=json.dumps(gallery, ensure_ascii=False),
        specs=specs, sort_order=sort_order, is_enabled=True,
        is_deleted=False, created_at=now, updated_at=now,
    ))


def generate(industry):
    from app.models.column import Column

    now = datetime.now()

    # 幂等：清理本插件全部产品（软删除的直接物理删除）
    Product.query.delete()
    db.session.flush()

    if industry == 'service':
        # 服务业：无产品数据；同时还原子栏目模板为默认列表
        for slug in ('precision-parts', 'automation'):
            col = Column.query.filter_by(slug=slug).first()
            if col is not None and col.list_template == 'list_product':
                col.list_template = None
        db.session.commit()
        return

    if industry == 'manufacturing_en':
        parts = Column.query.filter_by(slug='precision-parts',
                                       is_deleted=False).first()
        automation = Column.query.filter_by(slug='automation',
                                            is_deleted=False).first()
        if parts is not None:
            parts.list_template = 'list_product'
        if automation is not None:
            automation.list_template = 'list_product'
        db.session.flush()

        if parts is not None:
            _generate(
                parts, 'High-Precision Spindle ZX-100',
                'High-precision spindle for CNC machine tools, rotational accuracy ≤0.003mm.',
                '<p>Features integrated cast iron base with active temperature control system, '
                'minimal thermal deformation during long-term operation, '
                'suitable for high-speed precision turning and grinding.</p><ul>'
                '<li>Rotational accuracy ≤0.003mm</li><li>Max speed 12000rpm</li>'
                '<li>Optional built-in encoder and cooling kit</li></ul>',
                [f'{_DEMO_IMG}/mfg_product_a.jpg',
                 f'{_DEMO_IMG}/mfg_workshop.jpg',
                 f'{_DEMO_IMG}/mfg_factory.jpg'],
                _demo_specs_en('ZX-100', '7.5 kW', '38CrMoAl Nitrided Steel'), 100, now)
            _generate(
                parts, 'Precision Gear Assembly ZX-200',
                'Made of premium alloy steel with carburizing and quenching, smooth transmission and low noise.',
                '<p>Gear grinding accuracy DIN 5, surface roughness Ra0.4, '
                'widely used in precision reducers and printing machinery.</p>',
                [f'{_DEMO_IMG}/mfg_product_b.jpg',
                 f'{_DEMO_IMG}/mfg_workshop.jpg',
                 f'{_DEMO_IMG}/mfg_factory.jpg'],
                _demo_specs_en('ZX-200', '—', '20CrMnTi Carburizing Steel'), 90, now)
            _generate(
                parts, 'Linear Guide Block ZX-300',
                'Four-direction equal-load design, heavy duty, low noise, high positioning accuracy and long service life.',
                '<p>Available in ball and roller types with low friction coefficient, '
                'suitable for high positioning accuracy and rapid movement applications.</p>',
                [f'{_DEMO_IMG}/mfg_product_a.jpg',
                 f'{_DEMO_IMG}/mfg_product_b.jpg'],
                _demo_specs_en('ZX-300', '—', 'GCr15 Bearing Steel'), 80, now)

        if automation is not None:
            _generate(
                automation, 'Automated Assembly Line ZD-A1',
                'Custom automated assembly line for electronics and automotive parts industries.',
                '<p>Modular design with adjustable cycle time, supports in-line inspection and MES integration, '
                'max line rate 12 units/min.</p>',
                [f'{_DEMO_IMG}/mfg_factory.jpg',
                 f'{_DEMO_IMG}/mfg_workshop.jpg'],
                _demo_specs_en('ZD-A1', '18 kW', 'Carbon Steel Painted'), 100, now)
            _generate(
                automation, 'Industrial Robot Workstation ZD-B2',
                'Six-axis industrial robot workstation supporting welding, handling, palletizing and more.',
                '<p>Standard vision guidance and offline programming interface, changeover time under 30 minutes, '
                'repeatability ±0.02mm.</p>',
                [f'{_DEMO_IMG}/mfg_workshop.jpg',
                 f'{_DEMO_IMG}/mfg_product_a.jpg'],
                _demo_specs_en('ZD-B2', '9 kW', 'Aluminum + Sheet Metal'), 90, now)
            _generate(
                automation, 'Smart Inspection & Sorting System ZD-C3',
                'Machine vision-based inline inspection and auto sorting, false rejection rate below 0.1%.',
                '<p>Supports multi-station parallel inspection with configurable inspection items, '
                'data auto-uploaded to quality traceability system.</p>',
                [f'{_DEMO_IMG}/mfg_factory.jpg',
                 f'{_DEMO_IMG}/mfg_product_b.jpg'],
                _demo_specs_en('ZD-C3', '6 kW', 'Stainless Steel Frame'), 80, now)

        db.session.commit()
        return

    # 制造业：产品中心两个子栏目 → 产品列表模板 + 各 3 个产品
    parts = Column.query.filter_by(slug='precision-parts',
                                   is_deleted=False).first()
    automation = Column.query.filter_by(slug='automation',
                                        is_deleted=False).first()
    if parts is not None:
        parts.list_template = 'list_product'
    if automation is not None:
        automation.list_template = 'list_product'
    db.session.flush()

    if parts is not None:
        _generate(
            parts, '高精度主轴 ZX-100',
            '适用于数控机床的高精度主轴，回转精度≤0.003mm。',
            '<p>采用一体化铸铁基座与主动式温控系统，长期运行热变形小，'
            '适合高速精车与磨削工况。</p><ul>'
            '<li>回转精度 ≤0.003mm</li><li>最高转速 12000rpm</li>'
            '<li>可选内置编码器与冷却套件</li></ul>',
            [f'{_DEMO_IMG}/mfg_product_a.jpg',
             f'{_DEMO_IMG}/mfg_workshop.jpg',
             f'{_DEMO_IMG}/mfg_factory.jpg'],
            _demo_specs('ZX-100', '7.5 kW', '38CrMoAl 渗氮钢'), 100, now)
        _generate(
            parts, '精密齿轮组件 ZX-200',
            '采用优质合金钢材料，经过渗碳淬火工艺，传动平稳、噪音低。',
            '<p>磨齿精度达 DIN 5 级，齿面粗糙度 Ra0.4，'
            '广泛用于精密减速机与印刷机械。</p>',
            [f'{_DEMO_IMG}/mfg_product_b.jpg',
             f'{_DEMO_IMG}/mfg_workshop.jpg',
             f'{_DEMO_IMG}/mfg_factory.jpg'],
            _demo_specs('ZX-200', '—', '20CrMnTi 渗碳钢'), 90, now)
        _generate(
            parts, '直线导轨滑块 ZX-300',
            '四方向等载设计，重载低噪音，定位精度高，使用寿命长。',
            '<p>滚珠型与滚柱型两类，摩擦系数低，适合高定位精度'
            '与快速移动场合。</p>',
            [f'{_DEMO_IMG}/mfg_product_a.jpg',
             f'{_DEMO_IMG}/mfg_product_b.jpg'],
            _demo_specs('ZX-300', '—', 'GCr15 轴承钢'), 80, now)

    if automation is not None:
        _generate(
            automation, '自动化装配生产线 ZD-A1',
            '为电子、汽车零部件等行业定制的自动化装配生产线。',
            '<p>模块化设计，节拍可调，支持在线检测与 MES 系统对接，'
            '整线节拍最高 12 件/分钟。</p>',
            [f'{_DEMO_IMG}/mfg_factory.jpg',
             f'{_DEMO_IMG}/mfg_workshop.jpg'],
            _demo_specs('ZD-A1', '18 kW', '碳钢喷塑'), 100, now)
        _generate(
            automation, '工业机器人工作站 ZD-B2',
            '六轴工业机器人工作站，支持焊接、搬运、码垛等多种工艺。',
            '<p>标配视觉引导与离线编程接口，换型时间小于 30 分钟，'
            '重复定位精度 ±0.02mm。</p>',
            [f'{_DEMO_IMG}/mfg_workshop.jpg',
             f'{_DEMO_IMG}/mfg_product_a.jpg'],
            _demo_specs('ZD-B2', '9 kW', '铝合金 + 钣金'), 90, now)
        _generate(
            automation, '智能检测分拣设备 ZD-C3',
            '基于机器视觉的在线检测与自动分拣，误检率低于 0.1%。',
            '<p>支持多工位并行检测，检测项可配置，数据自动上传'
            '质量追溯系统。</p>',
            [f'{_DEMO_IMG}/mfg_factory.jpg',
             f'{_DEMO_IMG}/mfg_product_b.jpg'],
            _demo_specs('ZD-C3', '6 kW', '不锈钢机架'), 80, now)

    db.session.commit()
