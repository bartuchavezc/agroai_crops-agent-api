"""
Products reference data: phytosanitary products registered by country, their active ingredients (with the
herbicide/fungicide/insecticide mode-of-action group when known), per-crop authorised uses, and
fertilizer / amendment / stimulant / inoculant registrations.

Global reference data (no account_id): loaded by `src.scripts.seed_products`, read by the agent through lookup
tools — never loaded wholesale into the prompt. Names are kept twice: as the registry writes them
(`brand`, `raw_name`) and normalized (`*_norm`: upper case, no accents, single spaces — see `normalize_name`),
which is what the trigram indexes search, so "tizon", "Tizón" and "TIZON" hit the same rows.

A row in `phyto_products` only says the product is REGISTERED in that country. Which crop/pest it is authorised
for lives in `phyto_product_uses` (empty until a registry that publishes it — e.g. COFEPRIS — is loaded):
never infer an authorised use from the product row alone.
"""
import re
import unicodedata
import uuid

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

MOA_SCHEMES = ("HRAC", "FRAC", "IRAC")  # herbicides | fungicides | insecticides/acaricides
CONCENTRATION_UNITS = ("p/v", "p/p")  # weight/volume | weight/weight


def normalize_name(value: str | None) -> str:
    """Upper case, accents stripped, whitespace collapsed — the form stored in `*_norm` columns."""
    if not value:
        return ""
    text = "".join(c for c in unicodedata.normalize("NFD", value.upper()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def _trgm(table: str, column: str) -> Index:
    return Index(f"ix_{table}_{column}_trgm", column, postgresql_using="gin", postgresql_ops={column: "gin_trgm_ops"})


class ActiveIngredient(Base):
    """One active substance. `moa_*` are filled from the HRAC/FRAC/IRAC lists where the name matches."""
    __tablename__ = "active_ingredients"
    __table_args__ = (
        CheckConstraint(f"moa_scheme IS NULL OR moa_scheme IN {MOA_SCHEMES}", name="moa_scheme_valid"),
        _trgm("active_ingredients", "name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)  # normalized
    display_name = Column(String(255), nullable=False)
    moa_scheme = Column(String(5))
    moa_code = Column(String(10))  # HRAC global number, e.g. "4" (auxin mimics)
    moa_legacy_code = Column(String(10))  # e.g. "O"
    moa_group = Column(String(255))  # "Auxin Mimics"
    chemical_class = Column(String(255))  # "Phenoxycarboxylates"
    source = Column(String(30), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class ActiveIngredientAlias(Base):
    """Other names for an ingredient (Spanish/English, spelling variants): `2,4 D`, `2,4-D`, `clethodim`..."""
    __tablename__ = "active_ingredient_aliases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingredient_id = Column(
        UUID(as_uuid=True), ForeignKey("active_ingredients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias = Column(String(255), nullable=False, unique=True)  # normalized


class PhytoProduct(Base):
    """A formulated phytosanitary product as registered in one country."""
    __tablename__ = "phyto_products"
    __table_args__ = (
        UniqueConstraint("country", "registry_number", name="uq_phyto_products_country_registry"),
        _trgm("phyto_products", "brand_norm"),
        Index("ix_phyto_products_toxicity_band", "toxicity_band"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country = Column(String(2), nullable=False)  # ISO 3166-1 alpha-2
    registry_number = Column(String(40), nullable=False)
    brand = Column(String(255), nullable=False)
    brand_norm = Column(String(255), nullable=False)
    company = Column(String(255))
    toxicity_band = Column(String(10))  # SENASA: Ia, Ib, II, III, IV, S/D
    source = Column(String(40), nullable=False)
    extra = Column(JSONB)  # source-specific fields with no column of their own
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class PhytoProductIngredient(Base):
    """Composition of a product: one row per active, as written in the registry."""
    __tablename__ = "phyto_product_ingredients"
    __table_args__ = (
        CheckConstraint(
            f"concentration_unit IS NULL OR concentration_unit IN {CONCENTRATION_UNITS}", name="unit_valid"
        ),
        Index("ix_phyto_product_ingredients_product", "product_id"),
        Index("ix_phyto_product_ingredients_ingredient", "ingredient_id"),
        _trgm("phyto_product_ingredients", "raw_name_norm"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("phyto_products.id", ondelete="CASCADE"), nullable=False)
    ingredient_id = Column(UUID(as_uuid=True), ForeignKey("active_ingredients.id", ondelete="SET NULL"))
    raw_name = Column(String(255), nullable=False)
    raw_name_norm = Column(String(255), nullable=False)
    concentration = Column(Numeric(9, 4))
    concentration_unit = Column(String(3))
    position = Column(Integer, nullable=False, default=0)


class PhytoProductUse(Base):
    """An authorised use of a product on a crop (and optionally against a pest). The only table that may back a
    statement like "X is authorised for crop Y". Empty until a registry that publishes uses is loaded."""
    __tablename__ = "phyto_product_uses"
    __table_args__ = (
        Index("ix_phyto_product_uses_product", "product_id"),
        _trgm("phyto_product_uses", "crop_norm"),
        _trgm("phyto_product_uses", "pest_norm"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("phyto_products.id", ondelete="CASCADE"), nullable=False)
    crop = Column(String(255), nullable=False)
    crop_norm = Column(String(255), nullable=False)
    crop_scientific_name = Column(String(255))  # join key to the crop dictionary (WCVP) when known
    pest = Column(String(255))
    pest_norm = Column(String(255))
    pest_eppo_code = Column(String(10))
    dose = Column(Text)
    application_notes = Column(Text)
    preharvest_interval_days = Column(Integer)
    reentry_interval_hours = Column(Integer)
    source = Column(String(40), nullable=False)


class ActiveIngredientRegistration(Base):
    """Technical-grade active registrations (SENASA 'ST-A'): who is authorised to produce/import which
    active at what purity, from which country."""
    __tablename__ = "active_ingredient_registrations"
    __table_args__ = (
        UniqueConstraint("country", "registry_number", name="uq_active_ingredient_registrations_country_registry"),
        Index("ix_active_ingredient_registrations_ingredient", "ingredient_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country = Column(String(2), nullable=False)
    registry_number = Column(String(40), nullable=False)
    company = Column(String(255))
    ingredient_id = Column(UUID(as_uuid=True), ForeignKey("active_ingredients.id", ondelete="SET NULL"))
    raw_name = Column(String(255), nullable=False)
    purity_percent = Column(Numeric(9, 4))
    origin_country = Column(String(80))
    source = Column(String(40), nullable=False)


class FertilizerProduct(Base):
    """Fertilizers, amendments, stimulants, inoculants, conditioners and substrates registered in a country."""
    __tablename__ = "fertilizer_products"
    __table_args__ = (
        UniqueConstraint("country", "registry_number", name="uq_fertilizer_products_country_registry"),
        _trgm("fertilizer_products", "brand_norm"),
        Index("ix_fertilizer_products_category", "category"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country = Column(String(2), nullable=False)
    registry_number = Column(String(40), nullable=False)
    cuve = Column(String(20))  # SENASA vendor/product code
    brand = Column(String(255), nullable=False)
    brand_norm = Column(String(255), nullable=False)
    category = Column(String(60))  # Fertilizante, Enmienda, Estimulante, Inoculante, Acondicionador...
    ownership = Column(String(20))  # propio | referenciado
    origin_country = Column(String(80))
    company = Column(String(255))
    company_tax_id = Column(String(20))
    source = Column(String(40), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
