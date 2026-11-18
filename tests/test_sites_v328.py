"""v3.2.8 站群运维平台化回归测试。

覆盖：
  - 证书到期判定、巡检去重与批量隔离
  - 站点克隆（栏目树/字段/文章/碎片/构建器/插件/失败清理/异步任务）
  - 站点级 ZIP 备份导出、校验、三种导入模式与保留清理
  - 站点回收站、批量操作与批量站点角色
  - 后台页面权限与关键路由
"""
import os
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db

pytestmark = pytest.mark.sites


# ============================================================
# 辅助
# ============================================================

def _uniq(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


def _mk_site(app, *, slug=None, domain=None, is_default=False, status='open'):
    from app.models.site import Site
    with app.app_context():
        site = Site(name=f'站点-{slug}', slug=slug, domain=domain,
                    status=status, is_default=is_default)
        db.session.add(site)
        db.session.commit()
        return site.id


def _mk_super(app, username=None):
    from app.models.user import User
    with app.app_context():
        user = User(username=username or _uniq('v328-super'),
                    is_super=True, is_deleted=False)
        user.set_password('Abcdef123456!')
        db.session.add(user)
        db.session.commit()
        return user.id


def _mk_user(app, username=None):
    from app.models.user import User
    with app.app_context():
        user = User(username=username or _uniq('v328-user'),
                    is_deleted=False)
        user.set_password('Abcdef123456!')
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, uid):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True


def _seed_source(app):
    """创建含栏目树、文章、字段、碎片、构建器与插件内容的源站点。"""
    from app.models.article import Article, ArticleFieldValue, ArticleTranslation
    from app.models.builder import BuilderPage, BuilderRevision
    from app.models.column import (
        Column, ColumnField, ColumnFieldValue, ColumnTranslation,
    )
    from app.models.fragment import Fragment, FragmentGroup, FragmentTranslation
    from app.models.workflow import ArticleVersion
    from plugins.form.models import (
        Form, FormField, FormSubmission, FormTranslation,
    )
    from plugins.product.models import Product, ProductTranslation

    with app.app_context():
        site_id = _mk_site(app, slug=_uniq('v328-src'))
        parent = Column(site_id=site_id, name='父栏目',
                        slug=_uniq('col'), type='list')
        db.session.add(parent)
        db.session.flush()
        child = Column(site_id=site_id, name='子栏目', parent_id=parent.id,
                       slug=_uniq('col'), type='list')
        db.session.add(child)
        db.session.flush()

        field_parent = ColumnField(column_id=parent.id, label='父字段',
                                   field_key='pkey', field_type='text')
        field_child = ColumnField(column_id=child.id, label='子字段',
                                  field_key='ckey', field_type='text')
        db.session.add_all([field_parent, field_child])
        db.session.flush()
        db.session.add_all([
            ColumnFieldValue(column_id=parent.id, field_id=field_parent.id,
                             value='pv'),
            ColumnTranslation(column_id=parent.id, locale='en', name='Parent'),
        ])
        db.session.flush()

        articles = []
        for i in range(10):
            article = Article(site_id=site_id, column_id=child.id,
                              title=f'文章 {i}', summary='摘要')
            db.session.add(article)
            db.session.flush()
            db.session.add_all([
                ArticleFieldValue(article_id=article.id,
                                  field_id=field_child.id, value=f'v{i}'),
                ArticleTranslation(article_id=article.id, locale='en',
                                   title=f'Article {i}'),
            ])
            if i == 0:
                db.session.add(ArticleVersion(
                    article_id=article.id, version_no=1,
                    title=article.title))
            articles.append(article.id)

        group = FragmentGroup(name='共享分组')
        db.session.add(group)
        db.session.flush()
        fragment = Fragment(site_id=site_id, group_id=group.id, name='页脚',
                            slug=_uniq('frag'), field_type='text', value='v')
        db.session.add(fragment)
        db.session.flush()
        db.session.add(FragmentTranslation(
            fragment_id=fragment.id, locale='en', name='Footer'))

        page = BuilderPage(site_id=site_id, scope='column', column_id=child.id,
                           name='首页布局', status='published',
                           draft_json='{}', published_json='{}')
        db.session.add(page)
        db.session.flush()
        db.session.add(BuilderRevision(
            page_id=page.id, data_json='{"blocks":[]}', note='init'))
        db.session.flush()

        form = Form(site_id=site_id, name='联系表单', slug=_uniq('form'))
        db.session.add(form)
        db.session.flush()
        db.session.add(FormField(form_id=form.id, label='姓名',
                                 field_key='name', field_type='text'))
        db.session.add(FormTranslation(form_id=form.id, locale='en',
                                       name='Contact'))
        db.session.add(FormSubmission(form_id=form.id, ip='127.0.0.1'))

        product = Product(site_id=site_id, column_id=child.id, title='产品一')
        db.session.add(product)
        db.session.flush()
        db.session.add(ProductTranslation(
            product_id=product.id, locale='en', title='Product'))

        db.session.commit()
        return {
            'site_id': site_id, 'parent': parent.id, 'child': child.id,
            'group': group.id, 'fragment': fragment.id, 'page': page.id,
            'form': form.id, 'product': product.id,
            'field_parent': field_parent.id, 'field_child': field_child.id,
            'article': articles[0],
        }


