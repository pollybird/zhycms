"""插件站点作用域审计。

通过 AST 静态扫描 `plugins/*/models.py` 等文件，判断插件的数据模型与
查询入口是否带站点维度。脚本与运行时共用，避免两套判定逻辑漂移。

规则：
- R1：映射表缺少 `site_id` 且不在豁免清单；
- R2：`slug`/`code`/`name` 仍为单列 `unique=True`（未改为 (site_id, slug) 复合唯一）；
- R3：查询次数多于站点过滤引用次数（警告，不判定未适配）；
- R4：`search.sql_search` 缺少 `site_id` 参数。
"""
import ast
import fnmatch
import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
PLUGINS_DIR = os.path.join(_PROJECT_ROOT, 'plugins')
EXEMPT_FILE = os.path.join(
    _PROJECT_ROOT, 'scripts', 'plugin_site_scope_exempt.txt')
REPORT_FILE = os.path.join(
    _PROJECT_ROOT, 'build', 'plugin-site-scope.json')

CACHE_SECONDS = 600

# 靠父表外键隔离的子表：父表已带 site_id，子表不重复存储
DEFAULT_EXEMPT = (
    '*Translation',
    'FormField',
    'FormSubmission',
    'FormSubmissionValue',
    'MemberSmsCode',
    'RecruitApplication',
)

_report_cache = {'at': 0.0, 'data': None}


def load_exempt_patterns(path=EXEMPT_FILE):
    """读取豁免清单（每行一个通配符，`#` 之后为注释）。"""
    patterns = list(DEFAULT_EXEMPT)
    try:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                pattern = line.split('#', 1)[0].strip()
                if pattern:
                    patterns.append(pattern)
    except OSError as e:
        logger.warning('读取插件站点作用域豁免清单失败：%s', e)
    return patterns


def _is_exempt(name, patterns):
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def _attr_name(node):
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ''


def _target_names(stmt):
    if isinstance(stmt, ast.Assign):
        return [t.id for t in stmt.targets if isinstance(t, ast.Name)]
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return [stmt.target.id]
    return []


def _is_mapped_class(node):
    if not isinstance(node, ast.ClassDef):
        return False
    for stmt in node.body:
        if '__tablename__' in _target_names(stmt):
            return True
    for base in node.bases:
        name = _attr_name(base)
        if name.endswith('Model') or name.endswith('Base'):
            return True
    return False


def _class_meta(node):
    table_name = None
    has_site_id = False
    unique_single = []

    for base in node.bases:
        if 'SiteScoped' in _attr_name(base):
            has_site_id = True

    for stmt in node.body:
        names = _target_names(stmt)
        if '__tablename__' in names and isinstance(stmt.value, ast.Constant):
            table_name = str(stmt.value.value)
        if 'site_id' in names:
            has_site_id = True

        # slug / code / name 列仍为单列唯一约束
        candidates = [n for n in names if n in ('slug', 'code', 'name')]
        if not candidates or not isinstance(stmt.value, ast.Call):
            continue
        for keyword in stmt.value.keywords:
            if (keyword.arg == 'unique'
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True):
                unique_single.append(candidates[0])

    return {
        'class': node.name,
        'table': table_name or node.name,
        'site_id': has_site_id,
        'unique_single': unique_single,
    }


def _parse_model_file(path):
    try:
        with open(path, encoding='utf-8') as fh:
            tree = ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError) as e:
        logger.warning('解析插件模型文件失败 %s：%s', path, e)
        return []
    return [_class_meta(node) for node in ast.walk(tree)
            if _is_mapped_class(node)]


def _model_files(plugin_dir):
    files = []
    models_py = os.path.join(plugin_dir, 'models.py')
    if os.path.isfile(models_py):
        files.append(models_py)
    models_dir = os.path.join(plugin_dir, 'models')
    if os.path.isdir(models_dir):
        for name in sorted(os.listdir(models_dir)):
            if name.endswith('.py'):
                files.append(os.path.join(models_dir, name))
    return files


def _read_manifest(plugin_dir):
    path = os.path.join(plugin_dir, 'manifest.json')
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as e:
        logger.debug('读取插件清单失败 %s：%s', path, e)
        return {}


def _query_reference_counts(plugin_dir):
    """粗略统计插件业务代码中的查询次数与站点过滤引用次数。"""
    queries = 0
    site_refs = 0
    for name in os.listdir(plugin_dir):
        if not name.endswith('.py') or name in ('models.py', '__init__.py'):
            continue
        path = os.path.join(plugin_dir, name)
        try:
            with open(path, encoding='utf-8') as fh:
                source = fh.read()
        except OSError as e:
            logger.debug('读取插件文件失败 %s：%s', path, e)
            continue
        queries += len(re.findall(r'\.query\b', source))
        site_refs += len(re.findall(
            r'site_id|current_site_id|accessible_sites', source))
    return queries, site_refs


