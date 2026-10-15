"""Seed units: a lot is counted in seeds or weighed in grams. The thousand-seed weight (peso de mil
semillas, grams per 1000 seeds) converts between both: from the lot itself, else from its crop."""
from typing import Optional

from src.shared.utils.errors import InvalidInputError

SEEDS = "semillas"
GRAMS = "gramos"
SEED_UNITS = (SEEDS, GRAMS)

_ALIASES = {
    "g": GRAMS, "gr": GRAMS, "grs": GRAMS, "gramo": GRAMS, "gramos": GRAMS, "grams": GRAMS, "gram": GRAMS,
    "semilla": SEEDS, "semillas": SEEDS, "seeds": SEEDS, "seed": SEEDS, "u": SEEDS, "un": SEEDS,
    "unidad": SEEDS, "unidades": SEEDS,
}


class SeedWeightRequiredError(InvalidInputError):
    """Converting between seeds and grams needs the thousand-seed weight (grams per 1000 seeds)."""
    status_code = 422
    error_code = "seed_weight_required"


def normalize_unit(unit: Optional[str]) -> Optional[str]:
    """'gr', 'Gramos', 'u'… → 'gramos' / 'semillas'; None when it's neither (a legacy free-text unit)."""
    if unit is None:
        return None
    return _ALIASES.get(unit.strip().lower().rstrip("."))


def effective_tsw(lot_tsw: Optional[float], crop_tsw: Optional[float]) -> Optional[float]:
    for value in (lot_tsw, crop_tsw):
        if value is not None and value > 0:
            return value
    return None


def convert(amount: float, from_unit: str, to_unit: str, tsw: Optional[float]) -> float:
    """`amount` in `from_unit` expressed in `to_unit`. Same unit (or same legacy text) passes through."""
    src, dst = normalize_unit(from_unit) or from_unit, normalize_unit(to_unit) or to_unit
    if src == dst:
        return amount
    if src not in SEED_UNITS or dst not in SEED_UNITS:
        raise InvalidInputError(f"Cannot convert '{from_unit}' to '{to_unit}': use semillas or gramos.")
    if tsw is None:
        raise SeedWeightRequiredError()
    return amount * tsw / 1000 if src == SEEDS else amount / tsw * 1000


def equivalent(quantity: float, unit: str, tsw: Optional[float]) -> tuple[Optional[float], Optional[str]]:
    """The same stock in the other unit (12 g ≈ 4000 semillas), or (None, None) when it can't be known."""
    base = normalize_unit(unit)
    if base is None or tsw is None:
        return None, None
    other = GRAMS if base == SEEDS else SEEDS
    return convert(quantity, base, other, tsw), other


def as_seeds(quantity: float, unit: str, tsw: Optional[float]) -> Optional[float]:
    base = normalize_unit(unit)
    if base == SEEDS:
        return quantity
    if base == GRAMS and tsw is not None:
        return convert(quantity, GRAMS, SEEDS, tsw)
    return None


def normalize_tags(tags: Optional[list[str]]) -> list[str]:
    out: list[str] = []
    for tag in tags or []:
        t = " ".join(tag.strip().lower().split())[:50]
        if t and t not in out:
            out.append(t)
    return out
