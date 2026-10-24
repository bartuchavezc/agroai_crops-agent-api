"""applications: the follow-up (seguimiento) a record treats

Revision ID: c3e4a5b6d7f8
Revises: b2d3f4a5c6e7
Create Date: 2026-10-24 18:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c3e4a5b6d7f8'
down_revision: Union[str, None] = 'b2d3f4a5c6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'applications',
        sa.Column('followup_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('followups.id', ondelete='SET NULL')),
    )


def downgrade() -> None:
    op.drop_column('applications', 'followup_id')
