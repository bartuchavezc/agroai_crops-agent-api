"""tracking profile (intensity, growing context) and what happened after each nudge

Revision ID: 7a3e91c0d2b4
Revises: b5c4d3e2f1a0
Create Date: 2026-11-05 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '7a3e91c0d2b4'
down_revision: Union[str, None] = 'b5c4d3e2f1a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_profiles', sa.Column('tracking_intensity', sa.String(length=10), nullable=True))
    op.add_column('user_profiles', sa.Column(
        'growing_context', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'))
    op.create_check_constraint(
        op.f('ck_user_profiles_tracking_intensity_valid'), 'user_profiles',
        "tracking_intensity IS NULL OR tracking_intensity IN ('baja', 'media', 'alta')")
    op.add_column('nudge_log', sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('nudge_log', sa.Column('response_channel', sa.String(length=10), nullable=True))
    op.add_column('nudge_log', sa.Column('response_text', sa.Text(), nullable=True))
    op.add_column('nudge_log', sa.Column(
        'quick_replies', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'))
    op.add_column('nudge_log', sa.Column('plan_ref', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index('ix_nudge_log_conversation', 'nudge_log', ['conversation_id'])


def downgrade() -> None:
    op.drop_index('ix_nudge_log_conversation', table_name='nudge_log')
    for column in ('plan_ref', 'quick_replies', 'response_text', 'response_channel', 'responded_at'):
        op.drop_column('nudge_log', column)
    op.drop_constraint(op.f('ck_user_profiles_tracking_intensity_valid'), 'user_profiles', type_='check')
    op.drop_column('user_profiles', 'growing_context')
    op.drop_column('user_profiles', 'tracking_intensity')
