"""change_proposals: several writes the agent prepared, shown to the user before anything changes

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-10-20 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a0b1c2d3e4f5'
down_revision: Union[str, None] = 'f9a0b1c2d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'change_proposals',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('operations', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('preview', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'applied', 'rejected', 'failed')", name=op.f('ck_change_proposals_status_valid')
        ),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name='fk_change_proposals_account_id_accounts',
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_change_proposals_user_id_users',
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'],
                                name='fk_change_proposals_conversation_id_conversations', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name='pk_change_proposals'),
    )
    op.create_index('ix_change_proposals_account_status', 'change_proposals', ['account_id', 'status'])
    op.create_index('ix_change_proposals_conversation_id', 'change_proposals', ['conversation_id'])


def downgrade() -> None:
    op.drop_index('ix_change_proposals_conversation_id', table_name='change_proposals')
    op.drop_index('ix_change_proposals_account_status', table_name='change_proposals')
    op.drop_table('change_proposals')
