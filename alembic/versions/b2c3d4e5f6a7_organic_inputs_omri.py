"""organic_inputs: OMRI-listed products (USDA NOP)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-08 12:33:41.440767
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('organic_inputs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('omri_id', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=1000), nullable=False),
    sa.Column('name_norm', sa.String(length=1000), nullable=False),
    sa.Column('scope', sa.String(length=40), nullable=True),
    sa.Column('category', sa.Text(), nullable=True),
    sa.Column('company', sa.String(length=255), nullable=False),
    sa.Column('company_country', sa.String(length=80), nullable=True),
    sa.Column('company_website', sa.String(length=255), nullable=True),
    sa.Column('restricted', sa.Boolean(), nullable=False),
    sa.Column('restriction_note', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organic_inputs')),
    sa.UniqueConstraint('omri_id', name=op.f('uq_organic_inputs_omri_id'))
    )
    op.create_index('ix_organic_inputs_category_trgm', 'organic_inputs', ['category'], unique=False, postgresql_using='gin', postgresql_ops={'category': 'gin_trgm_ops'})
    op.create_index('ix_organic_inputs_company_country', 'organic_inputs', ['company_country'], unique=False)
    op.create_index('ix_organic_inputs_name_norm_trgm', 'organic_inputs', ['name_norm'], unique=False, postgresql_using='gin', postgresql_ops={'name_norm': 'gin_trgm_ops'})
    op.create_index('ix_organic_inputs_scope', 'organic_inputs', ['scope'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_organic_inputs_scope', table_name='organic_inputs')
    op.drop_index('ix_organic_inputs_name_norm_trgm', table_name='organic_inputs', postgresql_using='gin', postgresql_ops={'name_norm': 'gin_trgm_ops'})
    op.drop_index('ix_organic_inputs_company_country', table_name='organic_inputs')
    op.drop_index('ix_organic_inputs_category_trgm', table_name='organic_inputs', postgresql_using='gin', postgresql_ops={'category': 'gin_trgm_ops'})
    op.drop_table('organic_inputs')
