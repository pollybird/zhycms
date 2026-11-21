"""内容 API 的 OpenAPI 3.0 契约注册表（v3.2.11）。

不引入额外 Web 框架：视图函数通过 ``@openapi_doc`` 挂载元数据，
``build_spec`` 遍历 Flask 路由表合并生成契约；脚本据此输出 YAML，
门禁脚本反向校验"所有 /api/v1 路由都有契约或显式排除"。
"""
import re

# 明确不进入公开契约的路由（endpoint 名）。新增排除项必须写明原因。
OPENAPI_SKIP = {
    # 契约自身的 JSON 端点，避免自引用
    'api.api_openapi',
}

_PATH_PARAM_RE = re.compile(r'<(?:[^:<>]+:)?([^<>]+)>')


def openapi_doc(summary, tags=None, params=None, body=None, responses=None,
                auth='both', write=False):
    """为 API 视图挂载 OpenAPI 元数据。

    auth: ``both`` = JWT 或静态 Token；``jwt`` = 仅 Bearer JWT；``none`` = 公开。
    """
    def decorator(view_func):
        view_func.__openapi__ = {
            'summary': summary,
            'tags': list(tags or []),
            'params': list(params or []),
            'body': body,
            'responses': responses or {'200': {'description': '成功'}},
            'auth': auth,
            'write': bool(write),
        }
        return view_func
    return decorator


def _normalize_path(rule):
    """把 Flask 参数语法转换为 OpenAPI 路径参数语法。"""
    return _PATH_PARAM_RE.sub(lambda m: '{%s}' % m.group(1), str(rule))


def _operation(meta):
    op = {
        'summary': meta.get('summary') or '',
        'tags': meta.get('tags') or [],
        'responses': meta.get('responses') or {'200': {'description': '成功'}},
    }
    if meta.get('params'):
        op['parameters'] = meta['params']
    if meta.get('body'):
        op['requestBody'] = {
            'required': True,
            'content': {'application/json': {'schema': meta['body']}},
        }
    auth = meta.get('auth', 'both')
    if auth == 'jwt':
        op['security'] = [{'bearerAuth': []}]
    elif auth == 'none':
        op['security'] = []
    else:
        op['security'] = [{'bearerAuth': []}, {'apiToken': []}]
    return op


def iter_api_rules(app):
    """产出 (rule, methods, endpoint, meta) 供生成器与门禁复用。"""
    for rule in app.url_map.iter_rules():
        path = str(rule.rule)
        if not path.startswith('/api/v1/'):
            continue
        view = app.view_functions.get(rule.endpoint)
        meta = getattr(view, '__openapi__', None) if view else None
        methods = sorted(set(rule.methods or set()) - {'HEAD', 'OPTIONS'})
        yield rule, methods, rule.endpoint, meta


def build_spec(app):
    """根据路由表与元数据生成 OpenAPI 3.0 字典。"""
    from ..models.setting import Setting

    paths = {}
    for rule, methods, _endpoint, meta in iter_api_rules(app):
        if meta is None:
            continue
        path = _normalize_path(rule.rule)
        for method in methods:
            paths.setdefault(path, {})[method.lower()] = _operation(meta)

    return {
        'openapi': '3.0.3',
        'info': {
            'title': 'ZhyCMS Content API',
            'version': Setting.CMS_VERSION,
            'description': (
                'ZhyCMS 对外内容 API。只读端点支持 Bearer JWT 或 X-API-Token；'
                '写端点默认关闭，开启后仅接受 Bearer JWT。'
            ),
        },
        'servers': [{'url': '/'}],
        'tags': [
            {'name': 'site', 'description': '站点信息'},
            {'name': 'content', 'description': '栏目与文章'},
            {'name': 'auth', 'description': 'JWT 鉴权'},
            {'name': 'forms', 'description': '表单提交'},
            {'name': 'sites', 'description': '站点与资源计量（超管）'},
            {'name': 'plugins', 'description': '插件内容'},
        ],
        'paths': paths,
        'components': {
            'securitySchemes': {
                'bearerAuth': {
                    'type': 'http',
                    'scheme': 'bearer',
                    'bearerFormat': 'JWT',
                },
                'apiToken': {
                    'type': 'apiKey',
                    'in': 'header',
                    'name': 'X-API-Token',
                },
            },
            'schemas': {
                'Envelope': {
                    'type': 'object',
                    'properties': {
                        'code': {'type': 'integer'},
                        'message': {'type': 'string'},
                        'data': {},
                        'meta': {'type': 'object', 'nullable': True},
                    },
                },
            },
        },
    }
