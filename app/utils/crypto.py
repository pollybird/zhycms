"""v3.1.8：敏感配置加解密（VULN-003，GitCode issue #12）。

使用 Fernet 对称加密（cryptography>=42.0 已在依赖中），密钥来源见
``app/config.py::_resolve_enc_key()``。Fernet token 以 ``gAAAAA`` 开头，
用作密文识别前缀，未加密的历史明文可被识别并惰性迁移。

密钥不可用时优雅降级：加密返回原文、解密返回空串，并写 warning 日志，
不阻断业务。
"""
import logging

logger = logging.getLogger(__name__)

# Fernet token 固定前缀（urlsafe base64 编码的版本字节 0x80 编码结果）
FERNET_PREFIX = 'gAAAAA'

_fernet = None
_fernet_key = None


def _resolve_key():
    """优先取当前应用配置，无应用上下文时回退到 Config 类属性。"""
    try:
        from flask import current_app, has_app_context
        if has_app_context():
            key = current_app.config.get('ZHYCMS_ENC_KEY')
            if key:
                return key
    except (ImportError, RuntimeError) as e:
        logger.warning('从应用上下文读取加密密钥失败：%s', e)
    try:
        from ..config import Config
        return getattr(Config, 'ZHYCMS_ENC_KEY', '') or ''
    except ImportError as e:
        logger.warning('从 Config 读取加密密钥失败：%s', e)
        return ''


def _get_fernet(key):
    """按密钥惰性构建并缓存 Fernet 实例（密钥变更时自动重建）。"""
    global _fernet, _fernet_key
    if not key:
        return None
    if _fernet is not None and _fernet_key == key:
        return _fernet
    try:
        from cryptography.fernet import Fernet
        instance = Fernet(key.encode('ascii') if isinstance(key, str) else key)
    except Exception as e:
        logger.warning('初始化加密组件失败：%s', e)
        return None
    _fernet = instance
    _fernet_key = key
    return instance


def encrypt_value(plain):
    """加密敏感配置明文，返回密文；密钥不可用时降级返回原文。"""
    if not plain:
        return plain
    f = _get_fernet(_resolve_key())
    if f is None:
        logger.warning('加密密钥不可用，敏感配置将以明文存储')
        return plain
    return f.encrypt(plain.encode('utf-8')).decode('ascii')


def decrypt_value(value):
    """解密敏感配置密文；非密文（无 gAAAAA 前缀）原样返回。

    密钥不可用或解密失败（如密钥已轮换）时返回空串并告警，
    避免把密文当作明文泄露给业务层。
    """
    if not value or not value.startswith(FERNET_PREFIX):
        return value
    f = _get_fernet(_resolve_key())
    if f is None:
        logger.warning('加密密钥不可用，无法解密敏感配置')
        return ''
    try:
        return f.decrypt(value.encode('ascii')).decode('utf-8')
    except Exception as e:
        logger.warning('敏感配置解密失败（密钥可能已轮换）：%s', e)
        return ''
