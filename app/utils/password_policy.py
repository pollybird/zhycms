"""后台管理员密码策略（v3.1.10 VULN-015，SAST #12）。

仅用于**后台管理员**设置新密码的场景（初始化向导、个人改密、用户管理
新建/重置密码）；存量密码哈希不受影响，会员端（plugins/member）维持
原有 6 位策略不变。

v3.2.4：策略改为后台「安全设置」中可配置（仅超级管理员），默认值仍为
v3.1.10 的严格策略（12 位 + 大小写 + 数字 + 特殊字符）。
"""
from flask import has_app_context
from flask_babel import gettext as _gettext

DEFAULT_MIN_LENGTH = 12
MIN_LENGTH_LOWER = 6
MIN_LENGTH_UPPER = 64

POLICY_KEYS = (
    'password_min_length',
    'password_require_upper',
    'password_require_lower',
    'password_require_digit',
    'password_require_special',
)

DEFAULT_POLICY = {
    'min_length': DEFAULT_MIN_LENGTH,
    'require_upper': True,
    'require_lower': True,
    'require_digit': True,
    'require_special': True,
}


def _truthy(raw):
    return str(raw or '').strip().lower() in ('on', '1', 'true', 'yes')


def _clamp_length(value):
    try:
        length = int(value)
    except (TypeError, ValueError):
        length = DEFAULT_MIN_LENGTH
    return max(MIN_LENGTH_LOWER, min(MIN_LENGTH_UPPER, length))


def get_password_policy():
    """读取当前密码复杂度策略；无应用上下文或读取失败时回退默认严格策略。"""
    values = {}
    if has_app_context():
        from ..models.setting import Setting
        values = {
            key: Setting.get(key, Setting.DEFAULTS.get(key, ''))
            for key in POLICY_KEYS
        }
    return {
        'min_length': _clamp_length(
            values.get('password_min_length', DEFAULT_MIN_LENGTH)),
        'require_upper': _truthy(values.get(
            'password_require_upper', DEFAULT_POLICY['require_upper'])),
        'require_lower': _truthy(values.get(
            'password_require_lower', DEFAULT_POLICY['require_lower'])),
        'require_digit': _truthy(values.get(
            'password_require_digit', DEFAULT_POLICY['require_digit'])),
        'require_special': _truthy(values.get(
            'password_require_special', DEFAULT_POLICY['require_special'])),
    }


def password_policy_hint():
    """返回当前密码策略的可读提示（表单占位/说明文案用）。"""
    policy = get_password_policy()
    labels = [label for key, label in (
        ('require_upper', _gettext('大写字母')),
        ('require_lower', _gettext('小写字母')),
        ('require_digit', _gettext('数字')),
        ('require_special', _gettext('特殊字符')),
    ) if policy[key]]
    if not labels:
        return _gettext('至少 {0} 位').format(policy['min_length'])
    return _gettext('至少 {0} 位，需包含{1}').format(
        policy['min_length'], '、'.join(labels))


def validate_password(password):
    """按当前策略校验新密码。返回 (ok, message)，message 为空串表示通过。"""
    password = password or ''
    policy = get_password_policy()

    if len(password) < policy['min_length']:
        return False, _gettext('密码长度不能少于 {0} 位').format(
            policy['min_length'])

    checks = (
        ('require_upper', _gettext('大写字母'), any(c.isupper() for c in password)),
        ('require_lower', _gettext('小写字母'), any(c.islower() for c in password)),
        ('require_digit', _gettext('数字'), any(c.isdigit() for c in password)),
        ('require_special', _gettext('特殊字符'),
         any(not c.isalnum() for c in password)),
    )
    missing = [label for key, label, passed in checks
               if policy[key] and not passed]
    if missing:
        return False, _gettext('密码需包含：{0}').format('、'.join(missing))
    return True, ''
