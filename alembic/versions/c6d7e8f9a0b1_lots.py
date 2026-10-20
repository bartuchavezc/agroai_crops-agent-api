"""lots: crop cycles become lots (lotes) that can span several zones; zones get free numbers, size and soil

crop_cycles is renamed to lots in place, so every id and every reference survives untouched: the
crop_cycle_id columns elsewhere become lot_id, still pointing at the same rows. A lot's zone moves to
lot_zones (a lot sown the same day in two canteros is one lot). plant_count becomes quantity + unit.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-10-20 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c6d7e8f9a0b1'
down_revision: Union[str, None] = 'b5c6d7e8f9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REFERENCING = (
    'field_events', 'reports', 'crop_plans', 'plan_stages', 'plan_sowings', 'reminders', 'reminder_completions',
    'budget_entries',
)
OLD_STATUSES = "('planned', 'planted', 'growing', 'harvested', 'failed')"
NEW_STATUSES = "('planned', 'seedbed', 'planted', 'growing', 'harvesting', 'harvested', 'failed')"


def _rename_names(tables: tuple[str, ...], pattern: str, replacement: str) -> None:
    """Renames the constraints and indexes of `tables` whose name matches `pattern` (a PostgreSQL regex), so
    they keep following the naming convention after the table/column renames."""
    table_list = ", ".join(f"'{t}'" for t in tables)
    op.execute(f"""
    DO $$
    DECLARE r record;
    BEGIN
      FOR r IN
        SELECT c.conname AS name, t.relname AS tbl FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname IN ({table_list}) AND c.conname ~ '{pattern}' AND c.contype <> 'p'
      LOOP
        EXECUTE format('ALTER TABLE %I RENAME CONSTRAINT %I TO %I', r.tbl, r.name,
                       regexp_replace(r.name, '{pattern}', '{replacement}', 'g'));
      END LOOP;
      FOR r IN
        SELECT i.relname AS name FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
        JOIN pg_class t ON t.oid = x.indrelid
        WHERE t.relname IN ({table_list}) AND i.relname ~ '{pattern}'
      LOOP
        EXECUTE format('ALTER INDEX %I RENAME TO %I', r.name, regexp_replace(r.name, '{pattern}', '{replacement}', 'g'));
      END LOOP;
    END $$;
    """)


def upgrade() -> None:
    # Zones: the number is the user's own (no unique index, renumbering is checked by the service).
    op.drop_index('uq_field_zones_field_type_number_active', table_name='field_zones')
    op.create_index('ix_field_zones_field_type_number', 'field_zones', ['field_id', 'type', 'number'])
    op.add_column('field_zones', sa.Column('length_m', sa.Float(), nullable=True))
    op.add_column('field_zones', sa.Column('width_m', sa.Float(), nullable=True))
    op.add_column(
        'field_zones',
        sa.Column('soil', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    )

    # crop_cycles -> lots, keeping every id.
    op.rename_table('crop_cycles', 'lots')
    op.execute("ALTER TABLE lots RENAME CONSTRAINT pk_crop_cycles TO pk_lots")
    _rename_names(('lots',), 'crop_cycles', 'lots')
    op.drop_constraint(op.f('ck_lots_status_valid'), 'lots', type_='check')
    op.create_check_constraint(op.f('ck_lots_status_valid'), 'lots', f"status IN {NEW_STATUSES}")
    op.add_column('lots', sa.Column('season', sa.String(length=10), nullable=True))
    op.add_column('lots', sa.Column('number', sa.Integer(), nullable=True))
    op.create_check_constraint(op.f('ck_lots_number_positive'), 'lots', "number IS NULL OR number >= 1")
    op.add_column('lots', sa.Column('transplant_date', sa.Date(), nullable=True))
    op.add_column('lots', sa.Column('quantity', sa.Float(), nullable=True))
    op.add_column('lots', sa.Column('unit', sa.String(length=30), nullable=True))
    op.execute("UPDATE lots SET quantity = plant_count, unit = 'plantas' WHERE plant_count IS NOT NULL")
    op.drop_column('lots', 'plant_count')
    op.add_column('lots', sa.Column('plan_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_lots_plan_id_crop_plans', 'lots', 'crop_plans', ['plan_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_lots_plan_id', 'lots', ['plan_id'])
    op.add_column('lots', sa.Column('origin_lot_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_lots_origin_lot_id_lots', 'lots', 'lots', ['origin_lot_id'], ['id'], ondelete='SET NULL')

    op.create_table(
        'lot_zones',
        sa.Column('lot_id', sa.UUID(), nullable=False),
        sa.Column('zone_id', sa.UUID(), nullable=False),
        sa.Column('position', sa.Integer(), server_default='0', nullable=False),
        sa.ForeignKeyConstraint(['lot_id'], ['lots.id'], name='fk_lot_zones_lot_id_lots', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['zone_id'], ['field_zones.id'], name='fk_lot_zones_zone_id_field_zones', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('lot_id', 'zone_id', name='pk_lot_zones'),
    )
    op.create_index('ix_lot_zones_zone_id', 'lot_zones', ['zone_id'])
    op.execute("INSERT INTO lot_zones (lot_id, zone_id, position) SELECT id, zone_id, 0 FROM lots WHERE zone_id IS NOT NULL")
    op.drop_index('ix_lots_zone_id', table_name='lots')
    op.drop_constraint('fk_lots_zone_id_field_zones', 'lots', type_='foreignkey')
    op.drop_column('lots', 'zone_id')

    # Everything that pointed at a crop cycle now points at the same row as a lot.
    for table in REFERENCING:
        op.alter_column(table, 'crop_cycle_id', new_column_name='lot_id')
    op.alter_column('reports', 'crop_cycle_ids', new_column_name='lot_ids')
    _rename_names(REFERENCING, 'crop_cycles', 'lots')
    _rename_names(REFERENCING, 'crop_cycle_id', 'lot_id')


def downgrade() -> None:
    _rename_names(REFERENCING, '(?<!seed)_lot_id', '_crop_cycle_id')
    _rename_names(REFERENCING, '_lots$', '_crop_cycles')
    op.alter_column('reports', 'lot_ids', new_column_name='crop_cycle_ids')
    for table in REFERENCING:
        op.alter_column(table, 'lot_id', new_column_name='crop_cycle_id')

    op.add_column('lots', sa.Column('zone_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_lots_zone_id_field_zones', 'lots', 'field_zones', ['zone_id'], ['id'], ondelete='SET NULL'
    )
    op.create_index('ix_lots_zone_id', 'lots', ['zone_id'])
    op.execute(
        "UPDATE lots SET zone_id = lz.zone_id FROM (SELECT DISTINCT ON (lot_id) lot_id, zone_id FROM lot_zones "
        "ORDER BY lot_id, position) lz WHERE lz.lot_id = lots.id"
    )
    op.drop_index('ix_lot_zones_zone_id', table_name='lot_zones')
    op.drop_table('lot_zones')

    op.drop_constraint('fk_lots_origin_lot_id_lots', 'lots', type_='foreignkey')
    op.drop_column('lots', 'origin_lot_id')
    op.drop_index('ix_lots_plan_id', table_name='lots')
    op.drop_constraint('fk_lots_plan_id_crop_plans', 'lots', type_='foreignkey')
    op.drop_column('lots', 'plan_id')
    op.add_column('lots', sa.Column('plant_count', sa.Integer(), nullable=True))
    op.execute("UPDATE lots SET plant_count = round(quantity)::int WHERE quantity IS NOT NULL AND unit = 'plantas'")
    op.drop_column('lots', 'unit')
    op.drop_column('lots', 'quantity')
    op.drop_column('lots', 'transplant_date')
    op.drop_constraint(op.f('ck_lots_number_positive'), 'lots', type_='check')
    op.drop_column('lots', 'number')
    op.drop_column('lots', 'season')
    op.drop_constraint(op.f('ck_lots_status_valid'), 'lots', type_='check')
    op.execute("UPDATE lots SET status = 'planned' WHERE status = 'seedbed'")
    op.execute("UPDATE lots SET status = 'growing' WHERE status = 'harvesting'")
    op.create_check_constraint(op.f('ck_lots_status_valid'), 'lots', f"status IN {OLD_STATUSES}")
    _rename_names(('lots',), '^(fk|ix|ck)_lots_', '\\1_crop_cycles_')
    op.execute("ALTER TABLE lots RENAME CONSTRAINT pk_lots TO pk_crop_cycles")
    op.rename_table('lots', 'crop_cycles')

    op.drop_column('field_zones', 'soil')
    op.drop_column('field_zones', 'width_m')
    op.drop_column('field_zones', 'length_m')
    op.drop_index('ix_field_zones_field_type_number', table_name='field_zones')
    op.create_index(
        'uq_field_zones_field_type_number_active', 'field_zones', ['field_id', 'type', 'number'], unique=True,
        postgresql_where=sa.text('deleted_at IS NULL'),
    )
