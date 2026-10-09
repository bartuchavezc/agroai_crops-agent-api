"""accounts.currency, budget_entries.currency, crop cycle economics and stable budget category keys

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-10-09 16:00:00.000000

"""
import unicodedata
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c0d1e2f3a4b5'
down_revision: Union[str, None] = 'b9c0d1e2f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The suggestions the web app has always offered (and their keys); anything else is left as typed.
_KEYS = {
    "insumos": "insumos", "semillas": "semillas", "herramientas": "herramientas", "mano de obra": "mano_de_obra",
    "riego": "riego", "transporte": "transporte", "flete": "transporte", "servicios": "servicios",
    "otros": "otros_gastos", "otros gastos": "otros_gastos", "venta": "venta_cosecha",
    "venta de cosecha": "venta_cosecha", "otros ingresos": "otros_ingresos",
}


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in folded if not unicodedata.combining(c))


def upgrade() -> None:
    op.add_column('accounts', sa.Column('currency', sa.String(length=3), server_default='ARS', nullable=False))
    op.add_column('budget_entries', sa.Column('currency', sa.String(length=3), nullable=True))
    op.add_column('crop_cycles', sa.Column('plant_count', sa.Integer(), nullable=True))
    op.add_column('crop_cycles', sa.Column('expected_yield_kg', sa.Float(), nullable=True))
    op.add_column('crop_cycles', sa.Column('expected_price', sa.Float(), nullable=True))
    # An account keeps its books in the money of its owner's country.
    op.execute(
        "UPDATE accounts a SET currency = CASE u.country WHEN 'MX' THEN 'MXN' WHEN 'CO' THEN 'COP' ELSE 'ARS' END "
        "FROM users u WHERE u.account_id = a.id AND u.role = 'owner'"
    )
    bind = op.get_bind()
    for (category,) in bind.execute(sa.text("SELECT DISTINCT category FROM budget_entries WHERE category IS NOT NULL")):
        key = _KEYS.get(_plain(category))
        if key and key != category:
            bind.execute(sa.text("UPDATE budget_entries SET category = :key WHERE category = :old"),
                         {"key": key, "old": category})


def downgrade() -> None:
    op.drop_column('crop_cycles', 'expected_price')
    op.drop_column('crop_cycles', 'expected_yield_kg')
    op.drop_column('crop_cycles', 'plant_count')
    op.drop_column('budget_entries', 'currency')
    op.drop_column('accounts', 'currency')
