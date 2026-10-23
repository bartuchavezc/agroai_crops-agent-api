"""the assistant writes first: voice messages, notes and nudges in conversations, summaries, Web Push, preferences

- conversation_messages.audio_identifier (a voice message; content holds its transcription) and origin
  (turn | note | nudge: written outside a chat turn).
- digests: daily / weekly summaries per account. push_subscriptions: devices that accepted notifications.
  notification_preferences: per person limits, quiet hours and summaries. nudge_log: every proactive decision.
- notifications: types digest, nudge, application; entity types digest, conversation, application.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-10-23 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('digests',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('local_date', sa.Date(), nullable=False),
    sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('daily', 'weekly')", name=op.f('ck_digests_kind_valid')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_digests_account_id_accounts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_digests')),
    sa.UniqueConstraint('account_id', 'kind', 'local_date', name='uq_digests_account_kind_date')
    )
    op.create_table('notification_preferences',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('nudges_enabled', sa.Boolean(), nullable=False),
    sa.Column('max_nudges_per_day', sa.Integer(), nullable=False),
    sa.Column('quiet_start', sa.String(length=5), nullable=False),
    sa.Column('quiet_end', sa.String(length=5), nullable=False),
    sa.Column('daily_digest', sa.Boolean(), nullable=True),
    sa.Column('weekly_digest', sa.Boolean(), nullable=True),
    sa.Column('push_enabled', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notification_preferences_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_notification_preferences'))
    )
    op.create_table('push_subscriptions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('endpoint', sa.Text(), nullable=False),
    sa.Column('p256dh', sa.String(length=255), nullable=False),
    sa.Column('auth', sa.String(length=255), nullable=False),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failures', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_push_subscriptions_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_push_subscriptions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_push_subscriptions')),
    sa.UniqueConstraint('endpoint', name='uq_push_subscriptions_endpoint')
    )
    op.create_index(op.f('ix_push_subscriptions_user_id'), 'push_subscriptions', ['user_id'], unique=False)
    op.create_table('nudge_log',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('window', sa.String(length=10), nullable=False),
    sa.Column('signals', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('signal_keys', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('outcome', sa.String(length=12), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('conversation_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("outcome IN ('sent', 'silent', 'budget', 'quiet_hours', 'failed')", name=op.f('ck_nudge_log_outcome_valid')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_nudge_log_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_nudge_log_conversation_id_conversations'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_nudge_log_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_nudge_log'))
    )
    op.create_index('ix_nudge_log_account_created', 'nudge_log', ['account_id', 'created_at'], unique=False)
    op.create_index('ix_nudge_log_user_created', 'nudge_log', ['user_id', 'created_at'], unique=False)
    op.add_column('conversation_messages', sa.Column('audio_identifier', sa.String(length=255), nullable=True))
    op.add_column('conversation_messages', sa.Column('origin', sa.String(length=10), server_default='turn', nullable=False))
    op.drop_constraint(op.f('ck_notifications_notification_type_valid'), 'notifications', type_='check')
    op.create_check_constraint(
        op.f('ck_notifications_notification_type_valid'), 'notifications',
        "type IN ('report_diagnosis', 'report_periodic', 'report_soil', 'event', 'reminder', 'digest', 'nudge', "
        "'application')",
    )
    op.drop_constraint(op.f('ck_notifications_notification_entity_type_valid'), 'notifications', type_='check')
    op.create_check_constraint(
        op.f('ck_notifications_notification_entity_type_valid'), 'notifications',
        "entity_type IN ('report', 'event', 'reminder', 'digest', 'conversation', 'application')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE type IN ('digest', 'nudge', 'application') "
               "OR entity_type IN ('digest', 'conversation', 'application')")
    op.drop_constraint(op.f('ck_notifications_notification_entity_type_valid'), 'notifications', type_='check')
    op.create_check_constraint(
        op.f('ck_notifications_notification_entity_type_valid'), 'notifications',
        "entity_type IN ('report', 'event', 'reminder')",
    )
    op.drop_constraint(op.f('ck_notifications_notification_type_valid'), 'notifications', type_='check')
    op.create_check_constraint(
        op.f('ck_notifications_notification_type_valid'), 'notifications',
        "type IN ('report_diagnosis', 'report_periodic', 'report_soil', 'event', 'reminder')",
    )
    op.drop_column('conversation_messages', 'origin')
    op.drop_column('conversation_messages', 'audio_identifier')
    op.drop_index('ix_nudge_log_user_created', table_name='nudge_log')
    op.drop_index('ix_nudge_log_account_created', table_name='nudge_log')
    op.drop_table('nudge_log')
    op.drop_index(op.f('ix_push_subscriptions_user_id'), table_name='push_subscriptions')
    op.drop_table('push_subscriptions')
    op.drop_table('notification_preferences')
    op.drop_table('digests')
