import json
from datetime import datetime

from ..extensions import db


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
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    description = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # ==== CMS 自身标识（固定常量，后台使用，永远不可通过设置或演示数据修改）====
    # 与前台的“网站名称 / 前台版权”严格区分：
    #   - CMS_NAME：后台顶栏/登录页显示的 CMS 名称
    #   - CMS_COPYRIGHT：后台底部版权，永远为泰州姜堰钟毓信息技术有限公司
    CMS_NAME = '钟毓企业网站CMS'
    CMS_COPYRIGHT = '版权所有：泰州姜堰钟毓信息技术有限公司'
    # 全站显示的版本号（后台页脚等），改版本只动这里
    CMS_VERSION = '2.6.0'

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
        'site_theme': 'default',  # 前台主题

        # ===== 模块5：登录安全 =====
        'login_max_fail': '5',            # 最大失败次数
        'login_lock_minutes': '10',       # 锁定分钟数
        'login_abnormal_city_alert': 'on',  # 异地IP登录提醒开关

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

        # ===== 模块2/4：审计日志 与 备份 定期清理 =====
        'audit_log_keep_days': '90',
        'backup_enable_scheduled': '',       # on=开启定时自动备份
        'backup_schedule_mode': 'daily',     # daily / weekly
        'backup_schedule_time': '03:00',     # 执行时间 HH:MM
        'backup_keep_days': '30',            # 备份保留天数
        'backup_auto_clean': 'on',           # 过期自动清理

        # ===== v2.2.0：内容 API =====
        'api_enable': 'on',                  # on=启用 / off=整体 404
        'api_token': '',                     # 非空时要求请求头 X-API-Token
        'api_cache_ttl': '60',               # 接口缓存秒数（0=不缓存）
        'api_cors_origins': '',              # 跨域白名单，逗号分隔，* 全部

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

        # ===== v2.4.0：全文搜索 =====
        'search_engine': 'whoosh',             # whoosh / meilisearch / sql
        'search_meili_url': '',                # Meilisearch 服务地址
        'search_meili_key': '',                # Meilisearch API Key
        'search_index_on_save': 'on',          # on=文章保存时自动索引
        'search_results_per_page': '20',       # 每页搜索结果数
        'search_highlight': 'on',              # on=高亮匹配关键词

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
    }

    @classmethod
    def get(cls, key, default=None):
        item = cls.query.filter_by(key=key).first()
        if item is None:
            return default if default is not None else cls.DEFAULTS.get(key, '')
        return item.value or ''

    @classmethod
    def get_dict(cls):
        result = dict(cls.DEFAULTS)
        for item in cls.query.all():
            result[item.key] = item.value or ''
        return result

    @classmethod
    def set(cls, key, value):
        item = cls.query.filter_by(key=key).first()
        if item is None:
            item = cls(key=key, value=str(value) if value is not None else '')
            db.session.add(item)
        else:
            item.value = str(value) if value is not None else ''
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
