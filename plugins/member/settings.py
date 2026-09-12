"""前台会员插件配置（存储于核心 Setting 键值表，统一 member_ 前缀）。"""
from app.models.setting import Setting

# 全部配置项及默认值（后台「会员设置」页按此清单渲染与保存）
DEFAULTS = {
    # 基础
    'member_register_enable': 'on',       # 是否开放注册
    'member_agreement': '',               # 注册协议（富文本 HTML）
    'member_login_sms_enable': 'on',      # 短信验证码登录开关
    'member_auto_register_sms': 'on',     # 短信登录时手机号未注册则自动建号
    'member_oauth_auto_register': 'on',   # 第三方登录未绑定时自动建号

    # 短信通道：log=开发模式（验证码写日志）/ aliyun=阿里云短信 / webhook=通用HTTP接口
    'member_sms_provider': 'log',
    'member_sms_aliyun_key_id': '',
    'member_sms_aliyun_key_secret': '',
    'member_sms_aliyun_sign': '',
    'member_sms_aliyun_template': '',
    'member_sms_webhook_url': '',         # 支持占位符 {phone} {code}
    'member_sms_webhook_method': 'GET',   # GET / POST
    'member_sms_code_ttl': '300',         # 验证码有效期（秒）
    'member_sms_send_interval': '60',     # 同手机号发送间隔（秒）
    'member_sms_daily_limit': '10',       # 同手机号每日发送上限

    # 微信开放平台（网站应用扫码登录）
    'member_wechat_enable': '',
    'member_wechat_appid': '',
    'member_wechat_secret': '',

    # QQ 互联
    'member_qq_enable': '',
    'member_qq_appid': '',
    'member_qq_secret': '',
}

# 后台表单字段名 → 说明（分组顺序即页面展示顺序）
FIELD_GROUPS = [
    ('basic', '基础设置'),
    ('sms', '短信设置'),
    ('wechat', '微信登录'),
    ('qq', 'QQ 登录'),
]

# 每组允许保存的键（防越权写入其他 Setting）
GROUP_KEYS = {
    'basic': [
        'member_register_enable', 'member_agreement',
        'member_login_sms_enable', 'member_auto_register_sms',
        'member_oauth_auto_register',
    ],
    'sms': [
        'member_sms_provider', 'member_sms_aliyun_key_id',
        'member_sms_aliyun_key_secret', 'member_sms_aliyun_sign',
        'member_sms_aliyun_template', 'member_sms_webhook_url',
        'member_sms_webhook_method', 'member_sms_code_ttl',
        'member_sms_send_interval', 'member_sms_daily_limit',
    ],
    'wechat': ['member_wechat_enable', 'member_wechat_appid', 'member_wechat_secret'],
    'qq': ['member_qq_enable', 'member_qq_appid', 'member_qq_secret'],
}

# 复选框类键（未勾选时需显式写空串）
CHECKBOX_KEYS = {
    'member_register_enable', 'member_login_sms_enable', 'member_auto_register_sms',
    'member_oauth_auto_register', 'member_wechat_enable', 'member_qq_enable',
}


_MISSING = object()


def cfg(key):
    """读取单个配置（无记录时回退插件默认值）。

    注意核心 Setting.get 对未知键返回 ''，无法区分「无记录」与「显式置空」，
    故传入哨兵 default：行不存在才使用本插件 DEFAULTS；保存为空串（如关闭
    开关）时行已存在，应如实返回 ''。
    """
    val = Setting.get(key, default=_MISSING)
    if val is _MISSING:
        return DEFAULTS.get(key, '')
    return val


def is_on(key):
    return cfg(key) == 'on'


def save_group(group, form_data):
    """按分组保存表单中允许的键。返回实际写入的键列表。"""
    keys = GROUP_KEYS.get(group, [])
    for key in keys:
        if key in CHECKBOX_KEYS:
            value = 'on' if form_data.get(key) == 'on' else ''
        else:
            value = (form_data.get(key) or '').strip()
        Setting.set(key, value)
    return keys
