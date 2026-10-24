"""全局常量统一管理。

零依赖（不导入 Flask / db / 任何 app 模块），可被任意层（含脚本/模板上下文）导入。
v2.6.0 新增：收编散落在 models/utils/admin/plugins 中的硬编码常量，
消除重复定义与字面量散落。
"""


class Workflow:
    """内容发布工作流状态。"""

    STATUS_DRAFT = 'draft'          # 草稿
    STATUS_REVIEW = 'review'        # 待审核
    STATUS_PUBLISHED = 'published'  # 已发布
    STATUS_ARCHIVED = 'archived'    # 已归档

    STATUS_CHOICES = (
        (STATUS_DRAFT, '草稿'),
        (STATUS_REVIEW, '待审核'),
        (STATUS_PUBLISHED, '已发布'),
        (STATUS_ARCHIVED, '已归档'),
    )
    # 发布态集合：is_enabled=True 的状态
    PUBLISHED_STATUSES = (STATUS_PUBLISHED,)


class Upload:
    """文件上传扩展名白名单。"""

    IMAGE_EXTS = ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp')
    THEME_EXTS = ('zip', 'tar.gz', 'tgz')
    PLUGIN_EXTS = ('zip', 'tar.gz', 'tgz')
    RESUME_EXTS = ('doc', 'docx', 'xls', 'xlsx', 'pdf')
    DOCUMENT_EXTS = ('pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt')


class Locales:
    """语言区域代码。"""

    DEFAULT = 'zh'
    ZH = 'zh'
    EN = 'en'
    ALL = ('zh', 'en')


class Search:
    ENGINE_TANTIVY = 'tantivy'      # v3.1.4 起（替代 Whoosh）
    ENGINE_MEILI = 'meilisearch'
    ENGINE_SQL = 'sql'
    ENGINES = (ENGINE_TANTIVY, ENGINE_MEILI, ENGINE_SQL)
    DEFAULT_ENGINE = ENGINE_TANTIVY


class Roles:
    """预设角色 slug。"""

    SUPER_ADMIN = 'super_admin'
    CONTENT_AUDITOR = 'content_auditor'
    CONTENT_EDITOR = 'content_editor'
    READONLY_VIEWER = 'readonly_viewer'
    ALL = (SUPER_ADMIN, CONTENT_AUDITOR, CONTENT_EDITOR, READONLY_VIEWER)


class Pagination:
    """分页默认值。"""

    FRONT_PER_PAGE = 10
    ADMIN_PER_PAGE = 20
    SEARCH_PER_PAGE = 20


class Builder:
    """v3.0.0 可视化页面构建器常量。"""

    # 布局 JSON Schema 版本
    SCHEMA_VERSION = 1

    # 页面作用域
    SCOPE_HOME = 'home'        # 首页（唯一，column_id=NULL）
    SCOPE_PAGE = 'page'        # 单页栏目
    SCOPE_LIST = 'list'        # 列表栏目列表页
    SCOPE_ARTICLE = 'article'  # 列表栏目文章详情页（column_id=NULL 表示全局默认）
    SCOPES = (SCOPE_HOME, SCOPE_PAGE, SCOPE_LIST, SCOPE_ARTICLE)

    # 页面状态
    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'

    # 组件分类
    CAT_LAYOUT = 'layout'
    CAT_BASIC = 'basic'
    CAT_DATA = 'data'
    CATEGORIES = (
        (CAT_LAYOUT, '布局组件'),
        (CAT_BASIC, '基础组件'),
        (CAT_DATA, '数据组件'),
    )

    # 布局安全限制
    MAX_DEPTH = 8            # 最大嵌套深度
    MAX_NODES = 300          # 单页节点数上限
    MAX_PAYLOAD_BYTES = 256 * 1024  # 布局文档体积上限 256KB

    # 数据绑定模式
    BIND_AUTO = 'auto'       # 自动绑定当前访问栏目
    BIND_SELECT = 'select'   # 手动指定栏目

    # 预览查询参数（iframe 画布桥识别）
    PREVIEW_PARAM = 'zbw_preview'
