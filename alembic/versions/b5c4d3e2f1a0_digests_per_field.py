"""digests: one per field (digests.field_id; unique by account, field, kind and day)

Revision ID: b5c4d3e2f1a0
Revises: e8f1a2b3c4d5
Create Date: 2026-10-26 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b5c4d3e2f1a0'
down_revision: Union[str, None] = 'e8f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('digests', sa.Column('field_id', sa.UUID(), nullable=True))
    op.create_foreign_key('digests_field_id_fkey', 'digests', 'fields', ['field_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_digests_field_id'), 'digests', ['field_id'], unique=False)
    op.drop_constraint('uq_digests_account_kind_date', 'digests', type_='unique')
    op.create_unique_constraint(
        'uq_digests_field_kind_date', 'digests', ['account_id', 'field_id', 'kind', 'local_date']
    )


def downgrade() -> None:
    op.drop_constraint('uq_digests_field_kind_date', 'digests', type_='unique')
    op.execute("DELETE FROM digests WHERE field_id IS NOT NULL")
    op.create_unique_constraint('uq_digests_account_kind_date', 'digests', ['account_id', 'kind', 'local_date'])
    op.drop_index(op.f('ix_digests_field_id'), table_name='digests')
    op.drop_constraint('digests_field_id_fkey', 'digests', type_='foreignkey')
    op.drop_column('digests', 'field_id')
