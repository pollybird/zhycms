"""行业主题校验测试（v2.6.3）：education / catering 必备模板完整性。"""
import pytest


@pytest.mark.themes
class TestIndustryThemes:

    @pytest.fixture
    def theme_records(self, app):
        from app.utils.themes import list_theme_records
        with app.app_context():
            return list_theme_records()

    def test_education_theme_registered(self, theme_records):
        """education 主题被系统识别且为内置主题。"""
        edu = next((r for r in theme_records if r['slug'] == 'education'), None)
        assert edu is not None, 'education 主题未被发现'
        assert edu['builtin'] is True

    def test_education_theme_complete(self, theme_records):
        """education 主题必备模板完整无缺失。"""
        edu = next((r for r in theme_records if r['slug'] == 'education'), None)
        assert edu is not None
        assert len(edu['missing_required_files']) == 0, \
            f"education 缺失必备模板: {edu['missing_required_files']}"

    def test_catering_theme_registered(self, theme_records):
        """catering 主题被系统识别且为内置主题。"""
        cat = next((r for r in theme_records if r['slug'] == 'catering'), None)
        assert cat is not None, 'catering 主题未被发现'
        assert cat['builtin'] is True

    def test_catering_theme_complete(self, theme_records):
        """catering 主题必备模板完整无缺失。"""
        cat = next((r for r in theme_records if r['slug'] == 'catering'), None)
        assert cat is not None
        assert len(cat['missing_required_files']) == 0, \
            f"catering 缺失必备模板: {cat['missing_required_files']}"

    def test_education_templates_have_html(self, theme_records):
        """education 主题包含至少基础数量的模板文件。"""
        edu = next((r for r in theme_records if r['slug'] == 'education'), None)
        assert edu is not None
        assert edu['template_count'] >= 10

    def test_catering_templates_have_html(self, theme_records):
        """catering 主题包含至少基础数量的模板文件。"""
        cat = next((r for r in theme_records if r['slug'] == 'catering'), None)
        assert cat is not None
        assert cat['template_count'] >= 10
