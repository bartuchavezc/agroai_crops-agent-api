"""soilgrids_grids and soilgrids_tiles: SoilGrids rasters stored as georeferenced tiles

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-10-08 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'soilgrids_grids',
        sa.Column('grid', sa.String(length=40), nullable=False),
        sa.Column('min_lon', sa.Float(), nullable=False),
        sa.Column('max_lat', sa.Float(), nullable=False),
        sa.Column('res_lon', sa.Float(), nullable=False),
        sa.Column('res_lat', sa.Float(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('tile_size', sa.Integer(), nullable=False),
        sa.Column('resolution_m', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('grid', name=op.f('pk_soilgrids_grids')),
    )
    op.create_table(
        'soilgrids_tiles',
        sa.Column('grid', sa.String(length=40), nullable=False),
        sa.Column('prop', sa.String(length=12), nullable=False),
        sa.Column('depth', sa.String(length=10), nullable=False),
        sa.Column('tx', sa.Integer(), nullable=False),
        sa.Column('ty', sa.Integer(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ['grid'], ['soilgrids_grids.grid'], name=op.f('fk_soilgrids_tiles_grid_soilgrids_grids'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('grid', 'prop', 'depth', 'tx', 'ty', name=op.f('pk_soilgrids_tiles')),
    )


def downgrade() -> None:
    op.drop_table('soilgrids_tiles')
    op.drop_table('soilgrids_grids')
