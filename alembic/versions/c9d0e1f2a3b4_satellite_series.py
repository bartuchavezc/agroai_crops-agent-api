"""satellite: field_satellite_observations time series (S2 + S1), field_satellite_sync and copernicus_usage

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-08 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('field_satellite_observations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('field_id', sa.UUID(), nullable=False),
    sa.Column('observed_on', sa.Date(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('total_pixels', sa.Integer(), nullable=True),
    sa.Column('valid_pixels', sa.Integer(), nullable=True),
    sa.Column('valid_fraction', sa.Float(), nullable=True),
    sa.Column('ndvi_mean', sa.Float(), nullable=True),
    sa.Column('ndvi_std', sa.Float(), nullable=True),
    sa.Column('ndvi_min', sa.Float(), nullable=True),
    sa.Column('ndvi_max', sa.Float(), nullable=True),
    sa.Column('ndvi_p10', sa.Float(), nullable=True),
    sa.Column('ndvi_p50', sa.Float(), nullable=True),
    sa.Column('ndvi_p90', sa.Float(), nullable=True),
    sa.Column('ndre_mean', sa.Float(), nullable=True),
    sa.Column('ndre_std', sa.Float(), nullable=True),
    sa.Column('ndmi_mean', sa.Float(), nullable=True),
    sa.Column('ndmi_std', sa.Float(), nullable=True),
    sa.Column('evi_mean', sa.Float(), nullable=True),
    sa.Column('evi_std', sa.Float(), nullable=True),
    sa.Column('ndwi_mean', sa.Float(), nullable=True),
    sa.Column('vv_db_mean', sa.Float(), nullable=True),
    sa.Column('vh_db_mean', sa.Float(), nullable=True),
    sa.Column('vh_vv_db', sa.Float(), nullable=True),
    sa.Column('rvi_mean', sa.Float(), nullable=True),
    sa.Column('orbit_direction', sa.String(length=12), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_field_satellite_observations_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['field_id'], ['fields.id'], name=op.f('fk_field_satellite_observations_field_id_fields'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_field_satellite_observations')),
    sa.UniqueConstraint('field_id', 'observed_on', 'source', name='uq_field_satellite_observations_field_date_source')
    )
    op.create_index('ix_field_satellite_observations_field_source_date', 'field_satellite_observations', ['field_id', 'source', 'observed_on'], unique=False)
    op.create_table('field_satellite_sync',
    sa.Column('field_id', sa.UUID(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('geometry_hash', sa.String(length=16), nullable=False),
    sa.Column('history_from', sa.Date(), nullable=False),
    sa.Column('synced_to', sa.Date(), nullable=False),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_field_satellite_sync_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['field_id'], ['fields.id'], name=op.f('fk_field_satellite_sync_field_id_fields'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('field_id', 'source', name=op.f('pk_field_satellite_sync'))
    )
    op.create_table('copernicus_usage',
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('processing_units', sa.Float(), nullable=False),
    sa.Column('requests', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('month', 'kind', name=op.f('pk_copernicus_usage'))
    )


def downgrade() -> None:
    op.drop_table('copernicus_usage')
    op.drop_table('field_satellite_sync')
    op.drop_index('ix_field_satellite_observations_field_source_date', table_name='field_satellite_observations')
    op.drop_table('field_satellite_observations')
