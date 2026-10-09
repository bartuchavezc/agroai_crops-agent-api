"""users: Colombia (CO) joins the countries the product serves

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-10-09 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(op.f('ck_users_country_valid'), 'users', type_='check')
    op.create_check_constraint('country_valid', 'users', "country IN ('AR', 'MX', 'CO')")


def downgrade() -> None:
    op.execute("UPDATE users SET country = 'AR', timezone = 'America/Argentina/Buenos_Aires', locale = 'es-AR' "
               "WHERE country = 'CO'")
    op.drop_constraint(op.f('ck_users_country_valid'), 'users', type_='check')
    op.create_check_constraint('country_valid', 'users', "country IN ('AR', 'MX')")
