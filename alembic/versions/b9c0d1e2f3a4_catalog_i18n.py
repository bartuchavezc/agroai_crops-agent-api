"""crop_masters.i18n / variety_i18n and seed_lots.variety_i18n: names by locale, with the neutral value as fallback

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-10-09 15:30:00.000000

"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The global catalog is named the Argentine way (the neutral value). Where Mexico or Colombia say it differently:
_NAMES = {
    "Tomate": {"es-MX": "Jitomate"},
    "Pimiento": {"es-MX": "Pimiento morrón", "es-CO": "Pimentón"},
    "Rúcula": {"es-MX": "Arúgula", "es-CO": "Rúgula"},
    "Zapallito": {"es-MX": "Calabacita", "es-CO": "Calabacín"},
    "Zapallo": {"es-MX": "Calabaza", "es-CO": "Ahuyama"},
    "Chaucha": {"es-MX": "Ejote", "es-CO": "Habichuela"},
    "Frutilla": {"es-MX": "Fresa", "es-CO": "Fresa"},
    "Arveja": {"es-MX": "Chícharo"},
    "Remolacha": {"es-MX": "Betabel"},
    "Repollo": {"es-MX": "Col"},
    "Rabanito": {"es-MX": "Rábano", "es-CO": "Rábano"},
}


def upgrade() -> None:
    empty = sa.text("'{}'::jsonb")
    op.add_column('crop_masters', sa.Column('i18n', postgresql.JSONB(astext_type=sa.Text()), server_default=empty,
                                            nullable=False))
    op.add_column('crop_masters', sa.Column('variety_i18n', postgresql.JSONB(astext_type=sa.Text()),
                                            server_default=empty, nullable=False))
    op.add_column('seed_lots', sa.Column('variety_i18n', postgresql.JSONB(astext_type=sa.Text()),
                                         server_default=empty, nullable=False))
    for name, names in _NAMES.items():
        op.execute(
            sa.text("UPDATE crop_masters SET i18n = CAST(:i18n AS jsonb) WHERE account_id IS NULL AND name = :name")
            .bindparams(i18n=json.dumps(names, ensure_ascii=False), name=name)
        )


def downgrade() -> None:
    op.drop_column('seed_lots', 'variety_i18n')
    op.drop_column('crop_masters', 'variety_i18n')
    op.drop_column('crop_masters', 'i18n')
