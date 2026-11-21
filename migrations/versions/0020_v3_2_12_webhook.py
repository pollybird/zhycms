"""v3.2.12: Webhook 事件订阅

新增 webhook_subscriptions（订阅）与 webhook_events（投递记录）两张表。
升降级幂等，SQLite / MySQL / PostgreSQL 通用。

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-21

"""
from alembic import op
import sqlalchemy as sa


revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def _has_table(table):
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade():
    if not _has_table('webhook_subscriptions'):
        op.create_table(
            'webhook_subscriptions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('site_id', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('url', sa.String(length=500), nullable=False),
            sa.Column('secret_enc', sa.Text(), nullable=False, server_default=''),
            sa.Column('events', sa.Text(), nullable=False, server_default=''),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('site_id', 'url', name='uq_webhook_sub_site_url'),
        )
        op.create_index('ix_webhook_subscriptions_site_id',
                        'webhook_subscriptions', ['site_id'])

    if not _has_table('webhook_events'):
        op.create_table(
            'webhook_events',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('subscription_id', sa.Integer(), nullable=False),
            sa.Column('site_id', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('event_type', sa.String(length=64), nullable=False),
            sa.Column('payload_json', sa.Text(), nullable=False, server_default='{}'),
            sa.Column('status', sa.String(length=16), nullable=False,
                      server_default='pending'),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('next_retry_at', sa.DateTime()),
            sa.Column('last_status_code', sa.Integer()),
            sa.Column('last_error', sa.Text()),
            sa.Column('replay_id', sa.String(length=64), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('delivered_at', sa.DateTime()),
            sa.ForeignKeyConstraint(['subscription_id'],
                                    ['webhook_subscriptions.id'],
                                    ondelete='CASCADE'),
            sa.UniqueConstraint('replay_id', name='uq_webhook_events_replay_id'),
        )
        op.create_index('ix_webhook_events_subscription_id',
                        'webhook_events', ['subscription_id'])
        op.create_index('ix_webhook_events_site_id', 'webhook_events', ['site_id'])
        op.create_index('ix_webhook_events_next_retry_at',
                        'webhook_events', ['next_retry_at'])
        op.create_index('ix_webhook_events_status_retry',
                        'webhook_events', ['status', 'next_retry_at'])
        op.create_index('ix_webhook_events_site_created',
                        'webhook_events', ['site_id', 'created_at'])


def downgrade():
    if _has_table('webhook_events'):
        op.drop_table('webhook_events')
    if _has_table('webhook_subscriptions'):
        op.drop_table('webhook_subscriptions')
