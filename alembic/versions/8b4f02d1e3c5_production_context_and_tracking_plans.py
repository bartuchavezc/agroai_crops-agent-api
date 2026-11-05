"""production context (pots and open ground, watering, how a lot started) and the agent's tracking plans

Revision ID: 8b4f02d1e3c5
Revises: 7a3e91c0d2b4
Create Date: 2026-11-05 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '8b4f02d1e3c5'
down_revision: Union[str, None] = '7a3e91c0d2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TYPES = "('cajon', 'cantero', 'invernadero', 'hidroponia')"
NEW_TYPES = "('cajon', 'cantero', 'invernadero', 'hidroponia', 'maceta', 'tierra_directa')"
SOWING = "('directa', 'almacigo_trasplante', 'plantin_comprado', 'esqueje')"


def upgrade() -> None:
    op.drop_constraint(op.f('ck_field_zones_zone_type_valid'), 'field_zones', type_='check')
    op.create_check_constraint(op.f('ck_field_zones_zone_type_valid'), 'field_zones', f"type IN {NEW_TYPES}")
    op.add_column('fields', sa.Column('irrigation', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('field_zones', sa.Column('irrigation', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('lots', sa.Column('sowing_method', sa.String(length=24), nullable=True))
    op.create_check_constraint(op.f('ck_lots_sowing_method_valid'), 'lots', f"sowing_method IS NULL OR sowing_method IN {SOWING}")
    op.create_table(
        'lot_tracking_plans',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('lot_id', sa.UUID(), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('revisions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('last_observation_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lot_id'], ['lots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('lot_id', name='uq_lot_tracking_plans_lot'),
    )
    op.create_index(op.f('ix_lot_tracking_plans_account_id'), 'lot_tracking_plans', ['account_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_lot_tracking_plans_account_id'), table_name='lot_tracking_plans')
    op.drop_table('lot_tracking_plans')
    op.drop_constraint(op.f('ck_lots_sowing_method_valid'), 'lots', type_='check')
    op.drop_column('lots', 'sowing_method')
    op.drop_column('field_zones', 'irrigation')
    op.drop_column('fields', 'irrigation')
    op.execute("UPDATE field_zones SET type = 'cantero' WHERE type IN ('maceta', 'tierra_directa')")
    op.drop_constraint(op.f('ck_field_zones_zone_type_valid'), 'field_zones', type_='check')
    op.create_check_constraint(op.f('ck_field_zones_zone_type_valid'), 'field_zones', f"type IN {OLD_TYPES}")