def _write_cert(root, host, days):
    """生成自签名证书，days 为相对当前时间的天数（负数为过期）。"""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    directory = os.path.join(root, host)
    os.makedirs(directory, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=days))
            .sign(key, hashes.SHA256()))
    with open(os.path.join(directory, 'cert.pem'), 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


@pytest.fixture
def dirs(app, tmp_path):
    """隔离上传、备份与证书目录。"""
    keys = ('UPLOAD_FOLDER', 'BACKUP_FOLDER', 'SSL_CERT_ROOT')
    old = {k: app.config.get(k) for k in keys}
    uploads = tmp_path / 'uploads'
    backups = tmp_path / 'backups'
    certs = tmp_path / 'certs'
    uploads.mkdir()
    backups.mkdir()
    certs.mkdir()
    app.config['UPLOAD_FOLDER'] = str(uploads)
    app.config['BACKUP_FOLDER'] = str(backups)
    app.config['SSL_CERT_ROOT'] = str(certs)
    yield {'uploads': uploads, 'backups': backups, 'certs': certs,
           'root': tmp_path}
    for key, value in old.items():
        if value is None:
            app.config.pop(key, None)
        else:
            app.config[key] = value


@pytest.fixture(autouse=True)
def _clean_v328(app):
    yield
    from app.models.article import Article, ArticleFieldValue, ArticleTranslation
    from app.models.audit import AuditLog
    from app.models.builder import BuilderPage, BuilderRevision
    from app.models.column import (
        Column, ColumnField, ColumnFieldValue, ColumnTranslation,
    )
    from app.models.fragment import Fragment, FragmentTranslation
    from app.models.rbac import UserRole
    from app.models.setting import Setting
    from app.models.site import Site
    from app.models.site_job import SiteJob
    from app.models.site_recycle import SiteRecycleBin
    from app.models.upload import UploadedFile
    from app.models.user import User
    from app.services.site_clone import delete_all_site_content

    with app.app_context():
        site_ids = [s.id for s in Site.query.filter(
            Site.slug.like('v328-%')).all()]
        user_ids = [u.id for u in User.query.filter(
            User.username.like('v328-%')).all()]
        if site_ids:
            for sid in site_ids:
                try:
                    delete_all_site_content(sid)
                except Exception:
                    db.session.rollback()
            for model in (ArticleFieldValue, ArticleTranslation,
                          Article, ColumnFieldValue, ColumnTranslation,
                          ColumnField, Column, FragmentTranslation, Fragment,
                          BuilderRevision, BuilderPage, UploadedFile):
                column = getattr(model, 'site_id', None)
                if column is not None:
                    model.query.filter(column.in_(site_ids)).delete(
                        synchronize_session=False)
            SiteRecycleBin.query.filter(
                SiteRecycleBin.site_id.in_(site_ids)).delete(
                synchronize_session=False)
            AuditLog.query.filter(AuditLog.site_id.in_(site_ids)).delete(
                synchronize_session=False)
            Setting.query.filter(Setting.site_id.in_(site_ids)).delete(
                synchronize_session=False)
        job_query = SiteJob.query
        if user_ids:
            job_query = job_query.filter(SiteJob.created_by.in_(user_ids))
        job_query.delete(synchronize_session=False)
        Site.query.filter(Site.slug.like('v328-%')).delete(
            synchronize_session=False)
        if user_ids:
            UserRole.query.filter(UserRole.user_id.in_(user_ids)).delete(
                synchronize_session=False)
            User.query.filter(User.id.in_(user_ids)).delete(
                synchronize_session=False)
        Setting.query.filter(Setting.key.in_((
            'ssl_expiry_warn_days', 'ssl_expiry_notify_enable',
            'ssl_expiry_notify_channels', 'site_backup_keep_days',
            'site_backup_max_unzip_mb'))).delete(synchronize_session=False)
        db.session.commit()


# ============================================================
# 一、证书检查
# ============================================================

def test_warn_days_default_and_clamp(app):
    from app.models.setting import Setting
    from app.services.site_ssl import get_warn_days

    with app.app_context():
        assert get_warn_days() == 10
        Setting.set('ssl_expiry_warn_days', '0')
        assert get_warn_days() == 1
        Setting.set('ssl_expiry_warn_days', '999')
        assert get_warn_days() == 90
        Setting.set('ssl_expiry_warn_days', 'abc')
        assert get_warn_days() == 10


@pytest.mark.parametrize('days,expected', [
    (20, 'ok'), (9, 'expiring'), (-1, 'expired'),
])
def test_certificate_status(app, dirs, days, expected):
    from app.models.site import Site
    from app.services.site_ssl import check_site_certificate

    host = f'{_uniq("cert")}.example.com'
    sid = _mk_site(app, slug=_uniq('v328-cert'), domain=host)
    _write_cert(str(dirs['certs']), host, days)
    with app.app_context():
        result = check_site_certificate(db.session.get(Site, sid),
                                        base_domain='', warn_days=10)
    assert result['status'] == expected
    assert result['configured'] is True
    assert result['days_left'] is not None


def test_certificate_missing_and_invalid(app, dirs):
    from app.models.site import Site
    from app.services.site_ssl import check_site_certificate

    host_missing = f'{_uniq("missing")}.example.com'
    sid_missing = _mk_site(app, slug=_uniq('v328-miss'), domain=host_missing)
    host_invalid = f'{_uniq("bad")}.example.com'
    sid_invalid = _mk_site(app, slug=_uniq('v328-bad'), domain=host_invalid)
    bad_dir = os.path.join(str(dirs['certs']), host_invalid)
    os.makedirs(bad_dir)
    with open(os.path.join(bad_dir, 'cert.pem'), 'w') as f:
        f.write('not a certificate')

    with app.app_context():
        missing = check_site_certificate(db.session.get(Site, sid_missing))
        invalid = check_site_certificate(db.session.get(Site, sid_invalid))
    assert missing['status'] == 'missing'
    assert missing['configured'] is False
    assert invalid['status'] == 'invalid'


def test_daily_check_audits_once(app, dirs):
    from app.models.audit import AuditLog
    from app.services.site_ssl import run_daily_check

    host = f'{_uniq("daily")}.example.com'
    sid = _mk_site(app, slug=_uniq('v328-daily'), domain=host)
    _write_cert(str(dirs['certs']), host, 5)
    with app.app_context():
        run_daily_check(notify=False)
        first = AuditLog.query.filter(
            AuditLog.site_id == sid, AuditLog.detail.like('%ssl_expiry%')).count()
        run_daily_check(notify=False)
        second = AuditLog.query.filter(
            AuditLog.site_id == sid, AuditLog.detail.like('%ssl_expiry%')).count()
    assert first == 1
    assert second == 1


def test_certificate_summary_isolates_failure(app, monkeypatch):
    from app.services import site_ssl

    sid_a = _mk_site(app, slug=_uniq('v328-iso-a'))
    sid_b = _mk_site(app, slug=_uniq('v328-iso-b'))

    def fake_check(site, **kwargs):
        if site.id == sid_a:
            raise RuntimeError('boom')
        return {'site_id': site.id, 'site_name': site.name, 'host': 'ok',
                'configured': True, 'expires_at': '2030-01-01',
                'days_left': 30, 'status': 'ok', 'error': None}

    monkeypatch.setattr(site_ssl, 'check_site_certificate', fake_check)
    with app.app_context():
        summary = site_ssl.check_expiring_certificates(sites=[
            site for site in __import__('app.models.site', fromlist=['Site'])
            .Site.query.filter(__import__('app.models.site', fromlist=['Site'])
                               .Site.id.in_((sid_a, sid_b))).all()])
    assert summary['checked'] == 1
    assert summary['errors'] and summary['errors'][0]['site_id'] == sid_a


# ============================================================
# 二、站点克隆
# ============================================================

def test_estimate_clone_size(app):
    from app.services.site_clone import estimate_clone_size

    data = _seed_source(app)
    with app.app_context():
        estimate = estimate_clone_size(data['site_id'])
    assert estimate['columns'] == 2
    assert estimate['articles'] == 10
    assert estimate['fragments'] == 1
    assert estimate['plugin_rows'] >= 2
    assert estimate['total'] == sum(
        estimate[k] for k in ('columns', 'articles', 'fragments',
                              'plugin_rows', 'settings'))


def test_clone_counts_and_site_flags(app):
    from app.models.site import Site
    from app.services.site_clone import clone_site

    data = _seed_source(app)
    slug = _uniq('v328-clone')
    with app.app_context():
        result = clone_site(data['site_id'], {'name': '克隆站', 'slug': slug})
        target = Site.query.filter_by(slug=slug).one()
        assert result['site_id'] == target.id
        assert target.status == 'closed'
        assert target.is_default is False
        assert result['counts']['columns'] == 2
        assert result['counts']['articles'] == 10
        assert result['counts']['fragments'] == 1
        assert result['counts']['forms'] == 1
        assert result['counts']['products'] == 1


def test_clone_column_tree_and_article_mapping(app):
    from app.models.article import Article
    from app.models.column import Column
    from app.services.site_clone import clone_site

    data = _seed_source(app)
    slug = _uniq('v328-tree')
    with app.app_context():
        result = clone_site(data['site_id'], {'name': '树', 'slug': slug})
        sid = result['site_id']
        columns = Column.query.filter_by(site_id=sid).all()
        by_slug = {c.slug: c for c in columns}
        parent = by_slug[Column.query.get(data['parent']).slug]
        child = by_slug[Column.query.get(data['child']).slug]
        assert child.parent_id == parent.id
        articles = Article.query.filter_by(site_id=sid).all()
        assert len(articles) == 10
        assert all(a.column_id == child.id for a in articles)
        assert all(a.site_id == sid for a in articles)


def test_clone_field_values_and_translations(app):
    from app.models.article import ArticleFieldValue
    from app.models.column import ColumnFieldValue, ColumnTranslation
    from app.services.site_clone import clone_site

    data = _seed_source(app)
    slug = _uniq('v328-field')
    with app.app_context():
        result = clone_site(data['site_id'], {'name': '字段', 'slug': slug})
        sid = result['site_id']
        assert ColumnFieldValue.query.join(
            ColumnFieldValue.column).filter_by(site_id=sid).count() == 1
        assert ColumnTranslation.query.join(
            ColumnTranslation.column).filter_by(site_id=sid).count() == 1
        assert ArticleFieldValue.query.join(
            ArticleFieldValue.article).filter_by(site_id=sid).count() == 10


def test_clone_excludes_versions_submissions_and_uploads(app):
    from app.models.workflow import ArticleVersion
    from app.models.article import Article
    from app.models.upload import UploadedFile
    from plugins.form.models import FormSubmission
    from app.services.site_clone import clone_site

    data = _seed_source(app)
    slug = _uniq('v328-excl')
    with app.app_context():
        result = clone_site(data['site_id'], {'name': '排除', 'slug': slug})
        sid = result['site_id']
        article_ids = [a.id for a in Article.query.filter_by(site_id=sid)]
        assert ArticleVersion.query.filter(
            ArticleVersion.article_id.in_(article_ids)).count() == 0
        assert FormSubmission.query.join(FormSubmission.form).filter_by(
            site_id=sid).count() == 0
        assert UploadedFile.query.filter_by(site_id=sid).count() == 0


def test_clone_fragments_reuse_group(app):
    from app.models.fragment import Fragment, FragmentGroup
    from app.services.site_clone import clone_site

    data = _seed_source(app)
    slug = _uniq('v328-frag')
    with app.app_context():
        before = FragmentGroup.query.count()
        result = clone_site(data['site_id'], {'name': '碎片', 'slug': slug})
        fragments = Fragment.query.filter_by(site_id=result['site_id']).all()
        assert FragmentGroup.query.count() == before
        assert len(fragments) == 1
        assert fragments[0].group_id == data['group']


def test_clone_builder_maps_column_without_revisions(app):
    from app.models.article import Article  # noqa: F401 确保模型已注册
    from app.models.builder import BuilderPage, BuilderRevision
    from app.models.column import Column
    from app.services.site_clone import clone_site

    data = _seed_source(app)
    slug = _uniq('v328-build')
    with app.app_context():
        result = clone_site(data['site_id'], {'name': '构建', 'slug': slug})
        sid = result['site_id']
        pages = BuilderPage.query.filter_by(site_id=sid).all()
        assert len(pages) == 1
        target_child = Column.query.filter_by(
            site_id=sid, slug=Column.query.get(data['child']).slug).one()
        assert pages[0].column_id == target_child.id
        assert BuilderRevision.query.filter_by(
            page_id=pages[0].id).count() == 0


def test_clone_plugin_content(app):
    from plugins.form.models import Form, FormField, FormTranslation
    from plugins.product.models import Product
    from app.services.site_clone import clone_site

    data = _seed_source(app)
    slug = _uniq('v328-plugin')
    with app.app_context():
        result = clone_site(data['site_id'], {'name': '插件', 'slug': slug})
        sid = result['site_id']
        form = Form.query.filter_by(site_id=sid).one()
        assert FormField.query.filter_by(form_id=form.id).count() == 1
        assert FormTranslation.query.filter_by(form_id=form.id).count() == 1
        assert Product.query.filter_by(site_id=sid).count() == 1


def test_unique_slug_appends_copy(app):
    from app.models.fragment import Fragment
    from app.services.site_clone import _unique_slug

    sid = _mk_site(app, slug=_uniq('v328-slug'))
    with app.app_context():
        db.session.add(Fragment(site_id=sid, name='a', slug='dup',
                                field_type='text'))
        db.session.commit()
        assert _unique_slug(Fragment, sid, 'dup') == 'dup_copy1'


def test_clone_failure_cleans_partial(app, monkeypatch):
    from app.models.site import Site
    from app.services import site_clone

    data = _seed_source(app)
    slug = _uniq('v328-fail')

    def boom(*args, **kwargs):
        raise RuntimeError('模拟失败')

    monkeypatch.setattr(site_clone, '_copy_articles', boom)
    with app.app_context():
        with pytest.raises(site_clone.CloneError):
            site_clone.clone_site(data['site_id'], {'name': '失败', 'slug': slug})
        assert Site.query.filter_by(slug=slug).first() is None


def test_clone_async_job_success(app):
    from app.models.site import Site
    from app.models.site_job import SiteJob, JOB_CLONE, JOB_SUCCESS
    from app.services.site_clone import run_clone_job
    from app.services.site_jobs import create_job

    data = _seed_source(app)
    slug = _uniq('v328-async')
    with app.app_context():
        job = create_job(JOB_CLONE, payload={'source_site_id': data['site_id']})
        run_clone_job(job.id, data['site_id'], {'name': '异步', 'slug': slug}, {})
        job = db.session.get(SiteJob, job.id)
        assert job.status == JOB_SUCCESS
        assert job.progress == 100
        assert Site.query.filter_by(slug=slug).one()


def test_clone_job_permission(app, client):
    from app.models.site_job import JOB_CLONE
    from app.services.site_jobs import create_job

    owner = _mk_super(app)
    other = _mk_user(app)
    with app.app_context():
        job = create_job(JOB_CLONE, created_by=owner)
        job_id = job.id
    _login(client, other)
    assert client.get(f'/admin/sites/clone/jobs/{job_id}').status_code == 403


def test_recover_stale_job(app):
    from app.models.site import Site
    from app.models.site_job import SiteJob, JOB_CLONE, JOB_RUNNING, JOB_FAILED
    from app.models.column import Column
    from app.services.site_jobs import recover_stale_jobs

    sid = _mk_site(app, slug=_uniq('v328-stale'))
    with app.app_context():
        db.session.add(Column(site_id=sid, name='残留', slug='c', type='list'))
        job = SiteJob(site_id=sid, job_type=JOB_CLONE, status=JOB_RUNNING,
                      progress=40, message='复制栏目',
                      updated_at=datetime.now() - timedelta(hours=2))
        db.session.add(job)
        db.session.commit()
        assert recover_stale_jobs() == 1
        assert db.session.get(SiteJob, job.id).status == JOB_FAILED
        assert db.session.get(Site, sid) is None


def test_cleanup_old_jobs(app):
    from app.models.site_job import SiteJob, JOB_CLONE, JOB_SUCCESS
    from app.services.site_jobs import cleanup_old_jobs

    with app.app_context():
        job = SiteJob(site_id=0, job_type=JOB_CLONE, status=JOB_SUCCESS,
                      created_at=datetime.now() - timedelta(days=10))
        db.session.add(job)
        db.session.commit()
        job_id = job.id
        assert cleanup_old_jobs() >= 1
        assert db.session.get(SiteJob, job_id) is None


# ============================================================
# 三、站点备份
# ============================================================

def _seed_upload(dirs, site_id, name='pic.jpg'):
    directory = os.path.join(str(dirs['uploads']), f'site{site_id}')
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with open(path, 'wb') as f:
        f.write(b'image-bytes')
    return path


def test_export_manifest_and_uploads(app, dirs):
    from app.services.site_backup import export_site, inspect_backup

    data = _seed_source(app)
    _seed_upload(dirs, data['site_id'])
    with app.app_context():
        result = export_site(data['site_id'])
        summary = inspect_backup(result['path'])
    assert os.path.isfile(result['path'])
    assert summary['tables']['columns'] == 2
    assert summary['tables']['articles'] == 10
    assert summary['uploads'] == 1
    assert summary['site']['id'] == data['site_id']
    with zipfile.ZipFile(result['path']) as zf:
        names = zf.namelist()
    assert 'manifest.json' in names
    assert 'data/articles.jsonl' in names
    assert any(n.startswith(f'uploads/site{data["site_id"]}/') for n in names)


def test_import_new_remaps_and_rewrites(app, dirs):
    from app.models.article import Article
    from app.models.column import Column
    from app.models.site import Site
    from app.models.upload import UploadedFile
    from app.services.site_backup import export_site, import_site_backup

    data = _seed_source(app)
    _seed_upload(dirs, data['site_id'])
    with app.app_context():
        source = db.session.get(Site, data['site_id'])
        source.slug = _uniq('v328-bk-src')
        article = db.session.get(Article, data['article'])
        article.content = f'/static/uploads/site{data["site_id"]}/pic.jpg'
        db.session.commit()
        exported = export_site(data['site_id'])
        result = import_site_backup(exported['path'], mode='new')
        new_id = result['site_id']
        new_site = db.session.get(Site, new_id)
        assert new_site is not None and new_site.id != data['site_id']
        assert new_site.status == 'closed'
        assert Column.query.filter_by(site_id=new_id).count() == 2
        assert Article.query.filter_by(site_id=new_id).count() == 10
        imported = Article.query.filter_by(site_id=new_id).first()
        assert f'/uploads/site{new_id}/' in imported.content
        files = UploadedFile.query.filter_by(site_id=new_id).all()
        assert len(files) == 1
        assert f'site{new_id}' in files[0].url
        assert os.path.isfile(os.path.join(
            str(dirs['uploads']), f'site{new_id}', 'pic.jpg'))


def test_import_overwrite_creates_backup(app, dirs):
    from app.models.article import Article
    from app.models.site import Site
    from app.services.site_backup import (
        export_site, import_site_backup, list_site_backups,
    )

    data = _seed_source(app)
    target = _mk_site(app, slug=_uniq('v328-ow'))
    with app.app_context():
        exported = export_site(data['site_id'])
        db.session.add(Article(site_id=target, column_id=data['child'],
                               title='旧内容'))
        db.session.commit()
        before = len(list_site_backups(target))
        result = import_site_backup(exported['path'],
                                    target_site_id=target, mode='overwrite')
        assert result['site_id'] == target
        assert Article.query.filter_by(site_id=target, title='旧内容').count() == 0
        assert len(list_site_backups(target)) > before
        assert db.session.get(Site, target).is_deleted is False


def test_import_rename_resolves_conflict(app, dirs):
    from app.models.site import Site
    from app.services.site_backup import export_site, import_site_backup

    data = _seed_source(app)
    with app.app_context():
        exported = export_site(data['site_id'])
        before = Site.query.count()
        result = import_site_backup(exported['path'], mode='rename')
        assert Site.query.count() == before + 1
        assert result['site_id'] != data['site_id']


def test_import_rejects_bad_zip(app, dirs):
    from app.services.site_backup import BackupError, inspect_backup

    path = os.path.join(str(dirs['root']), 'bad.zip')
    with open(path, 'w') as f:
        f.write('not a zip')
    with app.app_context():
        with pytest.raises(BackupError):
            inspect_backup(path)


def test_import_rejects_traversal(app, dirs):
    import json as _json
    from app.services.site_backup import BackupError, inspect_backup

    path = os.path.join(str(dirs['root']), 'evil.zip')
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('manifest.json', _json.dumps({
            'format': 'zhycms-site-backup', 'format_version': 1,
            'site': {'id': 1}, 'tables': {}}))
        zf.writestr('../evil.txt', 'x')
    with app.app_context():
        with pytest.raises(BackupError):
            inspect_backup(path)


def test_import_rejects_oversize(app, dirs):
    import json as _json
    from app.models.setting import Setting
    from app.services.site_backup import BackupError, inspect_backup

    path = os.path.join(str(dirs['root']), 'big.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('manifest.json', _json.dumps({
            'format': 'zhycms-site-backup', 'format_version': 1,
            'site': {'id': 1}, 'tables': {}}))
        zf.writestr('data/articles.jsonl', os.urandom(2 * 1024 * 1024))
    with app.app_context():
        Setting.set('site_backup_max_unzip_mb', '1')
        with pytest.raises(BackupError):
            inspect_backup(path)


