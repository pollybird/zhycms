"""业务逻辑层（service 层）。

将视图层（routes）中的业务逻辑抽离到此处，使路由只负责 HTTP 协议转换
（解析请求、调用 service、渲染模板/重定向），业务逻辑可独立测试。

命名约定：
  - 函数名与原路由内 helper 对应，如 article_service.save_article()
  - 不依赖 flask.request / flask_login.current_user 等全局对象，
    所需数据通过参数显式传入
  - 返回 (result, messages)，messages 为 [(category, message), ...]，
    由调用方负责 flash
"""
