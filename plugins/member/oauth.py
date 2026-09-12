"""第三方一键登录：微信开放平台（网站应用扫码）与 QQ 互联。

仅负责标准 OAuth2 授权码换取用户身份；账号绑定/自动建号逻辑在路由层。
"""
import urllib.parse

import requests

from . import settings as cfg

PROVIDERS = ('wechat', 'qq')


def is_enabled(provider):
    if provider == 'wechat':
        return cfg.is_on('member_wechat_enable') and bool(
            cfg.cfg('member_wechat_appid') and cfg.cfg('member_wechat_secret'))
    if provider == 'qq':
        return cfg.is_on('member_qq_enable') and bool(
            cfg.cfg('member_qq_appid') and cfg.cfg('member_qq_secret'))
    return False


def authorize_url(provider, redirect_uri, state):
    """拼接第三方授权页地址。"""
    if provider == 'wechat':
        params = {
            'appid': cfg.cfg('member_wechat_appid'),
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': 'snsapi_login',
            'state': state,
        }
        return ('https://open.weixin.qq.com/connect/qrconnect?'
                + urllib.parse.urlencode(params) + '#wechat_redirect')
    if provider == 'qq':
        params = {
            'client_id': cfg.cfg('member_qq_appid'),
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'state': state,
        }
        return ('https://graph.qq.com/oauth2.0/authorize?'
                + urllib.parse.urlencode(params))
    raise ValueError(f'不支持的登录渠道：{provider}')


def fetch_profile(provider, code, redirect_uri):
    """授权码换取用户资料。

    返回 {'openid','unionid','nickname','avatar'}；失败抛 RuntimeError。
    """
    if provider == 'wechat':
        return _fetch_wechat(code)
    if provider == 'qq':
        return _fetch_qq(code, redirect_uri)
    raise ValueError(f'不支持的登录渠道：{provider}')


# ---------------- 微信开放平台 ----------------

def _fetch_wechat(code):
    appid = cfg.cfg('member_wechat_appid')
    secret = cfg.cfg('member_wechat_secret')
    resp = requests.get('https://api.weixin.qq.com/sns/oauth2/access_token', params={
        'appid': appid, 'secret': secret,
        'code': code, 'grant_type': 'authorization_code',
    }, timeout=10)
    data = resp.json()
    if 'access_token' not in data:
        raise RuntimeError('微信 access_token 获取失败：%s' % data.get('errmsg', data.get('errcode')))
    access_token = data['access_token']
    openid = data['openid']

    info = requests.get('https://api.weixin.qq.com/sns/userinfo', params={
        'access_token': access_token, 'openid': openid,
    }, timeout=10).json()
    if 'openid' not in info:
        raise RuntimeError('微信用户资料获取失败：%s' % info.get('errmsg', info.get('errcode')))
    return {
        'openid': info['openid'],
        'unionid': info.get('unionid') or data.get('unionid') or '',
        'nickname': info.get('nickname') or '',
        'avatar': info.get('headimgurl') or '',
    }


# ---------------- QQ 互联 ----------------

def _fetch_qq(code, redirect_uri):
    appid = cfg.cfg('member_qq_appid')
    secret = cfg.cfg('member_qq_secret')
    # fmt=json 使 QQ 返回标准 JSON，避免解析 callback(...) 包裹
    token_resp = requests.get('https://graph.qq.com/oauth2.0/token', params={
        'grant_type': 'authorization_code',
        'client_id': appid, 'client_secret': secret,
        'code': code, 'redirect_uri': redirect_uri, 'fmt': 'json',
    }, timeout=10).json()
    access_token = token_resp.get('access_token')
    if not access_token:
        raise RuntimeError('QQ access_token 获取失败：%s' % token_resp.get('error_description')
                           or token_resp.get('error'))

    me = requests.get('https://graph.qq.com/oauth2.0/me', params={
        'access_token': access_token, 'fmt': 'json',
    }, timeout=10).json()
    openid = me.get('openid')
    if not openid:
        raise RuntimeError('QQ openid 获取失败')

    info = requests.get('https://graph.qq.com/user/get_user_info', params={
        'oauth_consumer_key': appid,
        'access_token': access_token, 'openid': openid,
    }, timeout=10).json()
    if info.get('ret') != 0:
        raise RuntimeError('QQ 用户资料获取失败：%s' % info.get('msg'))
    return {
        'openid': openid,
        'unionid': '',
        'nickname': info.get('nickname') or '',
        'avatar': info.get('figureurl_qq_1') or info.get('figureurl_qq_2') or '',
    }
