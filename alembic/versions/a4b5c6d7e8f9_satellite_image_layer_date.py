"""satellite chips (our own copy of each pass's pixels) and the maps drawn from them

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-10-09 18:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'field_satellite_chips',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('field_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('observed_on', sa.Date(), nullable=False),
        sa.Column('geometry_hash', sa.String(length=16), nullable=False),
        sa.Column('min_lon', sa.Float(), nullable=False),
        sa.Column('min_lat', sa.Float(), nullable=False),
        sa.Column('max_lon', sa.Float(), nullable=False),
        sa.Column('max_lat', sa.Float(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['field_id'], ['fields.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('field_id', 'observed_on', name='uq_field_satellite_chips_field_date'),
    )
    op.create_index('ix_field_satellite_chips_field_date', 'field_satellite_chips', ['field_id', 'observed_on'])
    op.add_column('zone_satellite_readings', sa.Column('observed_on', sa.Date(), nullable=True))
    op.add_column('zone_satellite_readings', sa.Column('layer', sa.String(length=8), nullable=True))
    op.add_column('zone_satellite_readings', sa.Column('window_days', sa.Integer(), nullable=True))
    op.add_column('zone_satellite_readings', sa.Column('coverage', sa.Float(), nullable=True))
    op.add_column('zone_satellite_readings', sa.Column('passes_used', sa.Integer(), nullable=True))
    op.create_index('ix_zone_satellite_readings_field_image', 'zone_satellite_readings',
                    ['field_id', 'observed_on', 'layer', 'window_days'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_zone_satellite_readings_field_image', table_name='zone_satellite_readings')
    for column in ('passes_used', 'coverage', 'window_days', 'layer', 'observed_on'):
        op.drop_column('zone_satellite_readings', column)
    op.drop_index('ix_field_satellite_chips_field_date', table_name='field_satellite_chips')
    op.drop_table('field_satellite_chips')
