"""bitácora: skipped entries with a reason, losses, rain from the weather data; lots record what they resow

- field_events.outcome (done | skipped) + reason: "no regué: llovió" is an entry too.
- event types + loss (lowers a lot's live count) and rain (written by the system); source + system.
- lots.replaces_lot_id: a resowing points at the lot it replaces (in part or entirely).

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-10-23 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a0b1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TYPES = (
    "('irrigation', 'fertilization', 'pest_control', 'sowing', 'transplant', 'harvest', 'inspection', "
    "'observation', 'soil_prep', 'amendment', 'pruning', 'weeding', 'photo')"
)
NEW_TYPES = OLD_TYPES[:-1] + ", 'loss', 'rain')"


def upgrade() -> None:
    op.drop_constraint(op.f('ck_field_events_type_valid'), 'field_events', type_='check')
    op.create_check_constraint(op.f('ck_field_events_type_valid'), 'field_events', f"type IN {NEW_TYPES}")
    op.drop_constraint(op.f('ck_field_events_source_valid'), 'field_events', type_='check')
    op.create_check_constraint(
        op.f('ck_field_events_source_valid'), 'field_events', "source IN ('user', 'agent', 'system')"
    )
    op.add_column('field_events', sa.Column('outcome', sa.String(length=10), server_default='done', nullable=False))
    op.create_check_constraint(
        op.f('ck_field_events_outcome_valid'), 'field_events', "outcome IN ('done', 'skipped')"
    )
    op.add_column('field_events', sa.Column('reason', sa.Text(), nullable=True))
    op.add_column('lots', sa.Column('replaces_lot_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_lots_replaces_lot_id_lots', 'lots', 'lots', ['replaces_lot_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_lots_replaces_lot_id_lots', 'lots', type_='foreignkey')
    op.drop_column('lots', 'replaces_lot_id')
    op.drop_column('field_events', 'reason')
    op.drop_constraint(op.f('ck_field_events_outcome_valid'), 'field_events', type_='check')
    op.drop_column('field_events', 'outcome')
    op.execute("DELETE FROM field_events WHERE type IN ('loss', 'rain') OR source = 'system'")
    op.drop_constraint(op.f('ck_field_events_source_valid'), 'field_events', type_='check')
    op.create_check_constraint(op.f('ck_field_events_source_valid'), 'field_events', "source IN ('user', 'agent')")
    op.drop_constraint(op.f('ck_field_events_type_valid'), 'field_events', type_='check')
    op.create_check_constraint(op.f('ck_field_events_type_valid'), 'field_events', f"type IN {OLD_TYPES}")
