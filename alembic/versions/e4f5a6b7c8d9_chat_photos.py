"""chat: up to 4 photos per message (conversation_messages.image_identifiers; image_identifier stays the first)

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-10-24 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'conversation_messages',
        sa.Column('image_identifiers', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    )
    op.execute(
        "UPDATE conversation_messages SET image_identifiers = jsonb_build_array(image_identifier) "
        "WHERE image_identifier IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column('conversation_messages', 'image_identifiers')
