"""
Seeds the products reference tables (src/application/products/) from the CSVs in `src/scripts/seeds/products/`:
  - senasa_terapeutica_veg.csv          formulated phytosanitary products registered in Argentina (SENASA)
  - senasa_terapeutica_veg_act.csv      technical-grade active registrations (SENASA 'ST-A')
  - senasa_fertilizantes_enimiendas_otr.csv  fertilizers, amendments, stimulants, inoculants (SENASA)
  - hrac_herbicide_moa_2026.csv         HRAC herbicide mode-of-action master list (active -> MoA group)
  - omri_nop_2026.csv                   OMRI list (USDA NOP organic inputs), made by `parse_omri_pdf` from the PDF

    uv run python -m src.scripts.seed_products [--seeds-dir DIR]

Idempotent: every table is upserted on its natural key (country + registry number, ingredient name), so
re-running refreshes rows instead of duplicating them. Registrations that disappear from a newer CSV are NOT
deleted — replace the CSVs with the new export and re-run, then clean up by hand if a registry retires products.

Ingredient linking: an ingredient mentioned by SENASA is matched against the HRAC list by a punctuation-free key
(so "2,4 D" finds "2,4-D"); a SENASA name that isn't in HRAC becomes its own ingredient without mode of action.
Matching Spanish SENASA names to English HRAC/FRAC/IRAC names (e.g. CLETODIM -> clethodim) is not done here:
it needs a curated alias list (active_ingredient_aliases) — the table exists for it.
"""
import argparse
import asyncio
import csv
import logging
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from src.application.products.models import (
    ActiveIngredient,
    ActiveIngredientAlias,
    ActiveIngredientRegistration,
    FertilizerProduct,
    OrganicInput,
    PhytoProduct,
    PhytoProductIngredient,
    normalize_name,
)
from src.config.bootstrap import build_container
from src.shared.database import dispose_database_connections

logger = logging.getLogger("src.scripts.seed_products")

DEFAULT_SEEDS_DIR = Path(__file__).resolve().parent / "seeds" / "products"
COUNTRY = "AR"
BATCH = 1000

# "<NAME> <number>% [p/v|p/p]" separated by commas; the number may lack its leading zero (",64%" = 0.64%).
_COMPONENT = re.compile(
    r"\s*(?P<name>.+?)\s+(?P<num>\d+(?:[.,]\d+)?|[.,]\d+)\s*%\s*(?P<unit>p\s*/\s*[vp])?\s*(?:,\s*|$)", re.IGNORECASE
)


@dataclass
class Component:
    raw_name: str
    concentration: Decimal | None
    unit: str | None


def match_key(name: str) -> str:
    """Punctuation-free key used to match the same ingredient written differently ("2,4 D" / "2,4-D")."""
    return re.sub(r"[^A-Z0-9]", "", normalize_name(name))


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(("0" + text if text[:1] in ",." else text).replace(",", "."))
    except InvalidOperation:
        return None


def parse_composition(actives: str) -> list[Component]:
    """Splits "FLUDIOXONIL 2,5%, METALAXIL -M 1%" into components. A string that doesn't parse completely is kept
    whole as a single component without concentration (nothing is dropped or guessed)."""
    actives = (actives or "").strip()
    if not actives:
        return []
    components, pos = [], 0
    for m in _COMPONENT.finditer(actives):
        if m.start() != pos:
            break
        unit = re.sub(r"\s+", "", m.group("unit") or "").lower() or None
        components.append(Component(m.group("name").strip(), _decimal(m.group("num")), unit))
        pos = m.end()
    if pos != len(actives) or not components:
        return [Component(actives, None, None)]
    return components


