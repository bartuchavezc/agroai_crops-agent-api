"""field_satellite_observations: why pixels were lost (cloud / shadow / unusable share per Sentinel-2 pass)

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-10-09 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column in ('cloud_fraction', 'shadow_fraction', 'nodata_fraction'):
        op.add_column('field_satellite_observations', sa.Column(column, sa.Float(), nullable=True))


def downgrade() -> None:
    for column in ('nodata_fraction', 'shadow_fraction', 'cloud_fraction'):
        op.drop_column('field_satellite_observations', column)
