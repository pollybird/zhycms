"""v3.1.5 后台 Markdown 编辑模式集成测试。

覆盖：文章/栏目/碎片三处保存链路的双写契约、编辑页模式判定、
「编辑设置」页读写与非法值回退、版本回滚强制 html。
"""
import pytest

from tests.factories import make_column, make_article


@pytest.mark.usefixtures('admin_client')
class TestArticleMarkdown:

    def _create(self, admin_client, cid, **data):
        base = {'title': 'Markdown 文章', 'status': 'draft',
                'content': '', 'summary': ''}
        base.update(data)
        return admin_client.post(
            f'/admin/columns/{cid}/articles/create', data=base,
            follow_redirects=True)

    def test_create_markdown_mode(self, app, admin_client):
        """markdown 模式：content 存渲染后 HTML，content_md 存原文。"""
        from app.extensions import db
        from app.models.article import Article
        with app.app_context():
            col = make_column(name='MD栏目', slug='md-col')
            db.session.commit()
            cid = col.id

        resp = self._create(admin_client, cid,
                            content_format='markdown',
                            content_md='# 大标题\n\n正文**加粗**')
        assert resp.status_code == 200
        with app.app_context():
            art = Article.query.filter_by(column_id=cid).first()
            assert art is not None
            assert '<h1>' in art.content and '<strong>' in art.content
            assert art.content_md == '# 大标题\n\n正文**加粗**'
            assert art.content_format == 'markdown'

    def test_create_html_mode_default(self, app, admin_client):
        """无 format 字段（老客户端）：content 原样写入，format 落为 html。"""
        from app.extensions import db
        from app.models.article import Article
        with app.app_context():
            col = make_column(name='HTML栏目', slug='html-col')
            db.session.commit()
            cid = col.id

        resp = self._create(admin_client, cid, content='<p>富文本</p>')
        assert resp.status_code == 200
        with app.app_context():
            art = Article.query.filter_by(column_id=cid).first()
            assert art.content == '<p>富文本</p>'
            assert art.content_format == 'html'
            assert not art.content_md

    def test_create_invalid_format_falls_back_html(self, app, admin_client):
        """非法 format 值不报错，回退 html 语义。"""
        from app.extensions import db
        from app.models.article import Article
        with app.app_context():
            col = make_column(name='非法栏目', slug='bad-fmt-col')
            db.session.commit()
            cid = col.id

        resp = self._create(admin_client, cid, content='<p>x</p>',
                            content_format='weird', content_md='# 不应生效')
        assert resp.status_code == 200
        with app.app_context():
            art = Article.query.filter_by(column_id=cid).first()
            assert art.content == '<p>x</p>'
            assert art.content_format == 'html'

    def test_edit_page_opens_markdown_for_md_article(self, app, admin_client):
        """编辑页模式判定：记录自身 format=markdown → 初始 Markdown 模式。"""
        from app.extensions import db
        from app.models.article import Article
        with app.app_context():
            col = make_column(name='模式栏目', slug='mode-col')
            art = make_article(title='MD文', column_id=col.id, content='<h1>题</h1>')
            art.content_format = 'markdown'
            art.content_md = '# 题'
            db.session.commit()
            cid, aid = col.id, art.id

        resp = admin_client.get(f'/admin/columns/{cid}/articles/{aid}/edit')
        assert resp.status_code == 200
        assert b'data-mode="markdown"' in resp.data
        assert b'name="content_md"' in resp.data

    def test_edit_page_default_ckeditor_for_html_article(self, app, admin_client):
        """老数据 format=html → 永远 CKEditor 打开（升级无感）。"""
        from app.extensions import db
        with app.app_context():
            col = make_column(name='旧栏目', slug='old-col')
            art = make_article(title='旧文', column_id=col.id, content='<p>旧</p>')
            db.session.commit()
            cid, aid = col.id, art.id

        resp = admin_client.get(f'/admin/columns/{cid}/articles/{aid}/edit')
        assert resp.status_code == 200
        assert b'data-mode="ckeditor"' in resp.data

    def test_rollback_forces_html_format(self, app, admin_client):
        """版本回滚：强制 format=html 并清空 Markdown 原文。"""
        from app.extensions import db
        from app.models.article import Article
        from app.models.workflow import ArticleVersion
        with app.app_context():
            col = make_column(name='回滚栏目', slug='rb-col')
            db.session.commit()
            cid = col.id

        self._create(admin_client, cid, content_format='markdown',
                     content_md='# 版本一')
        with app.app_context():
            art = Article.query.filter_by(column_id=cid).first()
            aid = art.id
            ver = ArticleVersion.query.filter_by(article_id=aid)\
                .order_by(ArticleVersion.version_no.asc()).first()
            assert ver is not None
            vid = ver.id

        resp = admin_client.post(
            f'/admin/columns/{cid}/articles/{aid}/versions/{vid}/rollback',
            follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            art = Article.query.get(aid)
            assert art.content_format == 'html'
            assert not art.content_md


@pytest.mark.usefixtures('admin_client')
class TestColumnFragmentMarkdown:

    def test_column_page_content_markdown(self, app, admin_client):
        """单页栏目 page_content 支持 markdown 双写。"""
        from app.extensions import db
        from app.models.column import Column
        resp = admin_client.post('/admin/columns/create', data={
            'name': 'MD单页', 'slug': 'md-page', 'type': 'page',
            'page_content': '', 'page_content_md': '# 单页标题',
            'page_content_format': 'markdown',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            col = Column.query.filter_by(slug='md-page').first()
            assert col is not None
            assert '<h1>' in col.page_content
            assert col.page_content_md == '# 单页标题'
            assert col.page_content_format == 'markdown'

    def test_fragment_richtext_markdown(self, app, admin_client):
        """富文本碎片 value 支持 markdown 双写。"""
        from app.extensions import db
        from app.models.fragment import Fragment
        resp = admin_client.post('/admin/fragments/create', data={
            'name': 'MD碎片', 'slug': 'md-frag', 'field_type': 'richtext',
            'value': '', 'value_md': '碎片**重点**', 'value_format': 'markdown',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            frag = Fragment.query.filter_by(slug='md-frag').first()
            assert frag is not None
            assert '<strong>' in frag.value
            assert frag.value_md == '碎片**重点**'
            assert frag.value_format == 'markdown'

    def test_fragment_edit_page_markdown_mode(self, app, admin_client):
        """format=markdown 的碎片打开编辑页时为 Markdown 模式。"""
        from app.extensions import db
        from app.models.fragment import Fragment
        with app.app_context():
            frag = Fragment(name='富文本碎片', slug='rt-frag', field_type='richtext',
                            value='<p>x</p>', value_md='# x', value_format='markdown',
                            is_enabled=True, is_deleted=False)
            db.session.add(frag)
            db.session.commit()
            fid = frag.id
        resp = admin_client.get(f'/admin/fragments/{fid}/edit')
        assert resp.status_code == 200
        assert b'data-mode="markdown"' in resp.data


@pytest.mark.usefixtures('admin_client')
class TestEditorSetting:

    def test_editor_setting_page(self, app, admin_client):
        resp = admin_client.get('/admin/settings/editor')
        assert resp.status_code == 200
        assert 'editor_default_mode'.encode() in resp.data

    def test_set_default_mode_markdown(self, app, admin_client):
        from app.models.setting import Setting
        resp = admin_client.post('/admin/settings/editor',
                                 data={'editor_default_mode': 'markdown'},
                                 follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            assert Setting.get_editor_default_mode() == 'markdown'
        # 恢复默认，避免污染其他用例
        admin_client.post('/admin/settings/editor',
                          data={'editor_default_mode': 'ckeditor'},
                          follow_redirects=True)

    def test_invalid_mode_falls_back_ckeditor(self, app, admin_client):
        from app.models.setting import Setting
        resp = admin_client.post('/admin/settings/editor',
                                 data={'editor_default_mode': 'not-a-mode'},
                                 follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            assert Setting.get_editor_default_mode() == 'ckeditor'
