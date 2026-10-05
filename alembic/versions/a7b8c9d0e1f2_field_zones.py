"""field_zones (cajón / cantero / invernadero / hidroponía, numbered per field) and zone_id on crop cycles,
events and reports; zone tracking reports cover several cycles from several photos

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-05 13:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'field_zones',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('field_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('layout_object_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ('cajon', 'cantero', 'invernadero', 'hidroponia')", name=op.f('ck_field_zones_zone_type_valid')
        ),
        sa.CheckConstraint('number >= 1', name=op.f('ck_field_zones_zone_number_positive')),
        sa.ForeignKeyConstraint(
            ['account_id'], ['accounts.id'], name=op.f('fk_field_zones_account_id_accounts'), ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['field_id'], ['fields.id'], name=op.f('fk_field_zones_field_id_fields'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_field_zones')),
    )
    op.create_index(op.f('ix_field_zones_account_id'), 'field_zones', ['account_id'])
    op.create_index(op.f('ix_field_zones_field_id'), 'field_zones', ['field_id'])
    op.create_index(
        'uq_field_zones_field_type_number_active', 'field_zones', ['field_id', 'type', 'number'],
        unique=True, postgresql_where=sa.text('deleted_at IS NULL'),
    )

    for table in ('crop_cycles', 'field_events', 'reports'):
        op.add_column(table, sa.Column('zone_id', postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            op.f(f'fk_{table}_zone_id_field_zones'), table, 'field_zones', ['zone_id'], ['id'], ondelete='SET NULL'
        )
    op.create_index(op.f('ix_crop_cycles_zone_id'), 'crop_cycles', ['zone_id'])

    op.add_column(
        'reports',
        sa.Column('crop_cycle_ids', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    )
    op.add_column(
        'reports',
        sa.Column('image_identifiers', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('reports', 'image_identifiers')
    op.drop_column('reports', 'crop_cycle_ids')
    op.drop_index(op.f('ix_crop_cycles_zone_id'), table_name='crop_cycles')
    for table in ('crop_cycles', 'field_events', 'reports'):
        op.drop_constraint(op.f(f'fk_{table}_zone_id_field_zones'), table, type_='foreignkey')
        op.drop_column(table, 'zone_id')
    op.drop_index('uq_field_zones_field_type_number_active', table_name='field_zones')
    op.drop_index(op.f('ix_field_zones_field_id'), table_name='field_zones')
    op.drop_index(op.f('ix_field_zones_account_id'), table_name='field_zones')
    op.drop_table('field_zones')
