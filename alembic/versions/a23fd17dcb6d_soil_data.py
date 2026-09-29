"""soil data (INTA reference tables + cached field soil_context)

Revision ID: a23fd17dcb6d
Revises: 4686d205a3d6
Create Date: 2026-09-29 11:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a23fd17dcb6d'
down_revision: Union[str, None] = '4686d205a3d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # Static reference data (loaded once by src/scripts/import_soil_data.py, never written by the app
    # itself) — INTA "Suelos de la República Argentina" 1:500.000 soil map units.
    op.execute(
        """
        CREATE TABLE soil_map_units (
            id INTEGER PRIMARY KEY,
            provincia TEXT,
            unit_symbol TEXT,
            unit_type TEXT,
            productivity_index DOUBLE PRECISION,
            dominant_percent DOUBLE PRECISION,
            "position" TEXT,
            soil_order TEXT,
            great_group TEXT,
            subgroup TEXT,
            texture_surface TEXT,
            texture_subsoil TEXT,
            drainage TEXT,
            depth_cm DOUBLE PRECISION,
            alkalinity TEXT,
            erosion_hydric TEXT,
            erosion_eolic TEXT,
            rockiness TEXT,
            floodability TEXT,
            geom geometry(MultiPolygon, 4326) NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_soil_map_units_geom ON soil_map_units USING GIST (geom)")

    # INTA national pH (0-30cm) raster, flattened to point samples at import time (see the import
    # script) — a coarse zone signal (~km-scale grid), not per-plant precision.
    op.execute(
        """
        CREATE TABLE soil_ph_points (
            id BIGSERIAL PRIMARY KEY,
            ph DOUBLE PRECISION NOT NULL,
            geom geometry(Point, 4326) NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_soil_ph_points_geom ON soil_ph_points USING GIST (geom)")

    op.add_column(
        'fields', sa.Column('soil_context', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('fields', 'soil_context')
    op.drop_index('ix_soil_ph_points_geom', table_name='soil_ph_points')
    op.drop_table('soil_ph_points')
    op.drop_index('ix_soil_map_units_geom', table_name='soil_map_units')
    op.drop_table('soil_map_units')
    # postgis extension left installed intentionally: dropping it is riskier than leaving an unused
    # extension, and future features may want it too.
