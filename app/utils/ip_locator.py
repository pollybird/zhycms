"""IP 归属地查询（用于异地登录提醒）。

优先使用 http://ip-api.com/json/ 免费接口（有请求频率限制）；
失败时回退本地判断：仅对比 IP 网段与上次登录 IP 前两段是否一致，不一致则视为「异地」。
"""
import requests as _requests

_cache = {}  # ip -> city / None


def locate_city(ip, timeout=3):
    """返回城市/地区字符串；失败或内网 IP 返回空字符串。"""
    if not ip:
        return ''
    if ip.startswith('127.') or ip.startswith('192.168.') or ip.startswith('10.') or ip.startswith('172.'):
        return '内网'
    if ip in _cache:
        return _cache[ip] or ''
    try:
        r = _requests.get(f'http://ip-api.com/json/{ip}?lang=zh-CN&fields=status,regionName,city,isp',
                          timeout=timeout)
        j = r.json()
        if j.get('status') == 'success':
            city = (j.get('regionName', '') or '') + (j.get('city', '') or '')
            _cache[ip] = city or '未知'
            return city or ''
    except Exception:
        pass
    _cache[ip] = ''
    return ''


def is_abnormal_login(current_ip, last_ip):
    """粗略判断是否异地登录（前两段 IP 不同即视为异地，提醒用）。"""
    if not current_ip or not last_ip:
        return False
    try:
        c = current_ip.split('.')[:2]
        p = last_ip.split('.')[:2]
        return c != p
    except Exception:
        return False
