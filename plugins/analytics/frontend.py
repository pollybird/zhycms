"""第三方统计代码插件：前台注入函数。

analytics_head() / analytics_body() 注册为 Jinja 全局函数（核心自动包裹
「插件启用」守卫，未启用返回空串，主题模板零改动不报错）。

注入位置（4 套主题 base.html 统一约定）：
  - analytics_head()  </head> 前（{% block css %} 之后）
  - analytics_body()  </body> 前（{% block js %} 之后）

设计要点：
  - 仅前台主题页面调用，后台管理页不注入（避免后台流量污染统计）；
  - 代码一律 |safe 渲染（统计代码本就是可执行 JS，无需转义）；
  - 双层开关：插件未启用 → 核心守卫返回 ''；启用但 analytics_enable!=1 → 函数返回 ''。
"""


def analytics_head():
    """</head> 前注入：Google Analytics + 百度统计 + 站长工具 + 自定义 head 代码。

    插件未启用时由核心 _guarded_global 守卫返回 ''；启用但总开关关闭亦返回 ''。
    """
    from app.models.setting import Setting
    if Setting.get('analytics_enable') != '1':
        return ''
    parts = [
        Setting.get('analytics_google') or '',
        Setting.get('analytics_baidu') or '',
        Setting.get('analytics_webmaster') or '',
        Setting.get('analytics_custom_head') or '',
    ]
    return ''.join(p for p in parts if p.strip())


def analytics_body():
    """</body> 前注入：自定义 body 代码。

    插件未启用时由核心 _guarded_global 守卫返回 ''；启用但总开关关闭亦返回 ''。
    """
    from app.models.setting import Setting
    if Setting.get('analytics_enable') != '1':
        return ''
    return Setting.get('analytics_custom_body') or ''
