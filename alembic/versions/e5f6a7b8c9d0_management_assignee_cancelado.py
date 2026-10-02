"""management: assigned_to on shopping/roadmap items, "cancelado" status, budget_entries.updated_at

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-02 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ('shopping_list_items', 'roadmap_items'):
        op.add_column(table, sa.Column('assigned_to', postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            op.f(f'fk_{table}_assigned_to_users'), table, 'users', ['assigned_to'], ['id'], ondelete='SET NULL'
        )
        op.create_index(op.f(f'ix_{table}_account_assigned'), table, ['account_id', 'assigned_to'])

    op.drop_constraint(op.f('ck_shopping_list_items_shopping_status_valid'), 'shopping_list_items', type_='check')
    op.create_check_constraint(
        op.f('ck_shopping_list_items_shopping_status_valid'), 'shopping_list_items',
        "status IN ('pendiente', 'comprado', 'cancelado')",
    )
    op.drop_constraint(op.f('ck_roadmap_items_roadmap_status_valid'), 'roadmap_items', type_='check')
    op.create_check_constraint(
        op.f('ck_roadmap_items_roadmap_status_valid'), 'roadmap_items',
        "status IN ('pendiente', 'en_curso', 'hecho', 'cancelado')",
    )

    op.add_column(
        'budget_entries',
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('budget_entries', 'updated_at')

    op.execute("UPDATE roadmap_items SET status = 'pendiente' WHERE status = 'cancelado'")
    op.drop_constraint(op.f('ck_roadmap_items_roadmap_status_valid'), 'roadmap_items', type_='check')
    op.create_check_constraint(
        op.f('ck_roadmap_items_roadmap_status_valid'), 'roadmap_items', "status IN ('pendiente', 'en_curso', 'hecho')"
    )
    op.execute("UPDATE shopping_list_items SET status = 'pendiente' WHERE status = 'cancelado'")
    op.drop_constraint(op.f('ck_shopping_list_items_shopping_status_valid'), 'shopping_list_items', type_='check')
    op.create_check_constraint(
        op.f('ck_shopping_list_items_shopping_status_valid'), 'shopping_list_items',
        "status IN ('pendiente', 'comprado')",
    )

    for table in ('shopping_list_items', 'roadmap_items'):
        op.drop_index(op.f(f'ix_{table}_account_assigned'), table_name=table)
        op.drop_constraint(op.f(f'fk_{table}_assigned_to_users'), table, type_='foreignkey')
        op.drop_column(table, 'assigned_to')
