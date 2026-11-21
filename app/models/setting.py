import json
import logging
from datetime import datetime

from flask import g, has_app_context

from ..extensions import db

logger = logging.getLogger(__name__)


class Setting(db.Model):
    """全局站点配置，key-value 形式。

    预定义 key：
      site_name / site_subtitle / site_logo / site_status / site_close_reason
      footer_copyright
      seo_title / seo_keywords / seo_description
      upload_max_size / upload_allowed_exts
    """
    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)
    # 站群模式：站点维度（全局键恒为 0；站点键为当前站点 id）
    site_id = db.Column(db.Integer, nullable=False, default=0, server_default='0', index=True)
    key = db.Column(db.String(64), nullable=False, index=True)
    value = db.Column(db.Text)
    description = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('key', 'site_id', name='uq_setting_key_site'),
    )

    # ==== CMS 自身标识（固定常量，后台使用，永远不可通过设置或演示数据修改）====
    # 与前台的“网站名称 / 前台版权”严格区分：
    #   - CMS_NAME：后台顶栏/登录页显示的 CMS 名称
    #   - CMS_COPYRIGHT：后台底部版权，永远为泰州姜堰钟毓信息技术有限公司
    CMS_NAME = '钟毓企业网站CMS'
    CMS_COPYRIGHT = '版权所有：泰州姜堰钟毓信息技术有限公司'
    # 全站显示的版本号（后台页脚等），改版本只动这里
    CMS_VERSION = '3.2.11'

    DEFAULTS = {
        # site_name 为“网站名称”，前台展示企业名称，可在网站设置中修改，演示数据会写入企业名
        'site_name': '钟毓企业网站CMS',
        'site_subtitle': '欢迎访问我们的企业官方网站',
        'site_logo': '',
        'site_status': 'open',  # open / closed
        'site_close_reason': '网站维护中，请稍后访问……',
        # footer_copyright 为“前台版权”，前台底部展示企业版权，可修改，演示数据会写入企业版权
        'footer_copyright': '版权所有：泰州姜堰钟毓信息技术有限公司',
        'seo_title': '钟毓企业网站CMS',
        'seo_keywords': '',
        'seo_description': '',
        'upload_max_size': str(10 * 1024 * 1024),  # 10MB
        'upload_allowed_exts': 'jpg,jpeg,png,gif,pdf,doc,docx,xls,xlsx,zip,rar,txt',
        # v3.1.2 M4（GitCode issue #2）：SVG 上传管控默认关闭。SVG 可携带
        # <script>/onload=/href="javascript:" 等存储型 XSS 向量，仅在管理员
        # 显式开启后允许上传，且会做内容嗅探拒绝危险片段并施加大小上限。
        'upload_allow_svg': 'off',
        'site_theme': 'default',  # 前台主题

        # ===== 模块5：登录安全 =====
        'login_max_fail': '5',            # 最大失败次数
        'login_lock_minutes': '10',       # 锁定分钟数
        'login_abnormal_city_alert': 'on',  # 异地IP登录提醒开关
        # v3.2.4：后台管理员密码复杂度策略（全局，默认沿用 v3.1.10 严格策略）
        'password_min_length': '12',
        'password_require_upper': 'on',
        'password_require_lower': 'on',
        'password_require_digit': 'on',
        'password_require_special': 'on',

        # ===== 模块6：文件上传安全与图片优化 =====
        'upload_enable_mime_check': 'on',   # MIME 二次校验
        'upload_image_auto_compress': 'on', # 图片自动压缩
        'upload_image_compress_quality': '80',  # 压缩质量 0-100
        'upload_image_thumb_enable': 'on',  # 自动生成缩略图
        'upload_image_thumb_width': '300',  # 缩略图宽度
        'upload_enable_dedup': 'on',        # 上传内容去重
        'upload_single_max_size_mb': '10',  # 后台配置：单文件最大 MB 数（冗余于 upload_max_size，便于后台可视化）

        # ===== 模块7：表单提交消息通知 =====
        'form_notify_enable': '',           # on=开启 全局通知
        'form_notify_channels': '',         # 逗号分隔：email,wework
        # 邮件通知（与 admin/setting.py setting_notify 保存的表单字段一一对应）
        'notify_email_smtp_host': '',
        'notify_email_smtp_port': '465',
        'notify_email_smtp_ssl': 'on',
        'notify_email_smtp_user': '',       # SMTP 登录账号（通常为邮箱地址）
        'notify_email_smtp_password': '',   # SMTP 登录密码
        'notify_email_sender_name': '',      # 发件人显示名，如「官网线索通知」
        'notify_email_sender_address': '',   # 发件邮箱地址（通常等于登录账号）
        'notify_email_receivers': '',        # 收件人列表，逗号分隔
        # 企业微信 Webhook
        'notify_wework_webhook': '',
        'notify_wework_mentioned_mobiles': '',  # @ 手机号，逗号分隔

        # ===== 模块8：SEO 与站点性能优化 =====
        'seo_rewrite_enable': '',           # 伪静态开关（on=开启）
        'seo_sitemap_changefreq_column': 'weekly',   # 栏目页默认更新频率
        'seo_sitemap_changefreq_article': 'monthly', # 文章页默认更新频率
        'seo_sitemap_priority_column': '0.8',
        'seo_sitemap_priority_article': '6.0',
        'seo_robots_custom': '',             # robots.txt 自定义追加内容；空则用默认
        'seo_image_alt_default': '',         # 图片默认 ALT（缺失时填充）

        # 全站缓存
        'cache_enable': '',                  # on=开启页面缓存
        'cache_ttl_index': '3600',           # 首页缓存 TTL（秒）
        'cache_ttl_column': '1800',          # 栏目列表页 TTL
        'cache_ttl_article': '7200',         # 文章详情页 TTL

        # ===== 站点资源指标告警阈值（全局） =====
        'site_metric_disk_warn_mb': '2048',   # 单站磁盘告警阈值 MB（0=关闭）
        'site_metric_article_warn': '5000',   # 单站文章数告警阈值（0=关闭）
        'site_metric_cache_warn': '20000',    # 单站缓存条目告警阈值（0=关闭）
        'site_metric_disk_limit_mb': '0',     # 单站磁盘硬上限 MB（0=不限制）

        # ===== 站点证书到期巡检（全局，只读检查不调用 certbot） =====
        'ssl_expiry_warn_days': '10',           # 剩余天数告警阈值（1-90）
        'ssl_expiry_notify_enable': 'on',       # 是否发送邮件/企业微信提醒
        'ssl_expiry_notify_channels': 'email,wework',  # 提醒渠道，逗号分隔

        # ===== 站点级备份（全局，备份目录与保留策略） =====
        'site_backup_keep_days': '30',          # 备份保留天数（0=不自动清理）
        'site_backup_max_unzip_mb': '2048',     # 导入解压总量上限 MB

        # ===== 模块2/4：审计日志 与 备份 定期清理 =====
        'audit_log_keep_days': '90',
        'backup_enable_scheduled': '',       # on=开启定时自动备份
        'backup_schedule_mode': 'daily',     # daily / weekly
        'backup_schedule_time': '03:00',     # 执行时间 HH:MM
        'backup_keep_days': '30',            # 备份保留天数
        'backup_auto_clean': 'on',           # 过期自动清理

        # ===== v2.2.0：内容 API =====
        'api_enable': 'on',                  # on=启用 / off=整体 404
        'api_token': '',                     # 非空时要求请求头 X-API-Token（旧鉴权方式）
        'api_cache_ttl': '60',               # 接口缓存秒数（0=不缓存）
        'api_cors_origins': '',              # 跨域白名单，逗号分隔，* 全部

        # ===== v2.6.3：API JWT 鉴权 + 速率限制 =====
        'api_auth_mode': 'both',             # token=旧令牌 / jwt=仅JWT / both=双轨兼容（默认）
        'jwt_secret_key': '',                # JWT 签名密钥，空则复用 SECRET_KEY
        'jwt_access_expires_minutes': '15',  # access token 过期时间（分钟）
        'jwt_refresh_expires_days': '7',     # refresh token 过期时间（天）
        'api_rate_limit_enable': 'on',       # on=开启速率限制
        'api_rate_limit_login': '5',         # 登录端点每 IP 每分钟次数
        'api_rate_limit_read': '120',        # 只读端点每 IP 每分钟次数
        # ===== v3.2.11：内容写端点（默认关闭，开启后仅 Bearer JWT）=====
        'api_write_enable': 'off',           # on=开启写端点 / off=写端点 404
        'api_rate_limit_write': '30',        # 写端点每身份每分钟次数

        # ===== v2.3.0：第三方统计代码（plugins/analytics，键值存储零迁移）=====
        'analytics_enable': '0',             # 1=启用前台注入 / 0=关闭
        'analytics_google': '',              # Google Analytics 代码（注入 head）
        'analytics_baidu': '',               # 百度统计代码（注入 head）
        'analytics_webmaster': '',            # 站长工具代码 cnzz/51la（注入 head）
        'analytics_custom_head': '',          # 自定义 </head> 前注入代码
        'analytics_custom_body': '',          # 自定义 </body> 前注入代码

        # ===== v2.3.0：国际化（Flask-Babel，核心能力非插件）=====
        'i18n_enable': '0',                  # 1=启用 / 0=关闭（默认关闭，全站中文）
        'i18n_default_locale': 'zh',         # 默认语种（zh 中文 / en 英文）
        'i18n_available_locales': 'zh',      # 可用语种清单，逗号分隔，如 zh,en

        # ===== v3.2.0：站群会员归属模式 =====
        # shared=所有站点共享会员（默认，site_id=0 哨兵，等价现网全局唯一）
        # isolated=会员归属当前站点（各站独立唯一）
        'member_scope': 'shared',

        # ===== v2.4.0：全文搜索（v3.1.4 引擎切换为 Tantivy）=====
        'search_engine': 'tantivy',            # tantivy / meilisearch / sql
        'search_meili_url': '',                # Meilisearch 服务地址
        'search_meili_key': '',                # Meilisearch API Key
        'search_index_on_save': 'on',          # on=文章保存时自动索引
        'search_results_per_page': '20',       # 每页搜索结果数
        'search_highlight': 'on',              # on=高亮匹配关键词

        # ===== 模块9：后台编辑器（v3.1.5）=====
        'editor_default_mode': 'ckeditor',     # ckeditor / markdown（仅影响新建内容）

        # ===== v2.4.0：对象存储（oss_storage 插件，键值存储零迁移）=====
        'storage_driver': 'local',             # local / aliyun / tencent / qiniu
        'oss_aliyun_access_key_id': '',        # 阿里云 AccessKey ID
        'oss_aliyun_access_key_secret': '',    # 阿里云 AccessKey Secret
        'oss_aliyun_endpoint': '',             # 如 oss-cn-hangzhou.aliyuncs.com
        'oss_aliyun_bucket': '',               # Bucket 名称
        'oss_aliyun_cdn_domain': '',           # 绑定 CDN 域名（可空，用默认域名）
        'oss_tencent_secret_id': '',           # 腾讯云 SecretId
        'oss_tencent_secret_key': '',          # 腾讯云 SecretKey
        'oss_tencent_region': '',              # 如 ap-shanghai
        'oss_tencent_bucket': '',              # Bucket 名称（含 APPID 后缀）
        'oss_tencent_cdn_domain': '',          # 绑定 CDN 域名（可空）
        'oss_qiniu_access_key': '',            # 七牛 AccessKey
        'oss_qiniu_secret_key': '',            # 七牛 SecretKey
        'oss_qiniu_bucket': '',                # 空间名
        'oss_qiniu_cdn_domain': '',            # 七牛绑定域名（必填）

        # ===== v3.1.8：安全加固（GitCode issue #12）=====
        'plugin_upload_enabled': '',           # on=允许后台直传插件包（默认关闭）

        # ===== v3.1.8：CSP 第三方资源白名单（F-001，换行分隔 origin，默认空）=====
        'security_csp_script_src': '',
        'security_csp_style_src': '',
        'security_csp_img_src': '',
        'security_csp_font_src': '',
        'security_csp_connect_src': '',
        'security_csp_media_src': '',
        'security_csp_frame_src': '',
    }

    # ===== v3.2.0 站群模式：全局键（每实例一份，与站点无关）=====
    # 全局键恒读写 site_id=0；其余键为「站点键」，读写当前站点，
    # 站点键缺失时回退 (key, 0)（默认站点/迁移前存量值），保证单站点零变化。
    GLOBAL_KEYS_EXPLICIT = frozenset({
        'member_scope',
    })
    # v3.2.6：notify_ / api_ / jwt_ / editor_default_mode 改为站点级，
    # 不同站点可分别配置通知收件人、内容 API 开关/鉴权/密钥与默认编辑器。
    GLOBAL_KEY_PREFIXES = (
        'upload_', 'login_', 'password_', 'i18n_', 'search_',
        'storage_', 'oss_', 'audit_', 'backup_', 'security_', 'redis_',
        'plugin_', 'smtp_', 'mail_',
        'member_sms_', 'member_wechat_', 'member_oauth', 'member_captcha',
        # 站点资源指标阈值属于全局配置；使用 site_metric_ 前缀，
        # 避免误把 site_name/site_theme/site_logo 等站点键全局化。
        'site_metric_',
        # 证书巡检与站点级备份属于平台运维配置，所有站点共用一套。
        'ssl_', 'site_backup_',
    )

    @classmethod
    def _is_global_key(cls, key):
        if not key:
            return False
        if key in cls.GLOBAL_KEYS_EXPLICIT:
            return True
        return key.startswith(cls.GLOBAL_KEY_PREFIXES)

    @classmethod
    def _key_site_id(cls, key):
        """返回该配置键应归属的 site_id（全局键恒 0）。"""
        if cls._is_global_key(key):
            return 0
        from ..sites import current_site_id
        return current_site_id()

    # ===== v3.1.8：敏感键入库加密（VULN-003，GitCode issue #12）=====
    # 判定规则：显式集合 + 后缀匹配（覆盖 oss_*_secret、*_password、
    # member_sms_aliyun_key_secret、member_wechat_secret 等插件敏感键）。
    # 敏感键 value 以 Fernet 密文（gAAAAA 前缀）入库，get/get_dict 返回明文。
    SENSITIVE_KEYS_EXPLICIT = frozenset({
        'api_token',
        'jwt_secret_key',
        'search_meili_key',
    })
    SENSITIVE_KEY_SUFFIXES = ('_secret', '_secret_key', '_password')

    @classmethod
    def _is_sensitive_key(cls, key):
        if not key:
            return False
        if key in cls.SENSITIVE_KEYS_EXPLICIT:
            return True
        return key.endswith(cls.SENSITIVE_KEY_SUFFIXES)

    @classmethod
    def _resolve_sensitive(cls, key, raw, cache_map=None, site_id=0):
        """敏感键读取处理：密文解密返回明文；历史明文惰性加密回写。

        惰性迁移（v3.1.8 决策）：无需 Alembic 脚本，首次读取明文敏感值时
        自动加密回写，读路径隐式写需自行提交，失败回滚降级返回明文。
        """
        if not raw:
            return raw
        from ..utils.crypto import FERNET_PREFIX, decrypt_value, encrypt_value
        if raw.startswith(FERNET_PREFIX):
            return decrypt_value(raw)
        # 惰性迁移：明文 → 加密回写
        encrypted = encrypt_value(raw)
        if encrypted != raw:
            item = cls.query.filter_by(key=key, site_id=site_id).first()
            if item is not None and item.value == raw:
                item.value = encrypted
                try:
                    db.session.commit()
                except Exception as e:
                    # 惰性迁移回写失败：降级返回明文，下次读取重试
                    db.session.rollback()
                    logger.warning('敏感键 %s 惰性迁移回写失败：%s', key, e)
                else:
                    if cache_map is not None:
                        cache_map[key] = encrypted
        return raw

    @classmethod
    def _request_cache_map(cls):
        """v3.1.3 M7（GitCode issue #3）：请求级整表缓存（g）。

        v3.2.0 站群：映射结构改为 `{site_id: {key: value}}`，
        首查整表建映射，后续读零 SQL；set() 写后失效当前请求。
        """
        if not has_app_context():
            return None
        cache_map = g.get('_settings_map')
        if cache_map is None:
            cache_map = {}
            for r in cls.query.all():
                cache_map.setdefault(r.site_id or 0, {})[r.key] = (r.value or '')
            setattr(g, '_settings_map', cache_map)
        return cache_map

    @classmethod
    def get(cls, key, default=None):
        resolved = None
        found = False
        sid = cls._key_site_id(key)
        cache_map = cls._request_cache_map()
        if cache_map is not None:
            site_map = cache_map.setdefault(sid, {})
            if key in site_map:
                resolved = site_map[key]
                found = True
            else:
                # 键不在缓存：查当前站点，站点键缺失时回退全局 (key, 0)
                item = cls.query.filter_by(key=key, site_id=sid).first()
                if item is None and sid != 0:
                    item = cls.query.filter_by(key=key, site_id=0).first()
                if item is not None:
                    resolved = item.value or ''
                    found = True
                else:
                    resolved = default if default is not None else cls.DEFAULTS.get(key, '')
                site_map[key] = resolved
        else:
            # 无应用上下文（CLI / 单测裸调用）：保持原有逐键查询行为
            item = cls.query.filter_by(key=key, site_id=sid).first()
            if item is None and sid != 0:
                item = cls.query.filter_by(key=key, site_id=0).first()
            if item is not None:
                resolved = item.value or ''
                found = True
            else:
                resolved = default if default is not None else cls.DEFAULTS.get(key, '')
        # v3.1.8 VULN-003：敏感键解密/惰性迁移（仅处理来自 DB 的值，默认值不回写）
        if found and resolved and cls._is_sensitive_key(key):
            site_map = cache_map.get(sid) if cache_map is not None else None
            return cls._resolve_sensitive(key, resolved, site_map, site_id=sid)
        return resolved

    @classmethod
    def get_dict(cls):
        from ..sites import current_site_id
        sid = current_site_id()
        result = dict(cls.DEFAULTS)
        cache_map = cls._request_cache_map()
        if cache_map is not None:
            result.update(cache_map.get(0) or {})
            if sid != 0:
                result.update(cache_map.get(sid) or {})
        else:
            for item in cls.query.filter(cls.site_id.in_([0, sid])).all():
                result[item.key] = item.value or ''
        # v3.1.8 VULN-003：模板注入的 site_settings 需拿到明文
        for k in list(result):
            if result[k] and cls._is_sensitive_key(k):
                owner = 0 if cls._is_global_key(k) else sid
                result[k] = cls._resolve_sensitive(
                    k, result[k], (cache_map or {}).get(owner), site_id=owner)
        return result

    @classmethod
    def set(cls, key, value):
        stored = str(value) if value is not None else ''
        # v3.1.8 VULN-003：敏感键加密入库（已是密文则不重复加密）
        if stored and cls._is_sensitive_key(key):
            from ..utils.crypto import FERNET_PREFIX, encrypt_value
            if not stored.startswith(FERNET_PREFIX):
                stored = encrypt_value(stored)
        sid = cls._key_site_id(key)
        item = cls.query.filter_by(key=key, site_id=sid).first()
        if item is None:
            item = cls(key=key, site_id=sid, value=stored)
            db.session.add(item)
        else:
            item.value = stored
        # v3.1.3 M7：写后失效当前请求的整表缓存，同请求内后续读立即可见
        if has_app_context():
            g.pop('_settings_map', None)
        return item

    @classmethod
    def get_for_site(cls, key, site_id, default=None):
        """按指定站点读取配置（站点管理/跨站展示用）。"""
        item = cls.query.filter_by(key=key, site_id=site_id).first()
        if item is None and site_id != 0:
            item = cls.query.filter_by(key=key, site_id=0).first()
        if item is None:
            return default if default is not None else cls.DEFAULTS.get(key, '')
        raw = item.value or ''
        if raw and cls._is_sensitive_key(key):
            return cls._resolve_sensitive(key, raw, None, site_id=site_id)
        return raw

    @classmethod
    def set_for_site(cls, key, value, site_id):
        """按指定站点写入配置（站点管理用）。"""
        cls.set_site_override(key, value, site_id)

    @classmethod
    def set_site_override(cls, key, value, site_id):
        """直接写入指定站点的配置行（不做当前站点推断）。"""
        stored = str(value) if value is not None else ''
        if stored and cls._is_sensitive_key(key):
            from ..utils.crypto import FERNET_PREFIX, encrypt_value
            if not stored.startswith(FERNET_PREFIX):
                stored = encrypt_value(stored)
        item = cls.query.filter_by(key=key, site_id=site_id).first()
        if item is None:
            item = cls(key=key, site_id=site_id, value=stored)
            db.session.add(item)
        else:
            item.value = stored
        if has_app_context():
            g.pop('_settings_map', None)
        return item

    @classmethod
    def get_upload_max_size(cls):
        try:
            return int(cls.get('upload_max_size', cls.DEFAULTS['upload_max_size']))
        except (TypeError, ValueError):
            return 10 * 1024 * 1024

    @classmethod
    def get_allowed_exts(cls):
        raw = cls.get('upload_allowed_exts', cls.DEFAULTS['upload_allowed_exts'])
        return [e.strip().lower() for e in raw.split(',') if e.strip()]

    @classmethod
    def get_editor_default_mode(cls):
        """后台编辑器默认模式（v3.1.5）：ckeditor / markdown，非法值回退 ckeditor。"""
        from ..constants import Editor
        mode = (cls.get('editor_default_mode') or '').strip()
        return mode if mode in Editor.MODES else Editor.MODE_CKEDITOR
