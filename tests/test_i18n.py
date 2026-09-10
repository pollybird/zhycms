"""国际化测试：locale 选择、t_field 回退、po→mo 自编译。"""
import pytest


@pytest.mark.i18n
class TestI18N:

    def test_select_locale_default(self, app):
        """默认 locale 为 zh。"""
        from app.i18n import select_locale
        with app.test_request_context('/'):
            assert select_locale() == 'zh'

    def test_select_locale_via_query(self, app):
        """?lang=en 切换 locale（需开启 i18n + 可用语种含 en）。"""
        from app.i18n import select_locale
        from app.models.setting import Setting
        from app.extensions import db
        with app.app_context():
            Setting.set('i18n_enable', '1')
            Setting.set('i18n_default_locale', 'zh')
            Setting.set('i18n_available_locales', 'zh,en')
            db.session.commit()
        with app.test_request_context('/?lang=en'):
            loc = select_locale()
            assert loc == 'en'

    def test_mo_auto_compile(self, app):
        """启动后 .mo 文件存在（自动编译）。"""
        import os
        from app.i18n import ensure_translations_compiled
        ensure_translations_compiled()
        mo_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'app', 'translations', 'en', 'LC_MESSAGES', 'messages.mo'
        )
        assert os.path.isfile(mo_path)

    def test_t_field_fallback(self, app):
        """无翻译时 t_field 回退主表默认语言。"""
        from app.extensions import db
        from app.utils.i18n_content import t_field
        from app.models.column import Column

        with app.app_context():
            col = Column(name='中文名', slug='t-col-fb', type='list',
                         is_enabled=True, is_deleted=False)
            db.session.add(col)
            db.session.commit()

            result = t_field(col, 'name', 'en')
            assert result == '中文名'
