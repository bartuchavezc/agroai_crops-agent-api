"""users: country, timezone and locale (the agent's voice and local time); existing users stay in Argentina

Revision ID: d5e6f7a8b9c0
Revises: a1b2c3d4e5f6
Create Date: 2026-10-08 15:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('country', sa.String(length=2), server_default='AR', nullable=False))
    op.add_column(
        'users',
        sa.Column('timezone', sa.String(length=64), server_default='America/Argentina/Buenos_Aires', nullable=False),
    )
    op.add_column('users', sa.Column('locale', sa.String(length=10), server_default='es-AR', nullable=False))
    op.create_check_constraint(op.f('ck_users_country_valid'), 'users', "country IN ('AR', 'MX')")


def downgrade() -> None:
    op.drop_constraint(op.f('ck_users_country_valid'), 'users', type_='check')
    op.drop_column('users', 'locale')
    op.drop_column('users', 'timezone')
    op.drop_column('users', 'country')
