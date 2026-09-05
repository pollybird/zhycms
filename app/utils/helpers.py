"""通用工具函数与模板过滤器注册 + RBAC 权限装饰器 + 审计日志快捷方法。"""
from functools import wraps
import json
import re
from datetime import datetime

from flask import request, redirect, url_for, abort, flash, current_app
from flask_login import current_user


from flask_babel import gettext as _gettext
# ============================================================
# 后台通用鉴权
# ============================================================

def admin_required(func):
    """后台登录鉴权装饰器（旧名保留，兼容）；实际做登录 + 账号启用状态校验。"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('admin_auth.login', next=request.path))
        # 账号被禁用则踢下线
        u = current_user
        if getattr(u, 'is_deleted', False) or (hasattr(u, 'is_active_flag') and not u.is_active_flag):
            from flask_login import logout_user
            logout_user()
            flash(_gettext('账号已被禁用，请联系超级管理员'), 'warning')
            return redirect(url_for('admin_auth.login'))
        return func(*args, **kwargs)
    return wrapper


def permission_required(perm_code, column_id_arg=None, any_of=None):
    """RBAC 权限校验装饰器。

    - perm_code: 权限点 code，见 app.models.rbac.PERMISSION_DEFS
    - column_id_arg: 若校验「栏目专属权限」，传入函数参数中的栏目 ID 形参名（字符串）；
      装饰器会从 kwargs 或 request.form/args 中尝试读取该值并调用 current_user.can_access_column()
    - any_of: 备用权限点列表；用户无 perm_code 但拥有其中任一权限时同样放行
      （典型场景：栏目列表页作为内容管理的导航入口，对拥有内容操作权限的编辑开放浏览）
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('admin_auth.login', next=request.path))
            u = current_user
            if getattr(u, 'is_deleted', False) or (hasattr(u, 'is_active_flag') and not u.is_active_flag):
                from flask_login import logout_user
                logout_user()
                flash(_gettext('账号已被禁用'), 'warning')
                return redirect(url_for('admin_auth.login'))

            # 超级管理员直接放行
            if getattr(u, 'is_super', False):
                return func(*args, **kwargs)

            # 校验权限（any_of 任一命中即可替代 perm_code）
            if not u.has_permission(perm_code):
                if not (any_of and any(u.has_permission(c) for c in any_of)):
                    abort(403)

            # 栏目专属权限校验（content_* 类路由需要）
            if column_id_arg:
                cid = kwargs.get(column_id_arg)
                if cid is None:
                    cid = request.values.get(column_id_arg)
                if cid is not None:
                    try:
                        cid_int = int(cid)
                    except (TypeError, ValueError):
                        cid_int = None
                    if cid_int is not None and not u.can_access_column(cid_int):
                        abort(403)

            return func(*args, **kwargs)
        return wrapper
    return decorator


# ============================================================
# 登录日志
# ============================================================

def log_login(username, result, message='', user_id=None, city=None):
    """记录登录日志（模块5：扩展 user_id 与 city 字段）。"""
    from ..extensions import db
    from ..models.user import LoginLog
    log = LoginLog(
        username=username,
        user_id=user_id,
        ip=request.remote_addr or '',
        city=city,
        user_agent=request.user_agent.string[:255] if request.user_agent else '',
        result=result,
        message=message,
    )
    db.session.add(log)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


# ============================================================
# 审计日志快捷方法（供各模块调用）
# ============================================================

