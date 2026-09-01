"""自定义表单插件：演示数据（manufacturing / service）。

generate 前先清理本插件全部数据（按外键依赖顺序），保证重复生成幂等
（替代核心 _clean_demo_data 原有的表单清理）。制造业/服务业各生成
一条「在线留言」示例表单（与核心版演示数据一致）。
"""
from app.extensions import db

from .models import Form, FormField, FormSubmission, FormSubmissionValue


def generate(industry):
    # 幂等：按外键依赖顺序清理本插件全部数据
    FormSubmissionValue.query.delete()
    FormSubmission.query.delete()
    FormField.query.delete()
    Form.query.delete()
    db.session.flush()

    # 在线留言表单（两套行业演示数据共用同一条表单）
    form = Form(
        name='在线留言',
        slug='message',
        description='欢迎您留下宝贵的意见和建议，我们会尽快与您联系。',
        success_message='感谢您的留言，我们会尽快与您联系！',
        submit_interval=60,
        is_open=True,
    )
    db.session.add(form)
    db.session.flush()

    fields = [
        FormField(label='姓名', field_key='name', field_type='text',
                  is_required=True, placeholder='请输入您的姓名',
                  sort_order=100, form_id=form.id),
        FormField(label='手机号', field_key='phone', field_type='phone',
                  is_required=True, placeholder='请输入手机号',
                  help_text='我们会对您的信息严格保密',
                  sort_order=90, form_id=form.id),
        FormField(label='邮箱', field_key='email', field_type='email',
                  is_required=False, placeholder='请输入邮箱',
                  sort_order=80, form_id=form.id),
        FormField(label='留言内容', field_key='content', field_type='textarea',
                  is_required=True, placeholder='请输入留言内容',
                  sort_order=70, form_id=form.id),
    ]
    db.session.add_all(fields)
    db.session.commit()
