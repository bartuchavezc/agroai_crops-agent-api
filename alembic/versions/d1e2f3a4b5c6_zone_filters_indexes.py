"""indexes for per-zone event / reminder / report queries

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-10-09 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c0d1e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_field_events_zone_occurred', 'field_events', ['zone_id', 'occurred_at'], unique=False)
    op.create_index('ix_reminders_zone_due', 'reminders', ['zone_id', 'due_at'], unique=False)
    op.create_index('ix_reports_zone_created', 'reports', ['zone_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_reports_zone_created', table_name='reports')
    op.drop_index('ix_reminders_zone_due', table_name='reminders')
    op.drop_index('ix_field_events_zone_occurred', table_name='field_events')
