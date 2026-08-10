from flask import render_template, redirect, url_for, request
from flask_login import current_user

from ..extensions import db
from ..models.user import LoginLog
from ..models.column import Column
from ..models.article import Article
from ..models.form import FormSubmission
from . import admin_bp
from ..utils.helpers import admin_required


@admin_bp.route('/')
@admin_required
def dashboard():
    stats = {
        'columns': Column.query.filter_by(is_deleted=False).count(),
        'articles': Article.query.filter_by(is_deleted=False).count(),
        'pending_submissions': FormSubmission.query.filter_by(
            is_deleted=False, is_read=False
        ).count(),
        'recent_logs': LoginLog.query.order_by(LoginLog.created_at.desc()).limit(8).all(),
    }
    return render_template('admin/dashboard.html', stats=stats)