# 详情 JSON 键 → 中文标签
AUDIT_FIELD_LABELS = {
    'ip': 'IP 地址', 'city': '登录城市', 'abnormal': '异地登录',
    'user_agent': '浏览器',
    'nickname': '昵称', 'email': '邮箱', 'role_ids': '分配角色', 'role_id': '角色',
    'is_active': '账号启用', 'is_active_flag': '账号启用', 'pwd_changed': '密码已重置',
    'deleted_count': '删除条数',
    'column_id': '所属栏目', 'status': '内容状态', 'article_id': '文章',
    'form_id': '表单', 'form': '表单', 'parent_id': '父栏目',
    'category': '配置分类', 'changed_keys': '变更项', 'changed': '变更项',
    'action': '动作', 'code': '角色标识', 'result': '结果',
    'permission_codes_count': '权限点数量',
    'count': '数量', 'ok_count': '成功数', 'fail_count': '失败数',
    'ids': '记录编号', 'filename': '文件名', 'backup_type': '备份方式',
    'sub_dir': '保存目录', 'url': '访问地址', 'path': '存储路径',
    'size': '文件大小', 'keep_days': '保留天数',
    'message': '说明', 'reason': '原因', 'slug': 'URL 别名',
    'title': '标题', 'keywords': '关键词', 'content': '内容',
    'summary': '摘要', 'target': '目标', 'module': '模块',
    'old_name': '原名称', 'new_name': '新名称', 'sort': '排序',
    'type': '类型', 'name': '名称', 'template': '模板',
    'visible': '前台可见', 'compressed': '已压缩', 'dedup': '重复文件',
    'width': '宽度', 'height': '高度', 'thumb': '缩略图',
    'total': '总计', 'rows': '行数', 'days': '天数',
    'filters': '筛选条件', 'keyword': '关键词', 'op_type': '操作类型',
    'date_from': '开始日期', 'date_to': '结束日期', 'username': '操作人',
    'from_status': '原状态', 'from_column_id': '来源栏目',
    'target_column_id': '目标栏目', 'to_version_no': '回滚至版本',
    'title_snapshot': '标题快照', 'is_enabled': '是否启用',
    'enable': '启用定时备份', 'mode': '调度模式', 'time': '执行时间',
    'error': '错误信息', 'file_size_mb': '文件大小（MB）', 'remark': '备注',
    'from': '来源',
}

# changed_keys / changed 内层 Setting 配置键 → 中文名（键名以各视图实际代码为准）
AUDIT_SETTING_KEY_LABELS = {
    'site_name': '网站名称', 'site_subtitle': '网站副标题',
    'site_close_reason': '站点关闭公告', 'site_status': '站点状态',
    'site_theme': '前台主题', 'site_logo': '网站 LOGO',
    'footer_copyright': '版权文字',
    'site_seo_title': 'SEO 标题', 'site_seo_keywords': 'SEO 关键词',
    'site_seo_description': 'SEO 描述',
    'seo_default_title': 'SEO 默认标题', 'seo_default_keywords': 'SEO 默认关键词',
    'seo_default_description': 'SEO 默认描述',
    'seo_rewrite_enable': '伪静态开关',
    'seo_sitemap_changefreq_column': 'Sitemap 栏目更新频率',
    'seo_sitemap_changefreq_article': 'Sitemap 文章更新频率',
    'seo_sitemap_priority_column': 'Sitemap 栏目优先级',
    'seo_sitemap_priority_article': 'Sitemap 文章优先级',
    'seo_sitemap_enable': 'Sitemap 开关',
    'seo_robots_custom': 'robots 自定义规则',
    'seo_image_alt_default': '图片默认 ALT',
    'cache_enable': '页面缓存', 'cache_ttl': '缓存时长（秒）',
    'cache_ttl_index': '首页缓存时长（秒）',
    'cache_ttl_column': '栏目页缓存时长（秒）',
    'cache_ttl_article': '文章页缓存时长（秒）',
    'upload_max_size': '上传大小上限（KB）', 'upload_max_size_kb': '上传大小上限（KB）',
    'upload_max_mb': '上传大小上限（MB）',
    'upload_allowed_exts': '允许上传后缀',
    'upload_enable_mime_check': 'MIME 双重校验', 'upload_mime_check': 'MIME 双重校验',
    'upload_enable_dedup': '重复上传去重', 'upload_dedup_enable': '重复上传去重',
    'upload_single_max_size_mb': '单文件大小上限（MB）',
    'upload_image_auto_compress': '图片自动压缩', 'img_compress_enable': '图片自动压缩',
    'upload_image_compress_quality': '图片压缩质量', 'img_compress_quality': '图片压缩质量',
    'upload_image_thumb_enable': '缩略图开关', 'img_thumb_enable': '缩略图开关',
    'upload_image_thumb_width': '缩略图宽度', 'img_thumb_width': '缩略图宽度',
    'login_max_fail': '登录失败上限', 'login_lock_minutes': '锁定时长（分钟）',
    'login_captcha_enable': '登录验证码', 'login_captcha': '登录验证码',
    'login_abnormal_alert': '异地登录提醒', 'login_abnormal_city_alert': '异地城市登录提醒',
    'admin_prefix': '后台地址前缀',
    'audit_keep_days': '审计日志保留天数', 'backup_keep_days': '备份保留天数',
    'form_notify_enable': '表单通知开关', 'form_notify_channels': '通知渠道',
    'notify_email_enable': '邮件通知', 'notify_email_smtp_host': 'SMTP 服务器',
    'notify_email_smtp_port': 'SMTP 端口', 'notify_email_smtp_ssl': 'SMTP SSL',
    'notify_email_smtp_user': 'SMTP 账号', 'notify_email_smtp_password': 'SMTP 登录密码',
    'notify_email_sender_name': '发件人名称', 'notify_email_sender_address': '发件人地址',
    'notify_email_receivers': '通知接收邮箱',
    'notify_wework_enable': '企业微信通知', 'notify_wecom_enable': '企业微信通知',
    'notify_wework_webhook': '企业微信 Webhook', 'notify_wecom_webhook': '企业微信 Webhook',
    'notify_wework_mentioned_mobiles': '企业微信提醒手机号',
    'notify_wecom_mention_mobiles': '企业微信提醒手机号',
}

