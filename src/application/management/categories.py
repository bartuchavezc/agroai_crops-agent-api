"""Budget categories with a stable key and a label per locale.

`BudgetEntry.category` is still a free string (clients may send their own), but the suggested ones are keys, so a
report can group entries across users of different countries. A free-text value that matches a key or a label
(ignoring case and accents) is stored as the key; anything else is kept as written."""
import unicodedata

# key -> (type it applies to, {locale: label}); the first label is the default for any locale not listed.
CATEGORIES: dict[str, tuple[str, dict[str, str]]] = {
    "insumos": ("gasto", {"es": "Insumos"}),
    "semillas": ("gasto", {"es": "Semillas"}),
    "herramientas": ("gasto", {"es": "Herramientas"}),
    "mano_de_obra": ("gasto", {"es": "Mano de obra", "es-MX": "Mano de obra"}),
    "riego": ("gasto", {"es": "Riego"}),
    "transporte": ("gasto", {"es": "Transporte", "es-AR": "Flete y transporte"}),
    "servicios": ("gasto", {"es": "Servicios"}),
    "otros_gastos": ("gasto", {"es": "Otros gastos"}),
    "venta_cosecha": ("ingreso", {"es": "Venta de cosecha"}),
    "otros_ingresos": ("ingreso", {"es": "Otros ingresos"}),
}


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in folded if not unicodedata.combining(c))


_BY_TEXT = {
    _plain(text): key
    for key, (_, labels) in CATEGORIES.items()
    for text in (key.replace("_", " "), key, *labels.values())
}


def label_for(key: str, locale: str | None) -> str:
    labels = CATEGORIES[key][1]
    return labels.get(locale or "") or labels["es"]


def normalize_category(value: str | None) -> str | None:
    """The key if `value` names a known category, else `value` unchanged."""
    if not value:
        return value
    return _BY_TEXT.get(_plain(value), value)


def catalog(locale: str | None) -> list[dict]:
    return [{"key": key, "label": label_for(key, locale), "type": kind} for key, (kind, _) in CATEGORIES.items()]