def test_cleanup_expired_backups(app, dirs):
    from app.models.setting import Setting
    from app.services.site_backup import (
        cleanup_expired_site_backups, export_site,
    )

    data = _seed_source(app)
    with app.app_context():
        result = export_site(data['site_id'])
        old = datetime.now() - timedelta(days=40)
        os.utime(result['path'], (old.timestamp(), old.timestamp()))
        Setting.set('site_backup_keep_days', '30')
        assert cleanup_expired_site_backups() == 1
        assert not os.path.exists(result['path'])


def test_backup_path_validation():
    from app.services.site_backup import backup_path

    with pytest.raises(ValueError):
        backup_path(1, '../evil.zip')
    with pytest.raises(ValueError):
        backup_path(1, 'not-a-backup.zip')


# ============================================================
# 四、回收站与批量操作
# ============================================================

def test_delete_moves_to_recycle(app):
    from app.models.article import Article
    from app.models.site import Site
    from app.models.column import Column
    from app.services.site_clone import move_site_to_recycle

    sid = _mk_site(app, slug=_uniq('v328-del'))
    with app.app_context():
        column = Column(site_id=sid, name='保留', slug='keep', type='list')
        db.session.add(column)
        db.session.flush()
        db.session.add(Article(site_id=sid, column_id=column.id, title='内容'))
        db.session.commit()
        move_site_to_recycle(db.session.get(Site, sid))
        site = db.session.get(Site, sid)
        assert site.is_deleted is True and site.status == 'closed'
        assert Article.query.filter_by(site_id=sid).count() == 1


