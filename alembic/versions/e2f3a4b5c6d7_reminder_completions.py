"""reminder_completions: a record of every time a (recurring) reminder was done

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-09 17:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reminder_completions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reminder_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('field_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('zone_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('crop_cycle_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reminder_id'], ['reminders.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['field_id'], ['fields.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['zone_id'], ['field_zones.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['completed_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_reminder_completions_zone_done', 'reminder_completions', ['zone_id', 'completed_at'])
    op.create_index('ix_reminder_completions_account_done', 'reminder_completions', ['account_id', 'completed_at'])
    # Reminders already done before this existed: one completion each.
    op.execute(
        "INSERT INTO reminder_completions (id, account_id, reminder_id, field_id, zone_id, crop_cycle_id, title, "
        "description, completed_at) SELECT gen_random_uuid(), account_id, id, field_id, zone_id, crop_cycle_id, "
        "title, description, completed_at FROM reminders WHERE status = 'hecho' AND completed_at IS NOT NULL "
        "AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index('ix_reminder_completions_account_done', table_name='reminder_completions')
    op.drop_index('ix_reminder_completions_zone_done', table_name='reminder_completions')
    op.drop_table('reminder_completions')
