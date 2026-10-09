"""
Agronomic knowledge for the system prompt, scoped to Colombia — the counterpart of `knowledge_mx.py`.

Same rule as there: only stable, qualitative, structural knowledge. No exact sowing dates, no per-department windows,
no yields or prices (they change, and the agent has better sources: `find_crop_in_catalog`, `get_forecast`,
`web_search` on the official sources). Horticulture and greenhouse modules are shared (they are practices, not
geography); regions, vocabulary and authorities are Colombian.

Written from general public knowledge of Colombian agriculture; it has not been reviewed by a Colombian agronomist
yet, and should be before it is relied on for regional claims.
"""
from typing import Optional

from src.auth.services.profile_calculator import ProfileType

from .knowledge_ar import GREENHOUSE_MODULE, HORTICULTURE_MODULE, _GREENHOUSE_KEYWORDS
from .knowledge_ar import FAMILY_TO_MODULE as _AR_FAMILY_TO_MODULE
from .knowledge_mx import EXTENSIVE_GRAINS_MODULE_MX

GENERAL_AGRONOMY_CO = """## Agronomía general (Colombia)

**Clima: el piso térmico manda, no la estación.** Colombia está en la zona ecuatorial: casi no hay estaciones de
temperatura, y lo que cambia el manejo es la altitud (piso térmico) y el régimen de lluvias:
- **Cálido** (hasta ~1.000 m): caña, plátano, arroz, yuca, cacao, frutales tropicales; calor y humedad que
  favorecen hongos y bacterias.
- **Templado** (~1.000 a 2.000 m): café, aguacate, cítricos, hortalizas de clima medio.
- **Frío** (~2.000 a 3.000 m): papa, hortalizas de clima frío, flores, pastos, fresa, mora; heladas posibles en las
  partes altas de madrugada.
- **Páramo** (más de ~3.000 m): muy frío y húmedo; solo cultivos adaptados y conservación del agua.
En muchas zonas las lluvias son **bimodales** (dos temporadas de lluvia y dos secas al año) y las siembras se
planifican con ellas. Los fenómenos **El Niño** (más seco) y **La Niña** (más lluvioso) alteran el año: conviene
revisar el pronóstico y el aviso del IDEAM.
**Las fichas de cultivo traen calendarios del hemisferio sur (Argentina): no aplican. Para fechas de siembra
confirma con el piso térmico del lote, el pronóstico y fuentes locales.**

**Regiones de referencia** (marco cualitativo): Andina (Cundinamarca, Boyacá, Antioquia, Eje Cafetero, Nariño:
papa, café, hortalizas, flores, frutales), Caribe (humedad y calor, banano, palma, arroz), Orinoquía (llanos,
arroz, palma, ganadería), Pacífico (muy lluvioso: cacao, plátano, coco) y Amazonía (conservación, sistemas
agroforestales).

**Manejo integrado de plagas (MIP)**, el enfoque por defecto: monitoreo antes que aplicación, umbral de daño
antes de intervenir, alternativas de menor impacto primero (barreras físicas, control biológico y cultural,
biopreparados) y plaguicidas de síntesis como último recurso, solo productos registrados ante el ICA para ese
cultivo y respetando la etiqueta — nunca dosis o productos fuera de eso. Ante cualquier duda sobre un producto,
verificar su registro con una fuente oficial.

**Suelo y fertilidad**: la composta, los abonos verdes, la rotación de cultivos y la asociación son la base de la
fertilidad orgánica. En el trópico húmedo y en suelos de ladera son frecuentes la acidez, el lavado de nutrientes y
la erosión (curvas de nivel, coberturas, barreras vivas); pedir análisis de suelo antes de definir enmiendas y dosis.

**Riego y agua**: la frecuencia depende del cultivo, la etapa, el sustrato y el clima; en temporada de lluvias el
riesgo suele ser el exceso de agua (drenaje) más que la falta. Mejor regar profundo y espaciado que superficial
y seguido.

**Léxico** del resto de la app, con equivalentes locales: finca, vereda, lote, era o cama (cantero), semillero o
almácigo, trasplante, aporque. Usa la palabra que use el usuario."""

PROFILE_MODULES_CO: dict[ProfileType, list[str]] = {
    "guardian": [GENERAL_AGRONOMY_CO, HORTICULTURE_MODULE],
    "purist": [GENERAL_AGRONOMY_CO, HORTICULTURE_MODULE, GREENHOUSE_MODULE],
    "alchemist": [GENERAL_AGRONOMY_CO, GREENHOUSE_MODULE],
    "professional": [GENERAL_AGRONOMY_CO, HORTICULTURE_MODULE, GREENHOUSE_MODULE, EXTENSIVE_GRAINS_MODULE_MX],
}

# Same families as Argentina, with the Mexican grains module (maize/bean) for grasses; vines have no Colombian module.
FAMILY_TO_MODULE_CO: dict[str, str] = {
    family: {"Poaceae": EXTENSIVE_GRAINS_MODULE_MX}.get(family, module)
    for family, module in _AR_FAMILY_TO_MODULE.items()
}


def modules_for_account_co(profile: Optional[ProfileType], crop_families: set[str], field_texts: list[str]) -> str:
    base = PROFILE_MODULES_CO.get(profile or "guardian", PROFILE_MODULES_CO["guardian"])
    extra = [FAMILY_TO_MODULE_CO.get(family, HORTICULTURE_MODULE) for family in crop_families]
    if any(any(kw in text.lower() for kw in _GREENHOUSE_KEYWORDS) for text in field_texts):
        extra.append(GREENHOUSE_MODULE)
    return "\n\n".join(dict.fromkeys((*base, *extra)))
