"""v3.1.4：pkuseg 分词封装（tokenizer.py）契约测试。

只断言 tokenize() 的输出契约（空格连接、小写、无纯标点 token），
不断言具体切词结果（随模型/版本可能变化）。
"""
import threading

import pytest

from app.utils.tokenizer import tokenize, get_segmenter


@pytest.mark.search
class TestTokenizer:

    def test_mixed_cjk_english(self):
        """中英文混排产出非空分词串。"""
        out = tokenize('企业内容管理系统v3.1.4发布')
        assert out.strip()
        assert ' ' not in out or all(t for t in out.split(' '))  # 无空 token

    def test_lowercase_latin(self):
        """ASCII 一律小写化（同时规避 tantivy 大写运算符语义）。"""
        out = tokenize('CNC加工中心 AND')
        assert out == out.lower()

    def test_punctuation_only_returns_empty(self):
        """纯标点输入返回空串（token 需含文字/字母/数字）。"""
        assert tokenize('（）。，、；：？！—…""''《》') == ''

    def test_empty_input(self):
        assert tokenize('') == ''
        assert tokenize(None) == ''

    def test_segmenter_singleton(self):
        """分词器全局单例（模型仅加载一次）。"""
        assert get_segmenter() is get_segmenter()

    def test_concurrent_tokenize(self):
        """多线程并发分词结果一致且无异常。"""
        results, errors = [], []

        def work():
            try:
                results.append(tokenize('并发分词压力测试 v3.1.4'))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert len(results) == 8
        assert all(r == results[0] for r in results)
