"""seed lots: seeds/grams units with thousand-seed weight, free tags

Revision ID: 4bb0b6149307
Revises: f7a8b9c0d1e2
Create Date: 2026-10-15 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4bb0b6149307'
down_revision: Union[str, Sequence[str], None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Reference grams per 1000 seeds for the global catalog (name, variety) -> g. Tubers/cloves are left out.
GLOBAL_TSW = [
    ("Tomate", "Redondo", 3.0), ("Tomate", "Cherry", 2.0), ("Pimiento", None, 6.0), ("Berenjena", None, 4.0),
    ("Lechuga", "Mantecosa", 1.0), ("Lechuga", "Crespa", 1.0), ("Rúcula", None, 2.0), ("Espinaca", None, 10.0),
    ("Acelga", None, 15.0), ("Remolacha", None, 15.0), ("Zanahoria", None, 1.2), ("Perejil", None, 1.5),
    ("Albahaca", None, 1.5), ("Cebolla", None, 3.5), ("Puerro", None, 2.8),
    ("Zapallito", "Redondo de tronco", 150.0), ("Zapallo", "Anco", 120.0), ("Pepino", None, 25.0),
    ("Melón", None, 30.0), ("Sandía", None, 60.0), ("Chaucha", None, 300.0), ("Arveja", None, 200.0),
    ("Haba", None, 1500.0), ("Maíz", "Dulce", 150.0), ("Brócoli", None, 3.5), ("Coliflor", None, 3.0),
    ("Repollo", None, 3.5), ("Rabanito", None, 10.0), ("Frutilla", None, 0.3),
]


def upgrade() -> None:
    op.add_column('crop_masters', sa.Column('thousand_seed_weight_g', sa.Float(), nullable=True))
    op.add_column('seed_lots', sa.Column('thousand_seed_weight_g', sa.Float(), nullable=True))
    op.add_column(
        'seed_lots',
        sa.Column('tags', postgresql.ARRAY(sa.String(length=50)), server_default='{}', nullable=False),
    )
    op.create_index('ix_seed_lots_tags', 'seed_lots', ['tags'], unique=False, postgresql_using='gin')

    conn = op.get_bind()
    for name, variety, tsw in GLOBAL_TSW:
        conn.execute(
            sa.text(
                "UPDATE crop_masters SET thousand_seed_weight_g = :tsw "
                "WHERE account_id IS NULL AND name = :name AND variety IS NOT DISTINCT FROM :variety"
            ),
            {"tsw": tsw, "name": name, "variety": variety},
        )
    # Free-text units become one of the two the app converts between; anything else is left as is.
    op.execute(
        "UPDATE seed_lots SET unit = 'gramos' "
        "WHERE lower(trim(trailing '.' from trim(unit))) IN ('g', 'gr', 'grs', 'gramo', 'gramos', 'grams', 'gram')"
    )
    op.execute(
        "UPDATE seed_lots SET unit = 'semillas' "
        "WHERE lower(trim(trailing '.' from trim(unit))) IN "
        "('semilla', 'semillas', 'seed', 'seeds', 'u', 'un', 'unidad', 'unidades')"
    )
    op.execute("UPDATE seed_lots SET acquired_date = created_at::date WHERE acquired_date IS NULL")


def downgrade() -> None:
    op.drop_index('ix_seed_lots_tags', table_name='seed_lots', postgresql_using='gin')
    op.drop_column('seed_lots', 'tags')
    op.drop_column('seed_lots', 'thousand_seed_weight_g')
    op.drop_column('crop_masters', 'thousand_seed_weight_g')