def _search_missing_site(plugin_dir):
    path = os.path.join(plugin_dir, 'search.py')
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding='utf-8') as fh:
            tree = ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError) as e:
        logger.warning('解析插件搜索模块失败 %s：%s', path, e)
        return False

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == 'sql_search':
            args = [a.arg for a in node.args.args]
            return 'site_id' not in args
    return False


def _scan_plugin(plugin_dir, exempt_patterns):
    slug = os.path.basename(plugin_dir.rstrip(os.sep))
    manifest = _read_manifest(plugin_dir)
    classes = []
    for path in _model_files(plugin_dir):
        classes.extend(_parse_model_file(path))

    rules = []
    warnings = []
    tables = []

    for meta in classes:
        tables.append(meta['table'])
        exempt = (_is_exempt(meta['class'], exempt_patterns)
                  or _is_exempt(meta['table'], exempt_patterns))
        if exempt:
            continue
        if not meta['site_id']:
            rules.append({
                'rule': 'R1',
                'detail': f'{meta["class"]} 缺少 site_id',
            })
        for column in meta['unique_single']:
            rules.append({
                'rule': 'R2',
                'detail': f'{meta["class"]}.{column} 仍为单列唯一',
            })

    queries, site_refs = _query_reference_counts(plugin_dir)
    if queries > site_refs:
        warnings.append({
            'rule': 'R3',
            'detail': f'查询 {queries} 次，站点过滤引用 {site_refs} 处',
        })

    if _search_missing_site(plugin_dir):
        rules.append({'rule': 'R4', 'detail': 'sql_search 缺少 site_id 参数'})

    if not classes:
        status = 'no_tables'
    elif rules:
        status = 'unadapted'
    else:
        status = 'adapted'

    return {
        'slug': slug,
        'name': manifest.get('name') or slug,
        'version': manifest.get('version') or '',
        'status': status,
        'rules': rules,
        'warnings': warnings,
        'tables': tables,
        'query_count': queries,
        'site_ref_count': site_refs,
    }


def audit_plugins(plugins_dir=PLUGINS_DIR, exempt_file=EXEMPT_FILE):
    """扫描全部插件，返回 {'generated_at', 'plugins'}。"""
    patterns = load_exempt_patterns(exempt_file)
    plugins = []
    if os.path.isdir(plugins_dir):
        for name in sorted(os.listdir(plugins_dir)):
            path = os.path.join(plugins_dir, name)
            if os.path.isdir(path) and _model_files(path):
                plugins.append(_scan_plugin(path, patterns))
            elif os.path.isdir(path) and os.path.isfile(
                    os.path.join(path, 'manifest.json')):
                plugins.append(_scan_plugin(path, patterns))
    return {
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'plugins': plugins,
    }


def load_or_scan_report(max_age=CACHE_SECONDS):
    """优先读取构建产物；过期或缺失时现场扫描并缓存。"""
    if os.path.isfile(REPORT_FILE):
        try:
            if time.time() - os.path.getmtime(REPORT_FILE) <= max_age:
                with open(REPORT_FILE, encoding='utf-8') as fh:
                    return json.load(fh)
        except (OSError, ValueError) as e:
            logger.warning('读取插件站群适配报告失败，改为现场扫描：%s', e)

    now = time.time()
    cached = _report_cache.get('data')
    if cached is not None and now - _report_cache['at'] <= max_age:
        return cached

    report = audit_plugins()
    _report_cache['at'] = now
    _report_cache['data'] = report
    return report


def unadapted_slugs():
    """返回未适配站群作用域的插件标识集合。"""
    report = load_or_scan_report()
    return {
        item['slug'] for item in report.get('plugins', [])
        if item.get('status') == 'unadapted'
    }


def to_markdown(report):
    """把报告渲染为 Markdown 表格。"""
    lines = [
        '| 插件 | 版本 | 结论 | 规则 | 数据表 |',
        '| --- | --- | --- | --- | --- |',
    ]
    for item in report.get('plugins', []):
        rules = '、'.join(
            f'{r["rule"]} {r["detail"]}' for r in item.get('rules', [])) or '-'
        tables = ', '.join(item.get('tables', [])) or '-'
        lines.append(
            f'| {item["slug"]} | {item.get("version") or "-"} | '
            f'{item["status"]} | {rules} | {tables} |')
    return '\n'.join(lines) + '\n'