def _read_csv(path: Path, delimiter: str = ";") -> list[dict[str, str]]:
    """SENASA exports (default): ';'-separated, UTF-8 BOM, a trailing empty column, quoted values."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        return [
            {(k or "").strip(): (v or "").strip() for k, v in row.items() if k and k.strip()} for row in reader
        ]


def _none(value: str | None) -> str | None:
    return value.strip() or None if value else None


def _chunks(rows: list, size: int = BATCH):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


class IngredientIndex:
    """name_norm -> id for ingredients, plus the punctuation-free key -> id used to link variants."""

    def __init__(self, existing: dict[str, tuple[uuid.UUID, str]]):
        self.by_name = {name: id_ for name, (id_, _) in existing.items()}
        self.by_key = {match_key(name): id_ for name, id_ in self.by_name.items()}
        self.new_rows: list[dict] = []
        self.new_aliases: list[dict] = []

    def resolve(self, raw_name: str, source: str) -> uuid.UUID | None:
        name = normalize_name(raw_name)
        if not name:
            return None
        if name in self.by_name:
            return self.by_name[name]
        key = match_key(name)
        if key and key in self.by_key:  # same ingredient, different punctuation: alias of the existing one
            self.new_aliases.append({"id": uuid.uuid4(), "ingredient_id": self.by_key[key], "alias": name})
            self.by_name[name] = self.by_key[key]
            return self.by_key[key]
        id_ = uuid.uuid4()
        self.new_rows.append({"id": id_, "name": name, "display_name": raw_name.strip(), "source": source})
        self.by_name[name] = id_
        if key:
            self.by_key[key] = id_
        return id_


async def _load_hrac(session, path: Path) -> int:
    rows = []
    for r in _read_csv(path, delimiter=","):
        name = normalize_name(r["active"])
        if not name:
            continue
        rows.append({
            "id": uuid.uuid4(), "name": name, "display_name": r["active"], "moa_scheme": "HRAC",
            "moa_code": _none(r["hrac_global"]), "moa_legacy_code": _none(r["hrac_legacy"]),
            "moa_group": _none(r["moa_group"]), "chemical_class": _none(r["chemical_class"]), "source": "hrac_2026",
        })
    for chunk in _chunks(rows):
        stmt = insert(ActiveIngredient).values(chunk)
        await session.execute(stmt.on_conflict_do_update(
            index_elements=["name"],
            set_={c: stmt.excluded[c] for c in (
                "display_name", "moa_scheme", "moa_code", "moa_legacy_code", "moa_group", "chemical_class", "source")},
        ))
    return len(rows)


async def _upsert_returning_ids(session, model, rows: list[dict], update_cols: tuple[str, ...]) -> dict[str, uuid.UUID]:
    """Upserts on (country, registry_number) and returns registry_number -> id."""
    ids: dict[str, uuid.UUID] = {}
    for chunk in _chunks(rows):
        stmt = insert(model).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint=f"uq_{model.__tablename__}_country_registry",
            set_={c: stmt.excluded[c] for c in update_cols},
        ).returning(model.registry_number, model.id)
        for registry_number, id_ in (await session.execute(stmt)).all():
            ids[registry_number] = id_
    return ids


async def _load_products(session, path: Path) -> tuple[dict[str, uuid.UUID], dict[str, list[Component]]]:
    source = "senasa_ar_terapeutica_veg"
    products, compositions = [], {}
    for r in _read_csv(path):
        number = r["N° registro"]
        if not number:
            continue
        products.append({
            "id": uuid.uuid4(), "country": COUNTRY, "registry_number": number, "brand": r["Marca"],
            "brand_norm": normalize_name(r["Marca"]), "company": _none(r["Empresa"]),
            "toxicity_band": _none(r["Banda tox"]), "source": source,
        })
        compositions[number] = parse_composition(r["Activos"])
    ids = await _upsert_returning_ids(
        session, PhytoProduct, products, ("brand", "brand_norm", "company", "toxicity_band", "source")
    )
    return ids, compositions


async def _replace_composition(
    session, ids: dict[str, uuid.UUID], compositions: dict[str, list[Component]], index: IngredientIndex
) -> tuple[int, int]:
    """Rebuilds the composition rows of every product so a re-run reflects the current CSV."""
    rows, unparsed = [], 0
    for number, components in compositions.items():
        for position, c in enumerate(components):
            unparsed += c.concentration is None
            rows.append({
                "id": uuid.uuid4(), "product_id": ids[number],
                "ingredient_id": index.resolve(c.raw_name, "senasa_ar_terapeutica_veg"),
                "raw_name": c.raw_name, "raw_name_norm": normalize_name(c.raw_name),
                "concentration": c.concentration, "concentration_unit": c.unit, "position": position,
            })
    await _flush_ingredients(session, index)  # ingredient rows must exist before the composition rows point at them
    for chunk in _chunks(list(ids.values())):
        await session.execute(delete(PhytoProductIngredient).where(PhytoProductIngredient.product_id.in_(chunk)))
    for chunk in _chunks(rows):
        await session.execute(insert(PhytoProductIngredient).values(chunk))
    return len(rows), unparsed


async def _flush_ingredients(session, index: IngredientIndex) -> None:
    for chunk in _chunks(index.new_rows):
        await session.execute(insert(ActiveIngredient).values(chunk).on_conflict_do_nothing(index_elements=["name"]))
    for chunk in _chunks(index.new_aliases):
        stmt = insert(ActiveIngredientAlias).values(chunk).on_conflict_do_nothing(index_elements=["alias"])
        await session.execute(stmt)
    index.new_rows, index.new_aliases = [], []


async def _load_technical(session, path: Path, index: IngredientIndex) -> int:
    source = "senasa_ar_terapeutica_veg_act"
    rows = []
    for r in _read_csv(path):
        if not r["N° registro"]:
            continue
        rows.append({
            "id": uuid.uuid4(), "country": COUNTRY, "registry_number": r["N° registro"], "company": _none(r["Empresa"]),
            "ingredient_id": index.resolve(r["Nombre"], source), "raw_name": r["Nombre"],
            "purity_percent": _decimal(r["Concentracion"]) if r["Concentracion"] else None,
            "origin_country": _none(r["Pais"]), "source": source,
        })
    await _flush_ingredients(session, index)
    await _upsert_returning_ids(
        session, ActiveIngredientRegistration, rows,
        ("company", "ingredient_id", "raw_name", "purity_percent", "origin_country", "source"),
    )
    return len(rows)


async def _load_fertilizers(session, path: Path) -> int:
    rows = []
    for r in _read_csv(path):
        if not r["Número de inscripción"]:
            continue
        rows.append({
            "id": uuid.uuid4(), "country": COUNTRY, "registry_number": r["Número de inscripción"],
            "cuve": _none(r["Cuve"]), "brand": r["Marca"], "brand_norm": normalize_name(r["Marca"]),
            "category": _none(r["Aptitud"]), "ownership": (_none(r["Es propio o referenciado"]) or "").lower() or None,
            "origin_country": _none(r["País"]), "company": _none(r["Empresa"]), "company_tax_id": _none(r["Cuit"]),
            "source": "senasa_ar_fertilizantes",
        })
    await _upsert_returning_ids(
        session, FertilizerProduct, rows,
        ("cuve", "brand", "brand_norm", "category", "ownership", "origin_country", "company", "company_tax_id",
         "source"),
    )
    return len(rows)


async def _load_omri(session, path: Path) -> int:
    rows = []
    for r in _read_csv(path, delimiter=","):
        if not r["omri_id"]:
            continue
        rows.append({
            "id": uuid.uuid4(), "omri_id": r["omri_id"], "name": r["name"], "name_norm": normalize_name(r["name"]),
            "scope": _none(r["scope"]), "category": _none(r["category"]), "company": r["company"],
            "company_country": _none(r["company_country"]), "company_website": _none(r["company_website"]),
            "restricted": r["restricted"] == "True", "restriction_note": _none(r["restriction_note"]),
            "source": "omri_nop_2026",
        })
    for chunk in _chunks(rows):
        stmt = insert(OrganicInput).values(chunk)
        await session.execute(stmt.on_conflict_do_update(
            index_elements=["omri_id"],
            set_={c: stmt.excluded[c] for c in (
                "name", "name_norm", "scope", "category", "company", "company_country", "company_website",
                "restricted", "restriction_note", "source")},
        ))
    return len(rows)


async def seed(session_factory, seeds_dir: Path) -> dict[str, int]:
    stats: dict[str, int] = {}
    async with session_factory() as session:
        stats["hrac_ingredients"] = await _load_hrac(session, seeds_dir / "hrac_herbicide_moa_2026.csv")
        rows = await session.execute(select(ActiveIngredient.name, ActiveIngredient.id, ActiveIngredient.display_name))
        existing = {name: (id_, display) for name, id_, display in rows.all()}
        index = IngredientIndex(existing)

        ids, compositions = await _load_products(session, seeds_dir / "senasa_terapeutica_veg.csv")
        stats["products"] = len(ids)
        stats["composition_rows"], stats["composition_unparsed"] = await _replace_composition(
            session, ids, compositions, index
        )
        stats["technical_registrations"] = await _load_technical(
            session, seeds_dir / "senasa_terapeutica_veg_act.csv", index
        )
        stats["fertilizers"] = await _load_fertilizers(session, seeds_dir / "senasa_fertilizantes_enimiendas_otr.csv")
        stats["organic_inputs"] = await _load_omri(session, seeds_dir / "omri_nop_2026.csv")
        stats["ingredients_total"] = len(index.by_name)
        await session.commit()
    return stats


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.scripts.seed_products")
    parser.add_argument("--seeds-dir", type=Path, default=DEFAULT_SEEDS_DIR)
    args = parser.parse_args()
    container = build_container()
    try:
        stats = await seed(container.db_session_factory(), args.seeds_dir)
        logger.info("Done: " + ", ".join(f"{k}={v}" for k, v in stats.items()))
    finally:
        await dispose_database_connections()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
