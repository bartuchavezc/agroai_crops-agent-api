"""merge satellite series and soilgrids/locale heads

Revision ID: f7a8b9c0d1e2
Revises: c9d0e1f2a3b4, e6f7a8b9c0d1
Create Date: 2026-10-08 12:00:00.000000

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, Sequence[str], None] = ('c9d0e1f2a3b4', 'e6f7a8b9c0d1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
