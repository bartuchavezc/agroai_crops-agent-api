"""field layout_objects (replaces obstacles) + drop orientation_degrees

Revision ID: b7c1d2e3f4a5
Revises: 909e341a1b98
Create Date: 2026-09-29 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b7c1d2e3f4a5'
down_revision: Union[str, None] = '909e341a1b98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Old obstacles were compass-octant rows with no position; there is no faithful way to turn them into
    # x/y meters, so they are dropped (pre-launch, a handful of test fields) rather than migrated.
    op.add_column('fields', sa.Column('layout_objects', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.drop_column('fields', 'obstacles')
    op.drop_column('fields', 'orientation_degrees')


def downgrade() -> None:
    op.add_column('fields', sa.Column('orientation_degrees', sa.Float(), nullable=True))
    op.add_column('fields', sa.Column('obstacles', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.drop_column('fields', 'layout_objects')
