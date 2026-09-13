"""招聘插件贡献给页面构建器的组件（v3.0.0）。

job-list：取开放中的招聘岗位（recruit_jobs 同源），渲染为岗位行，
详情链接走 recruit_job_url()（动态/伪静态自适应）。
"""
from app.builder.registry import Widget
from app.constants import Builder as _B


class JobList(Widget):
    type = 'job-list'
    category = _B.CAT_DATA
    label = '招聘岗位（插件）'
    icon = 'fa-briefcase'
    description = '招聘插件数据：最新岗位列表，可只显示开放申请中的岗位'
    scopes = (_B.SCOPE_HOME, _B.SCOPE_PAGE)
    allowed_children = ()

    default_props = {
        'limit': 6, 'only_open': True,
        'show_location': True, 'show_salary': True, 'show_deadline': False,
        'show_more': True,
    }
    prop_schema = [
        {'key': 'limit', 'label': '显示条数', 'type': 'number'},
        {'key': 'only_open', 'label': '仅显示未截止岗位', 'type': 'toggle'},
        {'key': 'show_location', 'label': '显示工作地点', 'type': 'toggle'},
        {'key': 'show_salary', 'label': '显示薪资待遇', 'type': 'toggle'},
        {'key': 'show_deadline', 'label': '显示截止日期', 'type': 'toggle'},
        {'key': 'show_more', 'label': '显示「更多职位」入口', 'type': 'toggle'},
    ]

    def context(self, node, page_ctx):
        from .frontend import recruit_jobs
        props = node.get('props') or {}
        limit = max(int(props.get('limit') or 6), 1)
        return {
            'job_items': recruit_jobs(limit, bool(props.get('only_open'))),
        }
