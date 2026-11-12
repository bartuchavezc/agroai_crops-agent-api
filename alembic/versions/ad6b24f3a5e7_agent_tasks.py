"""agent_tasks: the agent's background work (to-do list, trace, budget, approval)

Revision ID: ad6b24f3a5e7
Revises: 9c5a13e2f4d6
Create Date: 2026-11-05 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'ad6b24f3a5e7'
down_revision: Union[str, None] = '9c5a13e2f4d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_tasks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=True),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('goal', sa.Text(), nullable=False),
        sa.Column('input', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('todos', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('trace', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('max_calls', sa.Integer(), nullable=False),
        sa.Column('used_calls', sa.Integer(), nullable=False),
        sa.Column('tokens', sa.Integer(), nullable=False),
        sa.Column('proposal_id', sa.UUID(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('plan_lots', 'replan_lot', 'general')", name=op.f('ck_agent_tasks_kind_valid')),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'done', 'failed', 'cancelled')",
            name=op.f('ck_agent_tasks_status_valid')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_tasks_status_created', 'agent_tasks', ['status', 'created_at'])
    op.create_index('ix_agent_tasks_account_created', 'agent_tasks', ['account_id', 'created_at'])
    op.create_index(op.f('ix_agent_tasks_conversation_id'), 'agent_tasks', ['conversation_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_agent_tasks_conversation_id'), table_name='agent_tasks')
    op.drop_index('ix_agent_tasks_account_created', table_name='agent_tasks')
    op.drop_index('ix_agent_tasks_status_created', table_name='agent_tasks')
    op.drop_table('agent_tasks')
