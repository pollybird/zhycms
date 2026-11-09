"""后台管理员密码策略（v3.1.10 VULN-015，SAST #12）。

仅用于**后台管理员**设置新密码的场景（初始化向导、个人改密、用户管理
新建/重置密码）；存量密码哈希不受影响，会员端（plugins/member）维持
原有 6 位策略不变。
"""
from flask_babel import gettext as _gettext

MIN_LENGTH = 12


def validate_password(password):
    """校验新密码。返回 (ok, message)，message 为空串表示通过。"""
    if len(password or '') < MIN_LENGTH:
        return False, _gettext('密码长度不能少于 {0} 位').format(MIN_LENGTH)
    classes = [
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ]
    if sum(classes) < 4:
        return False, _gettext('密码需同时包含大写字母、小写字母、数字和特殊字符')
    return True, ''
