"""Lookups in the products registry, returned as the formal text an application or a stock item copies.

Nothing downstream keeps a pointer to these rows: a registry is replaced by a newer export from time to time, and
what was applied must read the same years later. A match only says the product is REGISTERED in that country —
never that it is authorised for a crop (see PhytoProductUse)."""
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import FertilizerProduct, PhytoProduct, PhytoProductIngredient, normalize_name

RegistryKind = Literal["phyto", "fertilizer"]


class RegisteredProduct(BaseModel):
    kind: RegistryKind
    name: str
    registry_number: str
    company: Optional[str] = None
    active_ingredients: Optional[str] = None  # "PIRIMETANIL 40% p/v + ..."
    category: Optional[str] = None  # fertilizers: Fertilizante, Enmienda, Inoculante...
    toxicity_band: Optional[str] = None
    country: str
    source: str  # the registry it came from (senasa_...)


def _concentration(value: Optional[Decimal], unit: Optional[str]) -> str:
    if value is None:
        return ""
    number = f"{value.normalize():f}".replace(".", ",")
    return f" {number}%" + (f" {unit}" if unit else "")


class ProductRegistryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def search(
        self, query: str, country: str = "AR", kind: Optional[RegistryKind] = None, limit: int = 10
    ) -> list[RegisteredProduct]:
        """By brand (accents and case ignored, partial) or exact registry number."""
        text = normalize_name(query)
        if not text:
            return []
        like = f"%{text}%"
        limit = max(1, min(limit, 30))
        out: list[RegisteredProduct] = []
        async with self.session_factory() as session:
            if kind in (None, "phyto"):
                rows = (await session.execute(
                    select(PhytoProduct)
                    .where(PhytoProduct.country == country,
                           or_(PhytoProduct.brand_norm.ilike(like), PhytoProduct.registry_number == query.strip()))
                    .order_by(PhytoProduct.brand_norm)
                    .limit(limit)
                )).scalars().all()
                ingredients: dict = {}
                if rows:
                    for ing in (await session.execute(
                        select(PhytoProductIngredient)
                        .where(PhytoProductIngredient.product_id.in_([r.id for r in rows]))
                        .order_by(PhytoProductIngredient.position)
                    )).scalars():
                        ingredients.setdefault(ing.product_id, []).append(
                            ing.raw_name + _concentration(ing.concentration, ing.concentration_unit)
                        )
                out += [
                    RegisteredProduct(
                        kind="phyto", name=r.brand, registry_number=r.registry_number, company=r.company,
                        active_ingredients=" + ".join(ingredients.get(r.id, [])) or None,
                        toxicity_band=r.toxicity_band, country=r.country, source=r.source,
                    )
                    for r in rows
                ]
            if kind in (None, "fertilizer"):
                rows = (await session.execute(
                    select(FertilizerProduct)
                    .where(FertilizerProduct.country == country,
                           or_(FertilizerProduct.brand_norm.ilike(like),
                               FertilizerProduct.registry_number == query.strip()))
                    .order_by(FertilizerProduct.brand_norm)
                    .limit(limit)
                )).scalars().all()
                out += [
                    RegisteredProduct(
                        kind="fertilizer", name=r.brand, registry_number=r.registry_number, company=r.company,
                        category=r.category, country=r.country, source=r.source,
                    )
                    for r in rows
                ]
        # exact brand first, then the rest as the registry lists them
        out.sort(key=lambda p: (normalize_name(p.name) != text, not normalize_name(p.name).startswith(text)))
        return out[:limit]

    async def verify(self, name: str, registry_number: Optional[str], country: str = "AR") -> bool:
        """Whether a product written by hand matches a registry row (by number, else by exact brand)."""
        async with self.session_factory() as session:
            for model in (PhytoProduct, FertilizerProduct):
                cond = (model.registry_number == registry_number.strip()) if registry_number else (
                    model.brand_norm == normalize_name(name)
                )
                found = (await session.execute(
                    select(model.id).where(model.country == country, cond).limit(1)
                )).first()
                if found:
                    return True
        return False
