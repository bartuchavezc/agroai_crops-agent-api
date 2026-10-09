"""zone_satellite_readings: which pass and layer a rendered map shows

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-10-09 18:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('zone_satellite_readings', sa.Column('observed_on', sa.Date(), nullable=True))
    op.add_column('zone_satellite_readings', sa.Column('layer', sa.String(length=8), nullable=True))
    op.create_index('ix_zone_satellite_readings_field_image', 'zone_satellite_readings',
                    ['field_id', 'observed_on', 'layer'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_zone_satellite_readings_field_image', table_name='zone_satellite_readings')
    op.drop_column('zone_satellite_readings', 'layer')
    op.drop_column('zone_satellite_readings', 'observed_on')
