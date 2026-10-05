"""planning: crop_plans, plan_stages, plan_sowings and reminders; notifications of type "reminder"

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-05 13:48:02.125930
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('crop_plans',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('field_id', sa.UUID(), nullable=True),
    sa.Column('zone_id', sa.UUID(), nullable=True),
    sa.Column('crop_cycle_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("kind IN ('ciclo', 'largo')", name=op.f('ck_crop_plans_plan_kind_valid')),
    sa.CheckConstraint("source IN ('user', 'agent', 'plan')", name=op.f('ck_crop_plans_plan_source_valid')),
    sa.CheckConstraint("status IN ('borrador', 'activo', 'archivado')", name=op.f('ck_crop_plans_plan_status_valid')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_crop_plans_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_crop_plans_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], name=op.f('fk_crop_plans_crop_cycle_id_crop_cycles'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['field_id'], ['fields.id'], name=op.f('fk_crop_plans_field_id_fields'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['zone_id'], ['field_zones.id'], name=op.f('fk_crop_plans_zone_id_field_zones'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crop_plans'))
    )
    op.create_index('ix_crop_plans_account_status', 'crop_plans', ['account_id', 'status'], unique=False)
    op.create_index(op.f('ix_crop_plans_crop_cycle_id'), 'crop_plans', ['crop_cycle_id'], unique=False)
    op.create_table('plan_sowings',
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
    sa.Column('crop_cycle_id', sa.UUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pendiente', 'sembrado', 'cancelado')", name=op.f('ck_plan_sowings_sowing_status_valid')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_plan_sowings_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], name=op.f('fk_plan_sowings_crop_cycle_id_crop_cycles'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['crop_master_id'], ['crop_masters.id'], name=op.f('fk_plan_sowings_crop_master_id_crop_masters'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['plan_id'], ['crop_plans.id'], name=op.f('fk_plan_sowings_plan_id_crop_plans'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['seed_lot_id'], ['seed_lots.id'], name=op.f('fk_plan_sowings_seed_lot_id_seed_lots'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['zone_id'], ['field_zones.id'], name=op.f('fk_plan_sowings_zone_id_field_zones'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plan_sowings'))
    )
    op.create_index(op.f('ix_plan_sowings_plan_id'), 'plan_sowings', ['plan_id'], unique=False)
    op.create_table('plan_stages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('crop_master_id', sa.UUID(), nullable=True),
    sa.Column('crop_cycle_id', sa.UUID(), nullable=True),
    sa.Column('zone_id', sa.UUID(), nullable=True),
    sa.Column('stage', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("stage IN ('germinacion', 'plantin', 'traspaso', 'vegetativo', 'floracion', 'fructificacion', 'cosecha', 'establecimiento', 'poda', 'descanso', 'otro')", name=op.f('ck_plan_stages_stage_type_valid')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_plan_stages_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], name=op.f('fk_plan_stages_crop_cycle_id_crop_cycles'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['crop_master_id'], ['crop_masters.id'], name=op.f('fk_plan_stages_crop_master_id_crop_masters'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['plan_id'], ['crop_plans.id'], name=op.f('fk_plan_stages_plan_id_crop_plans'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['zone_id'], ['field_zones.id'], name=op.f('fk_plan_stages_zone_id_field_zones'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plan_stages'))
    )
    op.create_index(op.f('ix_plan_stages_plan_id'), 'plan_stages', ['plan_id'], unique=False)
    op.create_table('reminders',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('plan_id', sa.UUID(), nullable=True),
    sa.Column('stage_id', sa.UUID(), nullable=True),
    sa.Column('sowing_id', sa.UUID(), nullable=True),
    sa.Column('crop_cycle_id', sa.UUID(), nullable=True),
    sa.Column('field_id', sa.UUID(), nullable=True),
    sa.Column('zone_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recurrence', sa.String(length=15), nullable=False),
    sa.Column('interval_days', sa.Integer(), nullable=True),
    sa.Column('until', sa.Date(), nullable=True),
    sa.Column('assigned_to', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("recurrence IN ('none', 'daily', 'weekly', 'every_n_days')", name=op.f('ck_reminders_reminder_recurrence_valid')),
    sa.CheckConstraint("source IN ('user', 'agent', 'plan')", name=op.f('ck_reminders_reminder_source_valid')),
    sa.CheckConstraint("status IN ('pendiente', 'hecho', 'cancelado')", name=op.f('ck_reminders_reminder_status_valid')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_reminders_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], name=op.f('fk_reminders_assigned_to_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_reminders_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], name=op.f('fk_reminders_crop_cycle_id_crop_cycles'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['field_id'], ['fields.id'], name=op.f('fk_reminders_field_id_fields'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['plan_id'], ['crop_plans.id'], name=op.f('fk_reminders_plan_id_crop_plans'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sowing_id'], ['plan_sowings.id'], name=op.f('fk_reminders_sowing_id_plan_sowings'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stage_id'], ['plan_stages.id'], name=op.f('fk_reminders_stage_id_plan_stages'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['zone_id'], ['field_zones.id'], name=op.f('fk_reminders_zone_id_field_zones'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reminders'))
    )
    op.create_index('ix_reminders_account_due', 'reminders', ['account_id', 'due_at'], unique=False)
    op.create_index(op.f('ix_reminders_crop_cycle_id'), 'reminders', ['crop_cycle_id'], unique=False)
    op.create_index(op.f('ix_reminders_plan_id'), 'reminders', ['plan_id'], unique=False)
    op.create_index('ix_reminders_status_due', 'reminders', ['status', 'due_at'], unique=False)
    _notification_checks("('report_diagnosis', 'report_periodic', 'report_soil', 'event', 'reminder')", "('report', 'event', 'reminder')")


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE type = 'reminder' OR entity_type = 'reminder'")
    _notification_checks("('report_diagnosis', 'report_periodic', 'report_soil', 'event')", "('report', 'event')")
    op.drop_table('reminders')
    op.drop_table('plan_stages')
    op.drop_table('plan_sowings')
    op.drop_table('crop_plans')


def _notification_checks(types: str, entity_types: str) -> None:
    op.drop_constraint(op.f('ck_notifications_notification_type_valid'), 'notifications', type_='check')
    op.create_check_constraint(op.f('ck_notifications_notification_type_valid'), 'notifications', f"type IN {types}")
    op.drop_constraint(op.f('ck_notifications_notification_entity_type_valid'), 'notifications', type_='check')
    op.create_check_constraint(
        op.f('ck_notifications_notification_entity_type_valid'), 'notifications', f"entity_type IN {entity_types}"
    )
