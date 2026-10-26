"""market: Red Km 0, the marketplace (its own schema) and the market_order notification

Revision ID: e8f1a2b3c4d5
Revises: c3e4a5b6d7f8
Create Date: 2026-10-24 19:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e8f1a2b3c4d5'
down_revision: Union[str, None] = 'c3e4a5b6d7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TYPES = "'report_diagnosis', 'report_periodic', 'report_soil', 'event', 'reminder', 'digest', 'nudge', 'application'"
OLD_ENTITIES = "'report', 'event', 'reminder', 'digest', 'conversation', 'application'"
TYPES = OLD_TYPES + ", 'market_order'"
ENTITIES = OLD_ENTITIES + ", 'market_order'"


def _notification_checks(types: str, entities: str) -> None:
    op.drop_constraint(op.f('ck_notifications_notification_type_valid'), 'notifications', type_='check')
    op.create_check_constraint(op.f('ck_notifications_notification_type_valid'), 'notifications', f"type IN ({types})")
    op.drop_constraint(op.f('ck_notifications_notification_entity_type_valid'), 'notifications', type_='check')
    op.create_check_constraint(
        op.f('ck_notifications_notification_entity_type_valid'), 'notifications', f"entity_type IN ({entities})"
    )


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS market")
    op.execute("CREATE SEQUENCE IF NOT EXISTS market.order_code_seq START WITH 2001")
    op.create_table('orders',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('code', sa.Integer(), server_default=sa.text("nextval('market.order_code_seq')"), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('buyer_name', sa.String(length=160), nullable=False),
    sa.Column('buyer_email', sa.String(length=254), nullable=False),
    sa.Column('buyer_phone', sa.String(length=40), nullable=True),
    sa.Column('buyer_kind', sa.String(length=20), nullable=False),
    sa.Column('delivery_address', sa.String(length=255), nullable=False),
    sa.Column('delivery_date', sa.Date(), nullable=False),
    sa.Column('recurring', sa.Boolean(), nullable=False),
    sa.Column('subtotal', sa.Float(), nullable=False),
    sa.Column('logistics_fee', sa.Float(), nullable=False),
    sa.Column('total', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("buyer_kind IN ('restaurante', 'verduleria', 'hotel', 'comedor', 'familia', 'otro')", name=op.f('ck_orders_buyer_kind_valid')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orders')),
    sa.UniqueConstraint('code', name=op.f('uq_orders_code')),
    schema='market'
    )
    op.create_index('ix_orders_buyer_email', 'orders', ['buyer_email'], unique=False, schema='market')
    op.create_table('pickup_routes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('route_date', sa.Date(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('driver_name', sa.String(length=120), nullable=False),
    sa.Column('hub_name', sa.String(length=120), nullable=True),
    sa.Column('hub_eta', sa.Time(), nullable=True),
    sa.Column('deliveries_from', sa.Time(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pickup_routes')),
    schema='market'
    )
    op.create_index(op.f('ix_market_pickup_routes_route_date'), 'pickup_routes', ['route_date'], unique=False, schema='market')
    op.create_table('producers',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('field_id', sa.UUID(), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('barrio', sa.String(length=120), nullable=True),
    sa.Column('plan', sa.String(length=10), server_default='free', nullable=False),
    sa.Column('seal_until', sa.Date(), nullable=True),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("plan IN ('free', 'pro')", name=op.f('ck_producers_plan_valid')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_producers_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['field_id'], ['fields.id'], name=op.f('fk_producers_field_id_fields'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_producers')),
    sa.UniqueConstraint('account_id', name=op.f('uq_producers_account_id')),
    schema='market'
    )
    op.create_table('listings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('producer_id', sa.UUID(), nullable=False),
    sa.Column('lot_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('price_per_kg', sa.Float(), nullable=False),
    sa.Column('weekly_capacity_kg', sa.Float(), nullable=False),
    sa.Column('weeks', sa.Integer(), nullable=False),
    sa.Column('stock_kg', sa.Float(), nullable=False),
    sa.Column('available_from', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("category IN ('hojas', 'frutos', 'aromaticas', 'raices', 'otros')", name=op.f('ck_listings_category_valid')),
    sa.CheckConstraint("status IN ('published', 'paused', 'closed')", name=op.f('ck_listings_status_valid')),
    sa.CheckConstraint('price_per_kg > 0', name=op.f('ck_listings_price_positive')),
    sa.CheckConstraint('stock_kg >= 0', name=op.f('ck_listings_stock_not_negative')),
    sa.CheckConstraint('weekly_capacity_kg > 0', name=op.f('ck_listings_capacity_positive')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_listings_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['lot_id'], ['lots.id'], name=op.f('fk_listings_lot_id_lots'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['producer_id'], ['market.producers.id'], name=op.f('fk_listings_producer_id_producers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_listings')),
    schema='market'
    )
    op.create_index('ix_listings_status', 'listings', ['status'], unique=False, schema='market')
    op.create_index(op.f('ix_market_listings_lot_id'), 'listings', ['lot_id'], unique=False, schema='market')
    op.create_index(op.f('ix_market_listings_producer_id'), 'listings', ['producer_id'], unique=False, schema='market')
    op.create_table('order_parts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('producer_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('pickup_date', sa.Date(), nullable=False),
    sa.Column('gross', sa.Float(), nullable=False),
    sa.Column('fee_rate', sa.Float(), nullable=False),
    sa.Column('fee', sa.Float(), nullable=False),
    sa.Column('net', sa.Float(), nullable=False),
    sa.Column('packed', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('reject_reason', sa.Text(), nullable=True),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ready_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('nuevo', 'prep', 'listo', 'entregado', 'rechazado')", name=op.f('ck_order_parts_status_valid')),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_order_parts_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['order_id'], ['market.orders.id'], name=op.f('fk_order_parts_order_id_orders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['producer_id'], ['market.producers.id'], name=op.f('fk_order_parts_producer_id_producers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_parts')),
    schema='market'
    )
    op.create_index(op.f('ix_market_order_parts_order_id'), 'order_parts', ['order_id'], unique=False, schema='market')
    op.create_index('ix_order_parts_account_status', 'order_parts', ['account_id', 'status'], unique=False, schema='market')
    op.create_table('pickup_stops',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('route_id', sa.UUID(), nullable=False),
    sa.Column('producer_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('eta', sa.Time(), nullable=False),
    sa.Column('picked_up_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['producer_id'], ['market.producers.id'], name=op.f('fk_pickup_stops_producer_id_producers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['route_id'], ['market.pickup_routes.id'], name=op.f('fk_pickup_stops_route_id_pickup_routes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pickup_stops')),
    schema='market'
    )
    op.create_index(op.f('ix_market_pickup_stops_producer_id'), 'pickup_stops', ['producer_id'], unique=False, schema='market')
    op.create_index(op.f('ix_market_pickup_stops_route_id'), 'pickup_stops', ['route_id'], unique=False, schema='market')
    op.create_table('order_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('part_id', sa.UUID(), nullable=False),
    sa.Column('listing_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('kg', sa.Float(), nullable=False),
    sa.Column('price_per_kg', sa.Float(), nullable=False),
    sa.Column('from_stock', sa.Boolean(), nullable=False),
    sa.CheckConstraint('kg > 0', name=op.f('ck_order_items_kg_positive')),
    sa.ForeignKeyConstraint(['listing_id'], ['market.listings.id'], name=op.f('fk_order_items_listing_id_listings'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['part_id'], ['market.order_parts.id'], name=op.f('fk_order_items_part_id_order_parts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_items')),
    schema='market'
    )
    op.create_index(op.f('ix_market_order_items_part_id'), 'order_items', ['part_id'], unique=False, schema='market')
    _notification_checks(TYPES, ENTITIES)


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE type = 'market_order' OR entity_type = 'market_order'")
    _notification_checks(OLD_TYPES, OLD_ENTITIES)
    for table in ('order_items', 'pickup_stops', 'order_parts', 'listings', 'producers', 'pickup_routes', 'orders'):
        op.drop_table(table, schema='market')
    op.execute("DROP SEQUENCE IF EXISTS market.order_code_seq")
    op.execute("DROP SCHEMA IF EXISTS market")
