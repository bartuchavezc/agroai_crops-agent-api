"""conversation_messages.status/error_code: a turn is saved as it starts (user message + pending
assistant placeholder) and completed or marked as failed when it ends

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-05 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'conversation_messages',
        sa.Column('status', sa.String(length=10), server_default='complete', nullable=False),
    )
    op.add_column('conversation_messages', sa.Column('error_code', sa.String(length=50), nullable=True))
    op.create_check_constraint(
        op.f('ck_conversation_messages_status_valid'), 'conversation_messages',
        "status IN ('complete', 'pending', 'error')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f('ck_conversation_messages_status_valid'), 'conversation_messages', type_='check')
    op.drop_column('conversation_messages', 'error_code')
    op.drop_column('conversation_messages', 'status')
