"""event_lots: the bitácora — every event keeps the lots it reached; new event types; report reason

An event is logged on a zone (every lot growing there) or on specific lots, and event_lots fixes which lots
those were. Existing events get the same snapshot rebuilt from what was growing at the time: their own lot if
they had one, else the lots of their zone (or of the whole field) sown by then and not yet harvested.

Event types: treatment -> pest_control; pest/disease sightings -> inspection (the sighting kept in data.subtype);
new: soil_prep, amendment.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-10-20 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, None] = 'c6d7e8f9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TYPES = (
    "('sowing', 'transplant', 'irrigation', 'fertilization', 'treatment', 'pruning', 'weeding', 'pest_sighting', "
    "'disease_sighting', 'harvest', 'observation', 'photo')"
)
NEW_TYPES = (
    "('irrigation', 'fertilization', 'pest_control', 'sowing', 'transplant', 'harvest', 'inspection', "
    "'observation', 'soil_prep', 'amendment', 'pruning', 'weeding', 'photo')"
)
# A lot was growing at an event when it was sown by that day (or has no date) and not harvested before it.
GROWING_AT = (
    "l.deleted_at IS NULL AND (l.planting_date IS NULL OR l.planting_date <= e.occurred_at::date) "
    "AND (l.actual_harvest_date IS NULL OR l.actual_harvest_date >= e.occurred_at::date) "
    "AND l.status <> 'planned'"
)


def upgrade() -> None:
    op.create_table(
        'event_lots',
        sa.Column('event_id', sa.UUID(), nullable=False),
        sa.Column('lot_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ['event_id'], ['field_events.id'], name='fk_event_lots_event_id_field_events', ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(['lot_id'], ['lots.id'], name='fk_event_lots_lot_id_lots', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('event_id', 'lot_id', name='pk_event_lots'),
    )
    op.create_index('ix_event_lots_lot_id', 'event_lots', ['lot_id'])
    op.execute("INSERT INTO event_lots (event_id, lot_id) SELECT id, lot_id FROM field_events WHERE lot_id IS NOT NULL")
    op.execute(
        "INSERT INTO event_lots (event_id, lot_id) SELECT DISTINCT e.id, l.id FROM field_events e "
        "JOIN lot_zones lz ON lz.zone_id = e.zone_id JOIN lots l ON l.id = lz.lot_id "
        f"WHERE e.lot_id IS NULL AND e.zone_id IS NOT NULL AND {GROWING_AT}"
    )
    op.execute(
        "INSERT INTO event_lots (event_id, lot_id) SELECT e.id, l.id FROM field_events e "
        "JOIN lots l ON l.field_id = e.field_id "
        f"WHERE e.lot_id IS NULL AND e.zone_id IS NULL AND {GROWING_AT}"
    )
    op.drop_constraint('fk_field_events_lot_id_lots', 'field_events', type_='foreignkey')
    op.drop_column('field_events', 'lot_id')
    op.add_column(
        'field_events',
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.drop_constraint(op.f('ck_field_events_type_valid'), 'field_events', type_='check')
    op.execute("UPDATE field_events SET type = 'pest_control' WHERE type = 'treatment'")
    op.execute(
        "UPDATE field_events SET data = coalesce(data, '{}'::jsonb) || jsonb_build_object('subtype', type), "
        "type = 'inspection' WHERE type IN ('pest_sighting', 'disease_sighting')"
    )
    op.create_check_constraint(op.f('ck_field_events_type_valid'), 'field_events', f"type IN {NEW_TYPES}")

    op.add_column('reports', sa.Column('reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('reports', 'reason')

    op.drop_constraint(op.f('ck_field_events_type_valid'), 'field_events', type_='check')
    op.execute("UPDATE field_events SET type = 'treatment' WHERE type = 'pest_control'")
    op.execute(
        "UPDATE field_events SET type = CASE WHEN data->>'subtype' = 'disease_sighting' THEN 'disease_sighting' "
        "ELSE 'pest_sighting' END, data = data - 'subtype' WHERE type = 'inspection'"
    )
    op.execute("UPDATE field_events SET type = 'observation' WHERE type IN ('soil_prep', 'amendment')")
    op.create_check_constraint(op.f('ck_field_events_type_valid'), 'field_events', f"type IN {OLD_TYPES}")

    op.drop_column('field_events', 'updated_at')
    op.add_column('field_events', sa.Column('lot_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_field_events_lot_id_lots', 'field_events', 'lots', ['lot_id'], ['id'], ondelete='SET NULL'
    )
    # Only an event that reached a single lot was about that lot.
    op.execute(
        "UPDATE field_events e SET lot_id = s.lot_id FROM (SELECT event_id, min(lot_id::text)::uuid AS lot_id "
        "FROM event_lots GROUP BY event_id HAVING count(*) = 1) s WHERE s.event_id = e.id"
    )
    op.drop_index('ix_event_lots_lot_id', table_name='event_lots')
    op.drop_table('event_lots')
