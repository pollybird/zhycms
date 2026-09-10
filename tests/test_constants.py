"""常量治理测试：constants 模块完整性与门禁。"""
import pytest
import subprocess
import sys
from pathlib import Path


@pytest.mark.constants
class TestConstants:

    def test_workflow_constants(self):
        from app.constants import Workflow
        assert Workflow.STATUS_DRAFT == 'draft'
        assert Workflow.STATUS_PUBLISHED == 'published'
        assert Workflow.STATUS_ARCHIVED == 'archived'
        assert Workflow.STATUS_REVIEW == 'review'
        assert Workflow.STATUS_PUBLISHED in Workflow.PUBLISHED_STATUSES

    def test_upload_constants(self):
        from app.constants import Upload
        assert 'jpg' in Upload.IMAGE_EXTS
        assert 'zip' in Upload.THEME_EXTS
        assert 'pdf' in Upload.RESUME_EXTS

    def test_constants_zero_dependencies(self):
        """constants.py 不导入 Flask/db/任何 app 模块。"""
        import app.constants as const_mod
        # 检查模块的 globals 不含 Flask 扩展
        forbidden = ['flask', 'sqlalchemy', 'db', 'app']
        src = Path(const_mod.__file__).read_text()
        for kw in forbidden:
            assert f'import {kw}' not in src, f'constants.py 不应导入 {kw}'
            assert f'from {kw}' not in src, f'constants.py 不应从 {kw} 导入'

    def test_check_constants_passes(self):
        """CI 门禁脚本零违规。"""
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, str(root / 'scripts' / 'check_constants.py')],
            capture_output=True, text=True, cwd=str(root)
        )
        assert result.returncode == 0, f'常量门禁失败:\n{result.stdout}'

    def test_workflow_re_export_backward_compat(self):
        """workflow.py 重导出的常量与 constants.py 一致。"""
        from app.constants import Workflow
        from app.models.workflow import (
            STATUS_DRAFT, STATUS_PUBLISHED, STATUS_ARCHIVED, STATUS_REVIEW,
            STATUSES_ENABLED,
        )
        assert STATUS_DRAFT == Workflow.STATUS_DRAFT
        assert STATUS_PUBLISHED == Workflow.STATUS_PUBLISHED
        assert STATUS_ARCHIVED == Workflow.STATUS_ARCHIVED
        assert STATUS_REVIEW == Workflow.STATUS_REVIEW
        assert Workflow.STATUS_PUBLISHED in STATUSES_ENABLED

    def test_roles_re_export_backward_compat(self):
        """rbac.py 重导出的角色常量与 constants.py 一致。"""
        from app.constants import Roles
        from app.models.rbac import (
            ROLE_SUPER_ADMIN, ROLE_CONTENT_AUDITOR,
            ROLE_CONTENT_EDITOR, ROLE_READONLY_VIEWER,
        )
        assert ROLE_SUPER_ADMIN == Roles.SUPER_ADMIN
        assert ROLE_CONTENT_AUDITOR == Roles.CONTENT_AUDITOR
        assert ROLE_CONTENT_EDITOR == Roles.CONTENT_EDITOR
        assert ROLE_READONLY_VIEWER == Roles.READONLY_VIEWER
