"""add notes to reports

Revision ID: 39f0beb6f10f
Revises: 4bb0b6149307
Create Date: 2026-10-16 10:02:37.130852
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '39f0beb6f10f'
down_revision: Union[str, None] = '4bb0b6149307'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reports', sa.Column('notes', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('reports', 'notes')
