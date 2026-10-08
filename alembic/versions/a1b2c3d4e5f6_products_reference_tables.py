"""products: phytosanitary products, active ingredients (with mode of action), authorised uses, technical-active registrations and fertilizer registrations

Revision ID: a1b2c3d4e5f6
Revises: b8c9d0e1f2a3
Create Date: 2026-10-08 11:20:51.505891
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('active_ingredients',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('moa_scheme', sa.String(length=5), nullable=True),
    sa.Column('moa_code', sa.String(length=10), nullable=True),
    sa.Column('moa_legacy_code', sa.String(length=10), nullable=True),
    sa.Column('moa_group', sa.String(length=255), nullable=True),
    sa.Column('chemical_class', sa.String(length=255), nullable=True),
    sa.Column('source', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("moa_scheme IS NULL OR moa_scheme IN ('HRAC', 'FRAC', 'IRAC')", name=op.f('ck_active_ingredients_moa_scheme_valid')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_active_ingredients')),
    sa.UniqueConstraint('name', name=op.f('uq_active_ingredients_name'))
    )
    op.create_index('ix_active_ingredients_name_trgm', 'active_ingredients', ['name'], unique=False, postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.create_table('fertilizer_products',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('registry_number', sa.String(length=40), nullable=False),
    sa.Column('cuve', sa.String(length=20), nullable=True),
    sa.Column('brand', sa.String(length=255), nullable=False),
    sa.Column('brand_norm', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=60), nullable=True),
    sa.Column('ownership', sa.String(length=20), nullable=True),
    sa.Column('origin_country', sa.String(length=80), nullable=True),
    sa.Column('company', sa.String(length=255), nullable=True),
    sa.Column('company_tax_id', sa.String(length=20), nullable=True),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fertilizer_products')),
    sa.UniqueConstraint('country', 'registry_number', name='uq_fertilizer_products_country_registry')
    )
    op.create_index('ix_fertilizer_products_brand_norm_trgm', 'fertilizer_products', ['brand_norm'], unique=False, postgresql_using='gin', postgresql_ops={'brand_norm': 'gin_trgm_ops'})
    op.create_index('ix_fertilizer_products_category', 'fertilizer_products', ['category'], unique=False)
    op.create_table('phyto_products',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('registry_number', sa.String(length=40), nullable=False),
    sa.Column('brand', sa.String(length=255), nullable=False),
    sa.Column('brand_norm', sa.String(length=255), nullable=False),
    sa.Column('company', sa.String(length=255), nullable=True),
    sa.Column('toxicity_band', sa.String(length=10), nullable=True),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_phyto_products')),
    sa.UniqueConstraint('country', 'registry_number', name='uq_phyto_products_country_registry')
    )
    op.create_index('ix_phyto_products_brand_norm_trgm', 'phyto_products', ['brand_norm'], unique=False, postgresql_using='gin', postgresql_ops={'brand_norm': 'gin_trgm_ops'})
    op.create_index('ix_phyto_products_toxicity_band', 'phyto_products', ['toxicity_band'], unique=False)
    op.create_table('active_ingredient_aliases',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('ingredient_id', sa.UUID(), nullable=False),
    sa.Column('alias', sa.String(length=255), nullable=False),
    sa.ForeignKeyConstraint(['ingredient_id'], ['active_ingredients.id'], name=op.f('fk_active_ingredient_aliases_ingredient_id_active_ingredients'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_active_ingredient_aliases')),
    sa.UniqueConstraint('alias', name=op.f('uq_active_ingredient_aliases_alias'))
    )
    op.create_index(op.f('ix_active_ingredient_aliases_ingredient_id'), 'active_ingredient_aliases', ['ingredient_id'], unique=False)
    op.create_table('active_ingredient_registrations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('registry_number', sa.String(length=40), nullable=False),
    sa.Column('company', sa.String(length=255), nullable=True),
    sa.Column('ingredient_id', sa.UUID(), nullable=True),
    sa.Column('raw_name', sa.String(length=255), nullable=False),
    sa.Column('purity_percent', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('origin_country', sa.String(length=80), nullable=True),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['ingredient_id'], ['active_ingredients.id'], name=op.f('fk_active_ingredient_registrations_ingredient_id_active_ingredients'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_active_ingredient_registrations')),
    sa.UniqueConstraint('country', 'registry_number', name='uq_active_ingredient_registrations_country_registry')
    )
    op.create_index('ix_active_ingredient_registrations_ingredient', 'active_ingredient_registrations', ['ingredient_id'], unique=False)
    op.create_table('phyto_product_ingredients',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('ingredient_id', sa.UUID(), nullable=True),
    sa.Column('raw_name', sa.String(length=255), nullable=False),
    sa.Column('raw_name_norm', sa.String(length=255), nullable=False),
    sa.Column('concentration', sa.Numeric(precision=9, scale=4), nullable=True),
    sa.Column('concentration_unit', sa.String(length=3), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.CheckConstraint("concentration_unit IS NULL OR concentration_unit IN ('p/v', 'p/p')", name=op.f('ck_phyto_product_ingredients_unit_valid')),
    sa.ForeignKeyConstraint(['ingredient_id'], ['active_ingredients.id'], name=op.f('fk_phyto_product_ingredients_ingredient_id_active_ingredients'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['product_id'], ['phyto_products.id'], name=op.f('fk_phyto_product_ingredients_product_id_phyto_products'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_phyto_product_ingredients'))
    )
    op.create_index('ix_phyto_product_ingredients_ingredient', 'phyto_product_ingredients', ['ingredient_id'], unique=False)
    op.create_index('ix_phyto_product_ingredients_product', 'phyto_product_ingredients', ['product_id'], unique=False)
    op.create_index('ix_phyto_product_ingredients_raw_name_norm_trgm', 'phyto_product_ingredients', ['raw_name_norm'], unique=False, postgresql_using='gin', postgresql_ops={'raw_name_norm': 'gin_trgm_ops'})
    op.create_table('phyto_product_uses',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('crop', sa.String(length=255), nullable=False),
    sa.Column('crop_norm', sa.String(length=255), nullable=False),
    sa.Column('crop_scientific_name', sa.String(length=255), nullable=True),
    sa.Column('pest', sa.String(length=255), nullable=True),
    sa.Column('pest_norm', sa.String(length=255), nullable=True),
    sa.Column('pest_eppo_code', sa.String(length=10), nullable=True),
    sa.Column('dose', sa.Text(), nullable=True),
    sa.Column('application_notes', sa.Text(), nullable=True),
    sa.Column('preharvest_interval_days', sa.Integer(), nullable=True),
    sa.Column('reentry_interval_hours', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['phyto_products.id'], name=op.f('fk_phyto_product_uses_product_id_phyto_products'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_phyto_product_uses'))
    )
    op.create_index('ix_phyto_product_uses_crop_norm_trgm', 'phyto_product_uses', ['crop_norm'], unique=False, postgresql_using='gin', postgresql_ops={'crop_norm': 'gin_trgm_ops'})
    op.create_index('ix_phyto_product_uses_pest_norm_trgm', 'phyto_product_uses', ['pest_norm'], unique=False, postgresql_using='gin', postgresql_ops={'pest_norm': 'gin_trgm_ops'})
    op.create_index('ix_phyto_product_uses_product', 'phyto_product_uses', ['product_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_phyto_product_uses_product', table_name='phyto_product_uses')
    op.drop_index('ix_phyto_product_uses_pest_norm_trgm', table_name='phyto_product_uses', postgresql_using='gin', postgresql_ops={'pest_norm': 'gin_trgm_ops'})
    op.drop_index('ix_phyto_product_uses_crop_norm_trgm', table_name='phyto_product_uses', postgresql_using='gin', postgresql_ops={'crop_norm': 'gin_trgm_ops'})
    op.drop_table('phyto_product_uses')
    op.drop_index('ix_phyto_product_ingredients_raw_name_norm_trgm', table_name='phyto_product_ingredients', postgresql_using='gin', postgresql_ops={'raw_name_norm': 'gin_trgm_ops'})
    op.drop_index('ix_phyto_product_ingredients_product', table_name='phyto_product_ingredients')
    op.drop_index('ix_phyto_product_ingredients_ingredient', table_name='phyto_product_ingredients')
    op.drop_table('phyto_product_ingredients')
    op.drop_index('ix_active_ingredient_registrations_ingredient', table_name='active_ingredient_registrations')
    op.drop_table('active_ingredient_registrations')
    op.drop_index(op.f('ix_active_ingredient_aliases_ingredient_id'), table_name='active_ingredient_aliases')
    op.drop_table('active_ingredient_aliases')
    op.drop_index('ix_phyto_products_toxicity_band', table_name='phyto_products')
    op.drop_index('ix_phyto_products_brand_norm_trgm', table_name='phyto_products', postgresql_using='gin', postgresql_ops={'brand_norm': 'gin_trgm_ops'})
    op.drop_table('phyto_products')
    op.drop_index('ix_fertilizer_products_category', table_name='fertilizer_products')
    op.drop_index('ix_fertilizer_products_brand_norm_trgm', table_name='fertilizer_products', postgresql_using='gin', postgresql_ops={'brand_norm': 'gin_trgm_ops'})
    op.drop_table('fertilizer_products')
    op.drop_index('ix_active_ingredients_name_trgm', table_name='active_ingredients', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.drop_table('active_ingredients')