# 特定配置键的值级映射
AUDIT_VALUE_ENUMS = {
    'site_status': {'open': '开放中', 'closed': '已关闭'},
    'site_theme': {'default': '经典默认', 'blue': '科技蓝',
                   'manufacturing': '制造业模板', 'service': '服务业模板'},
    'seo_sitemap_changefreq_column': {'always': '始终', 'hourly': '每小时', 'daily': '每天',
                                      'weekly': '每周', 'monthly': '每月', 'yearly': '每年',
                                      'never': '从不'},
    'mode': {'daily': '每天', 'weekly': '每周', 'monthly': '每月', 'hourly': '每小时'},
    'from': {'upload': '上传文件包'},
}

# op_type / status 兜底值映射
AUDIT_OP_TYPE_LABELS = {
    'create': '新增', 'update': '修改', 'delete': '删除', 'login': '登录',
    'logout': '登出', 'config_change': '配置变更', 'review_pass': '审核通过',
    'review_reject': '审核驳回', 'publish': '发布', 'archive': '归档',
    'rollback': '回滚', 'batch': '批量操作', 'user_manage': '用户管理',
    'upload': '上传', 'export': '导出', 'backup_create': '创建备份',
    'backup_restore': '恢复备份',
}
AUDIT_RESULT_BACKUP_LABELS = {'success': '成功', 'failed': '失败', 'error': '异常'}

# 值可能为 (旧值, 新值) 变更对的顶层键（如个人资料的昵称/邮箱）
AUDIT_PAIR_KEYS = {'nickname', 'email', 'title', 'slug', 'name', 'summary',
                   'keywords', 'content', 'password', 'sort', 'remark'}

# detail 值级映射
AUDIT_CATEGORY_LABELS = {
    'site': '网站设置', 'seo': 'SEO 设置', 'seo_advanced': 'SEO 高级',
    'upload': '上传配置', 'security': '后台安全', 'notify': '消息通知',
    'cache': '页面缓存', 'backup': '备份策略',
}
AUDIT_ACTION_LABELS = {
    'reset_password': '重置密码', 'toggle_active': '启用/禁用账号',
    'clean': '清理', 'clear': '清空', 'export': '导出',
    'restore': '恢复', 'move': '移动', 'login': '登录',
    'submit_review': '提交审核', 'toggle': '切换状态',
    'update_schedule': '更新定时配置', 'profile': '更新个人资料',
    'change_password': '修改密码', 'clean_expired': '清理过期日志',
    'download': '下载', 'publish': '发布', 'archive': '归档',
}
AUDIT_RESULT_LABELS = {'success': '成功', 'fail': '失败', 'partial': '部分成功'}


def audit_log(op_type, module, target_id=None, target_name=None, detail=None):
    """写入一条审计日志。参数定义见 models.audit.AuditLog.record。"""
    from ..models.audit import AuditLog
    try:
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False, default=str)
        AuditLog.record(
            op_type=op_type, module=module,
            target_id=target_id, target_name=target_name, detail=detail,
        )
    except Exception:
        current_app.logger.exception('write audit log failed')


# ============================================================
# 缓存清除（模块8：内容变更时自动清相关页面缓存）
# ============================================================

def clear_content_cache(column_id=None, article_id=None):
    """内容新增/修改/删除/发布后，清除前台首页、栏目页、文章页相关缓存，
    并触发搜索索引更新（v2.4.0）。"""
    from ..extensions import cache
    from ..models.setting import Setting
    # v2.4.0：搜索索引更新（独立于缓存开关）
    if article_id:
        try:
            from ..utils.search import reindex_article
            reindex_article(article_id)
        except Exception:
            current_app.logger.exception('reindex_article failed')
    if Setting.get('cache_enable') != 'on':
        return
    keys = []
    # 首页
    keys.append('frontend/index')
    if column_id:
        keys.append(f'frontend/column/{column_id}')
    if article_id:
        keys.append(f'frontend/article/{article_id}')
    for k in keys:
        try:
            cache.delete(k)
        except Exception:
            pass
    # 简单起见，直接清整站缓存（覆盖 sitemap 等关联）
    try:
        cache.clear()
    except Exception:
        pass