def test_restore_site(app):
    from app.models.site import Site
    from app.models.site_recycle import SiteRecycleBin
    from app.services.site_clone import move_site_to_recycle, restore_site

    sid = _mk_site(app, slug=_uniq('v328-restore'))
    with app.app_context():
        record = move_site_to_recycle(db.session.get(Site, sid))
        site = restore_site(db.session.get(SiteRecycleBin, record.id))
        assert site.is_deleted is False
        assert site.status == 'closed'
        assert db.session.get(SiteRecycleBin, record.id).restored_at is not None


def test_purge_site_backs_up_first(app, dirs):
    from app.models.article import Article
    from app.models.site import Site
    from app.models.column import Column
    from app.services.site_backup import list_site_backups
    from app.services.site_clone import (
        move_site_to_recycle, purge_site,
    )

    sid = _mk_site(app, slug=_uniq('v328-purge'))
    with app.app_context():
        column = Column(site_id=sid, name='c', slug='c', type='list')
        db.session.add(column)
        db.session.flush()
        db.session.add(Article(site_id=sid, column_id=column.id, title='x'))
        db.session.commit()
        move_site_to_recycle(db.session.get(Site, sid))
        assert purge_site(sid) is True
        assert db.session.get(Site, sid) is None
        assert Article.query.filter_by(site_id=sid).count() == 0
        assert len(list_site_backups(sid)) == 1


