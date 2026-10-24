"""v3.1.4：pkuseg 中文分词封装（spacy-pkuseg 发行包）。

- 全局单例懒加载（双检锁）；首次 cut 时加载模型（约几十 MB 内存）
- tokenize() 输出"空格连接串"，配合 Tantivy 默认分词器做索引与查询：
  中文按 pkuseg 切词；英文/数字保留并小写化；标点丢弃。
  小写化同时规避 Tantivy 查询语法中的大写 AND/OR/NOT 运算符。
- 发行包：spacy-pkuseg（pkuseg 活跃维护 fork，导入名 spacy_pkuseg）；
  兼容原版 pkuseg 导入名，二者 API 一致。
- 部署注意：默认模型首次初始化时自动下载至 ~/.pkuseg/（已存在则跳过）；
  离线环境可预置该目录，Docker 镜像构建期预热（见 Dockerfile）。
"""
import re
import threading

_seg = None
_seg_lock = threading.Lock()

# 至少含一个文字/字母/数字的 token 才保留（纯标点丢弃）
_WORD_RE = re.compile(r'[\w一-鿿]', re.UNICODE)


def get_segmenter():
    """返回 pkuseg 分词器单例（首次调用时初始化并加载模型）。"""
    global _seg
    if _seg is None:
        with _seg_lock:
            if _seg is None:
                try:
                    import spacy_pkuseg as _mod
                except ImportError:
                    import pkuseg as _mod
                _seg = _mod.pkuseg()
    return _seg


def tokenize(text):
    """中英文混排文本 → 空格连接的分词串（供 Tantivy 索引/查询）。

    空输入返回空串；token 仅保留含文字/字母/数字的片段；ASCII 小写化。
    """
    if not text:
        return ''
    tokens = []
    for tok in get_segmenter().cut(text):
        tok = tok.strip()
        if tok and _WORD_RE.search(tok):
            tokens.append(tok.lower())
    return ' '.join(tokens)
