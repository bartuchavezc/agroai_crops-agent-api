"""application records (versioned, auditable) and inputs in stock with their ledger

- applications + application_products: the cuaderno de aplicaciones; products copied as text, never a registry id.
- account_products: products the account used that the registry doesn't have.
- product_crop_intervals: withholding periods read on labels, per product and crop.
- supply_items + supply_movements: stock of inputs and its append-only ledger.
- lots.harvest_blocked_until: no harvest before this day (carencia in force).

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-10-23 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('account_products',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('name_norm', sa.String(length=255), nullable=False),
    sa.Column('registry_number', sa.String(length=40), nullable=True),
    sa.Column('company', sa.String(length=255), nullable=True),
    sa.Column('active_ingredients', sa.Text(), nullable=True),
    sa.Column('formulation', sa.String(length=60), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('phyto', 'fertilizer', 'amendment', 'substrate', 'biological', 'other')", name=op.f('ck_account_products_kind_valid')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_account_products_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_account_products_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_account_products')),
    sa.UniqueConstraint('account_id', 'name_norm', name='uq_account_products_name')
    )
    op.create_table('product_crop_intervals',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('product_norm', sa.String(length=255), nullable=False),
    sa.Column('crop_norm', sa.String(length=255), nullable=False),
    sa.Column('product_name', sa.String(length=255), nullable=False),
    sa.Column('crop_name', sa.String(length=255), nullable=False),
    sa.Column('preharvest_interval_days', sa.Integer(), nullable=True),
    sa.Column('reentry_interval_hours', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_product_crop_intervals_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_product_crop_intervals_updated_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_product_crop_intervals')),
    sa.UniqueConstraint('account_id', 'product_norm', 'crop_norm', name='uq_product_crop_intervals')
    )
    op.create_table('supply_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('registry_number', sa.String(length=40), nullable=True),
    sa.Column('company', sa.String(length=255), nullable=True),
    sa.Column('active_ingredients', sa.Text(), nullable=True),
    sa.Column('formulation', sa.String(length=60), nullable=True),
    sa.Column('registry_verified', sa.Boolean(), nullable=False),
    sa.Column('unit', sa.String(length=10), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('manufacturer_lot', sa.String(length=60), nullable=True),
    sa.Column('expiry_date', sa.Date(), nullable=True),
    sa.Column('location', sa.String(length=255), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("kind IN ('phyto', 'fertilizer', 'amendment', 'substrate', 'biological', 'other')", name=op.f('ck_supply_items_kind_valid')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_supply_items_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_supply_items_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_supply_items'))
    )
    op.create_index('ix_supply_items_account', 'supply_items', ['account_id', 'deleted_at'], unique=False)
    op.create_table('supply_movements',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('item_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('application_id', sa.UUID(), nullable=True),
    sa.Column('image_identifier', sa.String(length=255), nullable=True),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('receipt', 'consumption', 'adjustment')", name=op.f('ck_supply_movements_kind_valid')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_supply_movements_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['item_id'], ['supply_items.id'], name=op.f('fk_supply_movements_item_id_supply_items'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_supply_movements_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_supply_movements'))
    )
    op.create_index('ix_supply_movements_application', 'supply_movements', ['application_id'], unique=False)
    op.create_index('ix_supply_movements_item', 'supply_movements', ['item_id', 'occurred_at'], unique=False)
    op.create_table('applications',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('record_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('supersedes_id', sa.UUID(), nullable=True),
    sa.Column('correction_reason', sa.Text(), nullable=True),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('field_id', sa.UUID(), nullable=False),
    sa.Column('zone_id', sa.UUID(), nullable=True),
    sa.Column('lot_ids', postgresql.ARRAY(sa.UUID()), server_default='{}', nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('target', sa.Text(), nullable=True),
    sa.Column('method', sa.String(length=60), nullable=True),
    sa.Column('equipment', sa.String(length=255), nullable=True),
    sa.Column('area_m2', sa.Float(), nullable=True),
    sa.Column('water_volume_l', sa.Float(), nullable=True),
    sa.Column('operator_user_id', sa.UUID(), nullable=True),
    sa.Column('operator_name', sa.String(length=255), nullable=True),
    sa.Column('prescribed_by', sa.String(length=255), nullable=True),
    sa.Column('prescription_number', sa.String(length=60), nullable=True),
    sa.Column('harvest_release_date', sa.Date(), nullable=True),
    sa.Column('reentry_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('weather', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('transcript', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('field_event_id', sa.UUID(), nullable=True),
    sa.Column('recorded_by', sa.UUID(), nullable=True),
    sa.Column('confirmed_by', sa.UUID(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('phyto', 'fertilization', 'biological', 'other')", name=op.f('ck_applications_kind_valid')),
    sa.CheckConstraint("status IN ('draft', 'confirmed', 'voided')", name=op.f('ck_applications_status_valid')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_applications_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['confirmed_by'], ['users.id'], name=op.f('fk_applications_confirmed_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['field_event_id'], ['field_events.id'], name=op.f('fk_applications_field_event_id_field_events'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['field_id'], ['fields.id'], name=op.f('fk_applications_field_id_fields'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['operator_user_id'], ['users.id'], name=op.f('fk_applications_operator_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], name=op.f('fk_applications_recorded_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['supersedes_id'], ['applications.id'], name=op.f('fk_applications_supersedes_id_applications'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['zone_id'], ['field_zones.id'], name=op.f('fk_applications_zone_id_field_zones'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_applications')),
    sa.UniqueConstraint('record_id', 'version', name='uq_applications_record_version')
    )
    op.create_index('ix_applications_account_current', 'applications', ['account_id', 'is_current', 'applied_at'], unique=False)
    op.create_index('ix_applications_lots', 'applications', ['lot_ids'], unique=False, postgresql_using='gin')
    op.create_index('ix_applications_record', 'applications', ['record_id'], unique=False)
    op.create_table('application_products',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('registry_number', sa.String(length=40), nullable=True),
    sa.Column('company', sa.String(length=255), nullable=True),
    sa.Column('active_ingredients', sa.Text(), nullable=True),
    sa.Column('formulation', sa.String(length=60), nullable=True),
    sa.Column('registry_verified', sa.Boolean(), nullable=False),
    sa.Column('dose', sa.Float(), nullable=True),
    sa.Column('dose_unit', sa.String(length=30), nullable=True),
    sa.Column('total_quantity', sa.Float(), nullable=True),
    sa.Column('total_unit', sa.String(length=10), nullable=True),
    sa.Column('supply_item_id', sa.UUID(), nullable=True),
    sa.Column('preharvest_interval_days', sa.Integer(), nullable=True),
    sa.Column('reentry_interval_hours', sa.Integer(), nullable=True),
    sa.Column('interval_source', sa.String(length=10), nullable=False),
    sa.CheckConstraint("interval_source IN ('label', 'user', 'saved', 'none')", name=op.f('ck_application_products_interval_source_valid')),
    sa.CheckConstraint("kind IN ('phyto', 'fertilizer', 'amendment', 'substrate', 'biological', 'other')", name=op.f('ck_application_products_kind_valid')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_application_products_application_id_applications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supply_item_id'], ['supply_items.id'], name=op.f('fk_application_products_supply_item_id_supply_items'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_products'))
    )
    op.create_index('ix_application_products_application', 'application_products', ['application_id'], unique=False)
    op.add_column('lots', sa.Column('harvest_blocked_until', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('lots', 'harvest_blocked_until')
    op.drop_index('ix_application_products_application', table_name='application_products')
    op.drop_table('application_products')
    op.drop_index('ix_applications_record', table_name='applications')
    op.drop_index('ix_applications_lots', table_name='applications', postgresql_using='gin')
    op.drop_index('ix_applications_account_current', table_name='applications')
    op.drop_table('applications')
    op.drop_index('ix_supply_movements_item', table_name='supply_movements')
    op.drop_index('ix_supply_movements_application', table_name='supply_movements')
    op.drop_table('supply_movements')
    op.drop_index('ix_supply_items_account', table_name='supply_items')
    op.drop_table('supply_items')
    op.drop_table('product_crop_intervals')
    op.drop_table('account_products')
