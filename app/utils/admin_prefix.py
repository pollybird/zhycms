"""后台路由前缀配置工具。

后台默认挂载在 ``/admin`` 前缀下。固定且众所周知的后台地址容易被扫描器
猜测并针对登录页发起暴力破解，因此允许管理员将前缀改为任意自定义值以增强安全性。

- 前缀以 ``instance/admin_config.json`` 落盘（chmod 600），与数据库配置
  ``db_config.json`` 采用同一套落盘/容错模式（见 ``app/utils/dbconfig.py``）。
- v2.0 起运行中修改前缀即时生效（无需重启）：``_register_dynamic_admin_rules``
  直接重建 ``url_map`` 中的路由规则，旧前缀立即失效。
- 应用启动时 ``app/__init__.py`` 在注册后台蓝本前调用 ``get_admin_url_prefix()``。
"""
import json
import os
import re

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
CONFIG_PATH = os.path.join(BASE_DIR, 'instance', 'admin_config.json')

# 默认前缀，保持与历史部署一致
DEFAULT_PREFIX = 'admin'

# 前台已占用的顶层路径，后台前缀不得与之冲突（见 app/frontend/views.py 与静态目录）
RESERVED = {'column', 'article', 'form', 'captcha', 'search', 'static', 'uploads'}

# 允许的前缀格式：字母/数字/连字符/下划线，长度 2-32
_PREFIX_RE = re.compile(r'^[a-zA-Z0-9_-]{2,32}$')


def load_admin_prefix():
    """读取已保存的后台前缀（不含斜杠）；文件缺失或损坏时回退默认值。

    需静默容错，保证任何情况下应用都能正常启动。
    """
    if not os.path.exists(CONFIG_PATH):
        return DEFAULT_PREFIX
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (ValueError, OSError):
        return DEFAULT_PREFIX
    prefix = (data.get('prefix') or '').strip().strip('/')
    return prefix or DEFAULT_PREFIX


def get_admin_url_prefix():
    """返回带前导斜杠的后台 URL 前缀，供 register_blueprint 使用，如 ``/admin``。"""
    return '/' + load_admin_prefix()


def validate_prefix(raw):
    """规范化并校验前缀，返回 ``(ok: bool, normalized_or_msg: str)``。

    - 规范化：去首尾空白与斜杠、转小写；
    - 仅允许字母/数字/连字符/下划线，长度 2-32；
    - 不得与前台保留路径冲突。
    """
    prefix = (raw or '').strip().strip('/').lower()
    if not prefix:
        return False, '后台路由不能为空'
    if not _PREFIX_RE.match(prefix):
        return False, '后台路由只能包含字母、数字、连字符(-)、下划线(_)，长度 2-32 位'
    if prefix in RESERVED:
        return False, f'“{prefix}”与前台路径冲突，请换一个'
    return True, prefix


def save_admin_prefix(prefix):
    """将后台前缀落盘为 ``admin_config.json``，权限收敛为 600。"""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump({'prefix': prefix}, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        # Windows 等平台可能不支持 chmod，忽略即可
        pass
