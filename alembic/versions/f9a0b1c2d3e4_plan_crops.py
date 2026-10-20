"""plan_crops: a general plan has objectives, zones and crops whose sowings are planned lots with sowing tasks

- crop_plans.objectives; plan_zones (the zones a general plan covers; filled from its zone_id).
- plan_crops: a crop of a plan, once / staggered / perennial. lots.plan_crop_id ties each planned lot to it.
- plan_sowings go away: each becomes a plan crop (same id). A pending one becomes a planned lot (status `planned`,
  in its zone) with a "Sembrar" task on its date (its "Sembrar" reminder is dropped: the task replaces it); a sown
  one points its lot at the plan crop. reminders.sowing_id goes too.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-10-20 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f9a0b1c2d3e4'
down_revision: Union[str, None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('crop_plans', sa.Column('objectives', sa.Text(), nullable=True))
    op.create_table(
        'plan_zones',
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('zone_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['crop_plans.id'], name='fk_plan_zones_plan_id_crop_plans',
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['zone_id'], ['field_zones.id'], name='fk_plan_zones_zone_id_field_zones',
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('plan_id', 'zone_id', name='pk_plan_zones'),
    )
    op.execute(
        "INSERT INTO plan_zones (plan_id, zone_id) SELECT id, zone_id FROM crop_plans "
        "WHERE zone_id IS NOT NULL AND kind = 'largo'"
    )
    op.create_table(
        'plan_crops',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('crop_master_id', sa.UUID(), nullable=False),
        sa.Column('mode', sa.String(length=10), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('every_days', sa.Integer(), nullable=True),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=True),
        sa.Column('unit', sa.String(length=30), nullable=True),
        sa.Column('zone_ids', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('seed_lot_id', sa.UUID(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('single', 'staggered', 'perennial')", name=op.f('ck_plan_crops_mode_valid')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name='fk_plan_crops_account_id_accounts',
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plan_id'], ['crop_plans.id'], name='fk_plan_crops_plan_id_crop_plans',
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['crop_master_id'], ['crop_masters.id'],
                                name='fk_plan_crops_crop_master_id_crop_masters', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['seed_lot_id'], ['seed_lots.id'], name='fk_plan_crops_seed_lot_id_seed_lots',
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name='pk_plan_crops'),
    )
    op.create_index('ix_plan_crops_plan_id', 'plan_crops', ['plan_id'])
    op.add_column('lots', sa.Column('plan_crop_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_lots_plan_crop_id_plan_crops', 'lots', 'plan_crops', ['plan_crop_id'], ['id'], ondelete='SET NULL'
    )

    # Every planned sowing (not cancelled) becomes a crop of its plan, keeping its id.
    op.execute(
        "INSERT INTO plan_crops (id, account_id, plan_id, crop_master_id, mode, start_date, count, quantity, unit, "
        "zone_ids, seed_lot_id, notes, created_at) "
        "SELECT s.id, s.account_id, s.plan_id, s.crop_master_id, 'single', s.sow_date, 1, s.quantity, s.unit, "
        "CASE WHEN s.zone_id IS NULL THEN '[]'::jsonb ELSE jsonb_build_array(s.zone_id::text) END, s.seed_lot_id, "
        "s.notes, s.created_at FROM plan_sowings s WHERE s.status <> 'cancelado'"
    )
    # Sown: its lot belongs to the plan crop.
    op.execute(
        "UPDATE lots l SET plan_crop_id = s.id, plan_id = s.plan_id FROM plan_sowings s "
        "WHERE s.lot_id = l.id AND s.status = 'sembrado'"
    )
    # Pending: a planned lot (when the plan or the zone gives a field) with its sowing task.
    op.execute("""
        CREATE TEMPORARY TABLE sowing_lots ON COMMIT DROP AS
        SELECT s.id AS sowing_id, gen_random_uuid() AS lot_id, s.account_id, coalesce(p.field_id, z.field_id)
               AS field_id, s.plan_id, s.crop_master_id, s.zone_id, s.sow_date, s.quantity, s.unit,
               p.name AS plan_name, p.created_by, cm.name AS crop_name, cm.variety
        FROM plan_sowings s JOIN crop_plans p ON p.id = s.plan_id
        LEFT JOIN field_zones z ON z.id = s.zone_id JOIN crop_masters cm ON cm.id = s.crop_master_id
        WHERE s.status = 'pendiente' AND coalesce(p.field_id, z.field_id) IS NOT NULL
    """)
    op.execute(
        "INSERT INTO lots (id, account_id, field_id, crop_master_id, status, planting_date, quantity, unit, plan_id, "
        "plan_crop_id, notes, created_by, created_at, updated_at) "
        "SELECT lot_id, account_id, field_id, crop_master_id, 'planned', sow_date, quantity, unit, plan_id, "
        "sowing_id, 'Plan «' || plan_name || '»', created_by, now(), now() FROM sowing_lots"
    )
    op.execute(
        "INSERT INTO lot_zones (lot_id, zone_id, position) SELECT lot_id, zone_id, 0 FROM sowing_lots "
        "WHERE zone_id IS NOT NULL"
    )
    op.execute(
        "INSERT INTO tasks (id, account_id, field_id, zone_id, lot_id, plan_id, title, description, due_date, status, "
        "result_event_type, source, created_by, created_at, updated_at) "
        "SELECT gen_random_uuid(), account_id, field_id, zone_id, lot_id, plan_id, "
        "'Sembrar ' || crop_name || coalesce(' ' || variety, ''), 'Siembra planificada en «' || plan_name || '».', "
        "sow_date, 'pendiente', 'sowing', 'plan', created_by, now(), now() FROM sowing_lots"
    )
    op.execute("DELETE FROM reminders WHERE sowing_id IS NOT NULL AND status = 'activo'")
    op.drop_constraint('fk_reminders_sowing_id_plan_sowings', 'reminders', type_='foreignkey')
    op.drop_column('reminders', 'sowing_id')
    op.drop_index('ix_plan_sowings_plan_id', table_name='plan_sowings')
    op.drop_table('plan_sowings')


def downgrade() -> None:
    op.create_table(
        'plan_sowings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('crop_master_id', sa.UUID(), nullable=False),
        sa.Column('zone_id', sa.UUID(), nullable=True),
        sa.Column('sow_date', sa.Date(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=True),
        sa.Column('unit', sa.String(length=30), nullable=True),
        sa.Column('seed_lot_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('lot_id', sa.UUID(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pendiente', 'sembrado', 'cancelado')",
                           name=op.f('ck_plan_sowings_sowing_status_valid')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name='fk_plan_sowings_account_id_accounts',
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['crop_master_id'], ['crop_masters.id'],
                                name='fk_plan_sowings_crop_master_id_crop_masters', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['lot_id'], ['lots.id'], name='fk_plan_sowings_lot_id_lots', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['plan_id'], ['crop_plans.id'], name='fk_plan_sowings_plan_id_crop_plans',
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['seed_lot_id'], ['seed_lots.id'], name='fk_plan_sowings_seed_lot_id_seed_lots',
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['zone_id'], ['field_zones.id'], name='fk_plan_sowings_zone_id_field_zones',
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name='pk_plan_sowings'),
    )
    op.create_index('ix_plan_sowings_plan_id', 'plan_sowings', ['plan_id'])
    # One sowing per lot a plan crop planned: still planned = pending, else sown (with its lot).
    op.execute(
        "INSERT INTO plan_sowings (id, account_id, plan_id, crop_master_id, zone_id, sow_date, quantity, unit, "
        "seed_lot_id, status, lot_id, notes, created_at, updated_at) "
        "SELECT l.id, l.account_id, pc.plan_id, l.crop_master_id, "
        "(SELECT zone_id FROM lot_zones lz WHERE lz.lot_id = l.id ORDER BY position LIMIT 1), "
        "coalesce(l.planting_date, pc.start_date), l.quantity, l.unit, pc.seed_lot_id, "
        "CASE WHEN l.status = 'planned' THEN 'pendiente' ELSE 'sembrado' END, "
        "CASE WHEN l.status = 'planned' THEN NULL ELSE l.id END, pc.notes, now(), now() "
        "FROM lots l JOIN plan_crops pc ON pc.id = l.plan_crop_id WHERE l.deleted_at IS NULL"
    )
    op.execute("DELETE FROM tasks WHERE source = 'plan' AND result_event_type = 'sowing' AND lot_id IN "
               "(SELECT id FROM lots WHERE status = 'planned' AND plan_crop_id IS NOT NULL)")
    op.execute("DELETE FROM lots WHERE status = 'planned' AND plan_crop_id IS NOT NULL")
    op.add_column('reminders', sa.Column('sowing_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_reminders_sowing_id_plan_sowings', 'reminders', 'plan_sowings', ['sowing_id'], ['id'], ondelete='CASCADE'
    )
    op.drop_constraint('fk_lots_plan_crop_id_plan_crops', 'lots', type_='foreignkey')
    op.drop_column('lots', 'plan_crop_id')
    op.drop_index('ix_plan_crops_plan_id', table_name='plan_crops')
    op.drop_table('plan_crops')
    op.drop_table('plan_zones')
    op.drop_column('crop_plans', 'objectives')