# ============================================================
# 模板过滤器
# ============================================================

def register_template_filters(app):
    @app.template_filter('datetime')
    def format_datetime(value, fmt='%Y-%m-%d %H:%M:%S'):
        if not value:
            return ''
        if isinstance(value, str):
            return value
        return value.strftime(fmt)

    @app.template_filter('date')
    def format_date(value, fmt='%Y-%m-%d'):
        if not value:
            return ''
        if isinstance(value, str):
            return value
        return value.strftime(fmt)

    @app.template_filter('datetime_format')
    def datetime_format(value, fmt='%Y-%m-%d %H:%M:%S'):
        """datetime 过滤器别名（模板沿用历史命名 datetime_format）。"""
        if not value:
            return ''
        if isinstance(value, str):
            return value
        return value.strftime(fmt)

    @app.template_filter('truncate_text')
    def truncate_text(value, length=50):
        if not value:
            return ''
        text = str(value)
        return text[:length] + '...' if len(text) > length else text

    @app.template_filter('highlight')
    def highlight_filter(value, keyword=''):
        """高亮搜索关键词：将匹配部分包裹在 <mark> 标签中。

        安全修复（v2.4.1）：先对原文与关键词做 HTML 转义，再仅对转义后的
        匹配文本包裹 <mark>，杜绝存储型 XSS（文章标题/摘要中的 HTML/JS
        此前因 |safe 直接渲染而被执行）。
        """
        from markupsafe import escape, Markup
        if not value or not keyword:
            return value or ''
        import re as _re
        safe_value = escape(str(value))
        safe_keyword = escape(str(keyword))
        # 在已转义文本上做正则匹配（关键词经 escape 后可能含实体如 &lt;）
        pattern = _re.escape(str(safe_keyword))
        result = _re.sub(
            pattern, f'<mark>{safe_keyword}</mark>', str(safe_value),
            flags=_re.IGNORECASE
        )
        return Markup(result)

    @app.template_filter('audit_detail')
    def audit_detail(value, maps=None, compact=False):
        """审计日志详情人性化：JSON 转中文描述，普通字符串原样。

        - maps: {'roles': {id: 角色名}, 'columns': {id: 栏目名}}，用于把 ID 翻译成名称
        - 返回 HTML（内部已逐值转义），模板需配合 |safe 使用
        """
        from markupsafe import escape
        maps = maps or {}

        def fmt_scalar(v, key=''):
            """单值渲染（返回已转义 str）。"""
            if v is None or v == '':
                return '<span class="text-muted">—</span>'
            if isinstance(v, bool):
                return '是' if v else '否'
            if key == 'size' and isinstance(v, (int, float)):
                num = float(v)
                return f'{num / 1024 / 1024:.2f} MB' if num >= 1024 * 1024 else f'{num / 1024:.1f} KB'
            text = str(v)
            # 值级语义映射
            if text == '***changed***':
                return '（已更新，值略）'
            if text == 'on':
                return '开启'
            if text == 'off':
                return '关闭'
            enum = AUDIT_VALUE_ENUMS.get(key)
            if enum is not None and text in enum:
                text = enum[text]
            elif key in ('status',):
                from ..models.workflow import STATUS_CHOICES
                text = dict(STATUS_CHOICES).get(v) \
                    or AUDIT_RESULT_BACKUP_LABELS.get(v, text)
            elif key == 'op_type':
                text = AUDIT_OP_TYPE_LABELS.get(v, text)
            elif key == 'category':
                text = AUDIT_CATEGORY_LABELS.get(v, text)
            elif key == 'action':
                text = AUDIT_ACTION_LABELS.get(v, text)
            elif key == 'result':
                text = AUDIT_RESULT_LABELS.get(v, text)
            elif key in ('role_ids', 'role_id') and isinstance(v, int):
                text = maps.get('roles', {}).get(v, f'角色 #{v}')
            elif key in ('column_id', 'from_column_id', 'target_column_id', 'parent_id') \
                    and isinstance(v, int):
                text = maps.get('columns', {}).get(v, f'栏目 #{v}')
            if len(text) > 80:
                text = text[:80] + '…'
            return str(escape(text))

        def fmt_change_val(v, sub_key=''):
            """changed 内层值：识别 [旧值, 新值] 变更对。"""
            if isinstance(v, (list, tuple)) and len(v) == 2 and not isinstance(v[0], (list, dict)) \
                    and not isinstance(v[1], (list, dict)):
                return f'{fmt_scalar(v[0], sub_key)} <span class="text-muted">→</span> {fmt_scalar(v[1], sub_key)}'
            if isinstance(v, dict):
                return '、'.join(fmt_change_val(sv, str(sk)) for sk, sv in v.items())
            return fmt_scalar(v, sub_key)

        def fmt_value(v, key=''):
            if isinstance(v, dict):
                # 嵌套变更字典（如 config 变更 changed）：逐子键翻译渲染
                segs = []
                for sk, sv in v.items():
                    label = AUDIT_SETTING_KEY_LABELS.get(str(sk),
                                                         AUDIT_FIELD_LABELS.get(str(sk), str(sk)))
                    segs.append(f'&nbsp;&nbsp;· <b>{escape(str(label))}：</b>{fmt_change_val(sv, str(sk))}')
                return '<br>'.join(segs) or '<span class="text-muted">无</span>'
            if isinstance(v, (list, tuple)):
                if key == 'changed_keys':
                    parts = [AUDIT_SETTING_KEY_LABELS.get(str(i), str(i)) for i in v]
                    return '、'.join(parts)
                if key == 'role_ids':
                    parts = [maps.get('roles', {}).get(i, f'角色 #{i}') for i in v]
                    return '、'.join(str(escape(p)) for p in parts)
                # 顶层 (旧值, 新值) 变更对（如个人资料的昵称/邮箱）
                if key in AUDIT_PAIR_KEYS and len(v) == 2 \
                        and not isinstance(v[0], (list, dict)) and not isinstance(v[1], (list, dict)):
                    return (f'{fmt_scalar(v[0], key)} <span class="text-muted">→</span>'
                            f' {fmt_scalar(v[1], key)}')
                return '、'.join(fmt_scalar(i, key) for i in v) or '<span class="text-muted">—</span>'
            return fmt_scalar(v, key)

        # 非 JSON：原样（转义）
        if isinstance(value, (dict, list)) or (
                isinstance(value, str) and value.lstrip().startswith(('{', '['))):
            try:
                data = json.loads(value) if isinstance(value, str) else value
            except (ValueError, TypeError):
                data = None
            if isinstance(data, dict):
                if compact:
                    # 紧凑单行摘要：最多前 3 个键，"标签：值"以 ； 分隔（用于仪表盘等窄列表格）
                    items = []
                    for k, v in list(data.items())[:3]:
                        label = AUDIT_FIELD_LABELS.get(k, k)
                        seg = re.sub(r'<[^>]+>', '', f'{label}：{fmt_value(v, k)}').strip()
                        items.append(' '.join(seg.split()))
                    text = '；'.join(items)
                    return str(escape(text[:70])) + ('…' if len(text) > 70 else '')
                parts = []
                for k, v in data.items():
                    label = AUDIT_FIELD_LABELS.get(k, k)
                    parts.append(f'<b>{escape(str(label))}：</b>{fmt_value(v, k)}')
                return '<br>'.join(parts) if parts else '<span class="text-muted">无</span>'
            if isinstance(data, list):
                return '、'.join(escape(str(i)) for i in data) or '<span class="text-muted">无</span>'
        text = str(value) if value is not None else ''
        return str(escape(text)) if text else ''

    @app.template_filter('status_label')
    def status_label(value):
        """工作流状态转中文字典。"""
        from ..models.workflow import STATUS_CHOICES
        for k, v in STATUS_CHOICES:
            if k == value:
                return v
        return value or ''

    @app.template_filter('filesize')
    def filesize(num):
        """字节数转可读大小。"""
        try:
            num = int(num or 0)
        except (TypeError, ValueError):
            return '0 B'
        step = 1024
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if num < step:
                return f'{num:.1f} {unit}' if unit != 'B' else f'{num} {unit}'
            num /= step
        return f'{num:.1f} PB'

    @app.template_filter('op_type_label')
    def op_type_label(code):
        from ..models.audit import OP_TYPE_CHOICES
        for k, v in OP_TYPE_CHOICES:
            if k == code:
                return v
        return code or ''