def test_purge_expired_recycle(app, dirs):
    from app.models.site import Site
    from app.models.site_recycle import SiteRecycleBin
    from app.services.site_clone import (
        move_site_to_recycle, purge_expired_recycle_bin,
    )

    sid = _mk_site(app, slug=_uniq('v328-expire'))
    with app.app_context():
        record = move_site_to_recycle(db.session.get(Site, sid))
        record.purge_at = datetime.now() - timedelta(minutes=1)
        db.session.commit()
        assert purge_expired_recycle_bin() >= 1
        assert db.session.get(Site, sid) is None
        assert db.session.get(SiteRecycleBin, record.id) is None


def test_batch_enable_disable_skips_default(app, client):
    from app.models.site import Site

    admin = _mk_super(app)
    default_like = _mk_site(app, slug=_uniq('v328-default'), is_default=True)
    normal = _mk_site(app, slug=_uniq('v328-batch'))
    _login(client, admin)
    response = client.post('/admin/sites/batch', data={
        'action': 'disable',
        'site_ids': [str(default_like), str(normal)],
    })
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Site, default_like).status == 'open'
        assert db.session.get(Site, normal).status == 'closed'


def test_batch_delete_and_role(app, client):
    from app.models.rbac import UserRole
    from app.models.site import Site
    from app.services.user_service import assignable_site_roles

    admin = _mk_super(app)
    user_id = _mk_user(app)
    first = _mk_site(app, slug=_uniq('v328-bdel-a'))
    second = _mk_site(app, slug=_uniq('v328-bdel-b'))
    _login(client, admin)

    with app.app_context():
        roles = assignable_site_roles()
    assert roles, '缺少可分配的站点角色'
    role_code = roles[0].code
    response = client.post('/admin/sites/batch/assign-role', data={
        'user_id': str(user_id), 'role_code': role_code,
        'site_ids': [str(first), str(second)],
    })
    assert response.status_code == 302
    with app.app_context():
        assert UserRole.query.filter(
            UserRole.user_id == user_id,
            UserRole.site_id.in_((first, second))).count() == 2

    response = client.post('/admin/sites/batch', data={
        'action': 'delete', 'site_ids': [str(first), str(second)]})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Site, first).is_deleted is True
        assert db.session.get(Site, second).is_deleted is True


# ============================================================
# 五、后台页面与权限
# ============================================================

def test_ssl_panel_and_backup_page(app, client):
    admin = _mk_super(app)
    sid = _mk_site(app, slug=_uniq('v328-page'))
    _login(client, admin)
    assert client.get('/admin/sites/ssl').status_code == 200
    assert client.get(f'/admin/sites/{sid}/backups').status_code == 200
    assert client.get(f'/admin/sites/{sid}/clone').status_code == 200
    assert client.get('/admin/sites/recycle').status_code == 200


def test_site_pages_require_permission(app, client):
    from app.models.rbac import UserRole
    from app.models.user import User

    with app.app_context():
        role = __import__('app.models.rbac', fromlist=['Role']).Role.query.filter_by(
            code='readonly_viewer', is_deleted=False).first()
        user = User(username=_uniq('v328-reader'), is_deleted=False)
        user.set_password('Abcdef123456!')
        db.session.add(user)
        db.session.flush()
        if role:
            db.session.add(UserRole(user_id=user.id, role_id=role.id,
                                    site_id=None))
        db.session.commit()
        uid = user.id
    _login(client, uid)
    assert client.get('/admin/sites/ssl').status_code == 403
    assert client.get('/admin/sites/recycle').status_code == 403
