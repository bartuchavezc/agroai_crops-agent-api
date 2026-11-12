"""crop thermal parameters (base and upper temperature, GDD to first harvest)

Revision ID: 9c5a13e2f4d6
Revises: 8b4f02d1e3c5
Create Date: 2026-11-05 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '9c5a13e2f4d6'
down_revision: Union[str, None] = '8b4f02d1e3c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('crop_masters', sa.Column('t_base_c', sa.Float(), nullable=True))
    op.add_column('crop_masters', sa.Column('t_upper_c', sa.Float(), nullable=True))
    op.add_column('crop_masters', sa.Column('gdd_to_maturity', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('crop_masters', 'gdd_to_maturity')
    op.drop_column('crop_masters', 't_upper_c')
    op.drop_column('crop_masters', 't_base_c')
