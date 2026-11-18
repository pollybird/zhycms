"""日志增强：给每条日志附加当前站点标签。

多站点共用同一进程时，仅凭 logger 名称无法判断日志来自哪个站点。
请求内使用 `g.current_site_id`（由 select_site 写入）；无请求上下文
（CLI、迁移、定时任务）统一输出 `-`。
"""
import logging

DEFAULT_LOG_FORMAT = (
    '%(asctime)s %(levelname)s [site=%(site_id)s] %(name)s: %(message)s'
)

_FILTER_FLAG = '_zhycms_site_filter'
_LOG_FORMAT_FLAG = '_zhycms_site_log_format'

logger = logging.getLogger(__name__)


class SiteContextFilter(logging.Filter):
    """为 LogRecord 补充 site_id 属性；异常时降级为 `-`。"""

    def filter(self, record):
        try:
            from flask import g, has_app_context, has_request_context
            if has_app_context() and has_request_context():
                site_id = getattr(g, 'current_site_id', None)
                record.site_id = site_id if site_id is not None else '-'
            else:
                record.site_id = '-'
        except Exception as e:
            logger.debug('日志站点标签解析失败，按无站点处理：%s', e)
            record.site_id = '-'
        return True


def install_logging(app):
    """把站点过滤器与格式挂到现有 handler；重复调用保持幂等。"""
    fmt = app.config.get('LOG_FORMAT') or DEFAULT_LOG_FORMAT
    formatter = logging.Formatter(fmt)

    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())

    # app.logger 自己持有 handler，关闭向 root 传播，避免同一条日志输出两次
    app.logger.propagate = False

    handlers = list(root.handlers) + list(app.logger.handlers)
    for handler in handlers:
        if not getattr(handler, _FILTER_FLAG, False):
            handler.addFilter(SiteContextFilter())
            setattr(handler, _FILTER_FLAG, True)
        if not getattr(handler, _LOG_FORMAT_FLAG, False):
            handler.setFormatter(formatter)
            setattr(handler, _LOG_FORMAT_FLAG, True)
