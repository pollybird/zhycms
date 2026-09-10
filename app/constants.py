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
    """搜索引擎名称。"""

    ENGINE_WHOOSH = 'whoosh'
    ENGINE_MEILI = 'meilisearch'
    ENGINE_SQL = 'sql'
    ENGINES = (ENGINE_WHOOSH, ENGINE_MEILI, ENGINE_SQL)
    DEFAULT_ENGINE = ENGINE_WHOOSH


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
