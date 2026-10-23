"""Units of an input in stock: volume (L, ml), weight (kg, g) or pieces (unidades). A dose's total is converted to
the stock's unit when both measure the same thing; across kinds (litres of a product counted in kg) there is no
safe conversion without the product's density, so the caller must say the amount in the stock's unit."""
from typing import Optional

from src.shared.utils.errors import InvalidInputError

# unit -> (dimension, factor to the dimension's base unit)
_UNITS = {
    "l": ("volume", 1.0), "ml": ("volume", 0.001), "cc": ("volume", 0.001), "cm3": ("volume", 0.001),
    "kg": ("weight", 1.0), "g": ("weight", 0.001), "t": ("weight", 1000.0),
    "unidad": ("count", 1.0),
}
_ALIASES = {
    "litro": "l", "litros": "l", "lt": "l", "lts": "l", "l.": "l",
    "mililitro": "ml", "mililitros": "ml", "cm³": "cm3",
    "kilo": "kg", "kilos": "kg", "kgs": "kg", "kilogramo": "kg", "kilogramos": "kg",
    "gramo": "g", "gramos": "g", "gr": "g", "grs": "g",
    "tonelada": "t", "toneladas": "t", "tn": "t",
    "unidades": "unidad", "u": "unidad", "un": "unidad", "bolsa": "unidad", "bolsas": "unidad",
    "envase": "unidad", "envases": "unidad", "bidon": "unidad", "bidones": "unidad",
}
SUPPLY_UNITS = ("l", "ml", "kg", "g", "unidad")


def normalize(unit: Optional[str]) -> Optional[str]:
    """'Litros' -> 'l', 'cc' -> 'ml'... None for a unit this module doesn't know."""
    if unit is None:
        return None
    key = unit.strip().lower()
    key = _ALIASES.get(key, key)
    if key in ("cc", "cm3"):
        return "ml"
    return key if key in _UNITS else None


def convert(amount: float, from_unit: str, to_unit: str) -> float:
    src, dst = normalize(from_unit), normalize(to_unit)
    if src is None or dst is None:
        raise InvalidInputError(f"Unknown unit: {from_unit if src is None else to_unit}. Use L, ml, kg, g or unidad.")
    if src == dst:
        return amount
    (dim_a, fa), (dim_b, fb) = _UNITS[src], _UNITS[dst]
    if dim_a != dim_b:
        raise InvalidInputError(
            f"Can't turn {from_unit} into {to_unit} without the product's density: give the amount in {to_unit}."
        )
    return amount * fa / fb
