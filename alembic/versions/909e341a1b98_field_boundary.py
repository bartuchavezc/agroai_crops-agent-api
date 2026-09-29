"""field boundary + satellite reading pixel_count

Revision ID: 909e341a1b98
Revises: a23fd17dcb6d
Create Date: 2026-09-29 12:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '909e341a1b98'
down_revision: Union[str, None] = 'a23fd17dcb6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('fields', sa.Column('boundary', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('zone_satellite_readings', sa.Column('pixel_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('zone_satellite_readings', 'pixel_count')
    op.drop_column('fields', 'boundary')
