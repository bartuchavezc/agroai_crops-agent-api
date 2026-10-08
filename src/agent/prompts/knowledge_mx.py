"""
Agronomic knowledge for the system prompt, scoped to Mexico — the counterpart of `knowledge_ar.py`.

Same rule as there: only stable, qualitative, structural knowledge. No exact sowing dates, no per-state windows, no
yields or prices (they change, and the agent has better sources: `find_crop_in_catalog`, `get_forecast`,
`web_search` on the official sources). Horticulture and greenhouse modules are shared with Argentina (they are
practices, not geography); regions, vocabulary, authorities and the viticulture and grain modules are Mexican.

Written from general public knowledge of Mexican agriculture; it has not been reviewed by a Mexican agronomist yet,
and should be before it is relied on for regional claims.
"""
from typing import Optional

from src.auth.services.profile_calculator import ProfileType

from .knowledge_ar import (
    FAMILY_TO_MODULE as _AR_FAMILY_TO_MODULE,
)
from .knowledge_ar import (
    GREENHOUSE_MODULE,
    HORTICULTURE_MODULE,
    _GREENHOUSE_KEYWORDS,
)

GENERAL_AGRONOMY_MX = """## Agronomía general (México)

**Grandes regiones agrícolas** (marco cualitativo para razonar aun sin pronóstico cargado, p. ej. campos sin
coordenadas todavía):
- **Noroeste** (Sonora, Sinaloa, Baja California, Baja California Sur): clima árido y semiárido, agricultura de
  riego intensiva (hortalizas, trigo, maíz, frutales), ciclo fuerte de otoño-invierno, calor extremo en verano.
- **Norte y Altiplano** (Chihuahua, Durango, Zacatecas, Coahuila, San Luis Potosí, Aguascalientes): semiárido,
  gran amplitud térmica, heladas de otoño a primavera, agua escasa (pozos y presas); frijol, chile, forrajes,
  frutales de clima templado.
- **Bajío y Occidente** (Guanajuato, Querétaro, Jalisco, Michoacán): riego con pozos, hortalizas, berries, granos,
  agave; heladas ocasionales en las partes altas y abatimiento de acuíferos como restricción de fondo.
- **Centro** (Estado de México, Puebla, Hidalgo, Tlaxcala, Morelos, CDMX): clima templado de altura, lluvias de
  verano, heladas de invierno en zonas altas; mucha agricultura de temporal y pequeña propiedad (maíz, frijol,
  hortalizas, flores).
- **Sur y Sureste** (Oaxaca, Chiapas, Guerrero, Veracruz, Tabasco, Yucatán y península): trópico húmedo y
  subhúmedo, lluvias abundantes en verano, temporada de huracanes (aprox. junio a noviembre), calor y humedad
  que favorecen hongos y bacterias; café, cacao, frutales tropicales, caña, milpa.
Es un marco cualitativo, no un calendario: para fechas concretas del campo del usuario, preferir `get_forecast`
(si hay coordenadas) o `web_search`.

**Ciclos y modalidades**: el calendario agrícola oficial se organiza en ciclos Primavera-Verano y Otoño-Invierno,
y la producción se reporta como de **temporal** (depende de la lluvia) o de **riego**. Antes de dar fechas o
dosis de riego, saber cuál es el caso. La **milpa** (maíz, frijol y calabaza asociados) es un sistema tradicional
de policultivo que conviene respetar y no tratar como un "monocultivo mal hecho".

**Manejo integrado de plagas (MIP)**, el enfoque por defecto: monitoreo antes que aplicación, umbral de daño
antes de intervenir, alternativas de menor impacto primero (barreras físicas, control biológico y cultural,
biopreparados) y plaguicidas de síntesis como último recurso, solo productos registrados ante COFEPRIS para ese
cultivo y respetando la etiqueta — nunca dosis o productos fuera de eso. Ante cualquier duda sobre un producto,
verificar su registro con una fuente oficial.

**Suelo y fertilidad**: el compost y la composta casera, los abonos verdes (leguminosas), la rotación de
cultivos (no repetir la misma familia en el mismo sitio temporada tras temporada) y la asociación de cultivos
son la base de la fertilidad orgánica. En suelos calcáreos y de zonas áridas son frecuentes la salinidad y los pH
altos; en el trópico húmedo, la acidez y el lavado de nutrientes: pedir un análisis de suelo antes de dosis.

**Riego**: la frecuencia depende del cultivo, la etapa, el sustrato y el clima; mejor regar profundo y espaciado
que superficial y seguido. El riego por goteo es más eficiente y moja menos el follaje. En zonas con escasez de agua,
priorizar eficiencia (acolchado, goteo, riego en horas frescas).

**Léxico** del resto de la app, con equivalentes locales: cama o bordo (cantero), semillero o almácigo, trasplante,
aporque (acumular tierra en la base del tallo). Usa la palabra que use el usuario."""

VITICULTURE_MODULE_MX = """## Viticultura (México)

**Estados fenológicos** de la vid para ubicar la consulta: brotación (muy sensible a heladas tardías) → floración
(cuajado) → envero (la baya cambia de color y acumula azúcar) → maduración → cosecha (vendimia). La brotación es
la etapa más vulnerable a helada; del envero en adelante pesan las enfermedades que afectan al racimo.

**Enfermedades típicas**: mildiu (favorecido por lluvia y humedad), oídio (polvillo blanco; calor y humedad
moderada) y botrytis (podredumbre gris cerca de cosecha con racimos compactos y humedad). La poda que abre la
planta a la luz y el aire y el deshojado en la zona de racimos reducen el riesgo antes de cualquier tratamiento.

**Regiones de referencia**: Baja California (Valle de Guadalupe y alrededores, clima mediterráneo), Coahuila
(Valle de Parras), Querétaro, Zacatecas, Aguascalientes y Guanajuato; además hay uva de mesa en Sonora. Cada región
tiene su propio riesgo de helada tardía en brotación: consultar `get_forecast` para el campo puntual."""

EXTENSIVE_GRAINS_MODULE_MX = """## Cultivos extensivos / granos (México)

Pensado para maíz (incluye elote y maíz de grano), frijol, trigo, sorgo, cebada y avena, los más comunes en
cultivo extensivo en México.

**Densidad de siembra**: depende del cultivo, la variedad o híbrido, el sistema (temporal o riego) y la zona;
nunca asumir una densidad fija sin confirmarla (`web_search` o la ficha de la variedad).

**Plagas típicas**: gusano cogollero del maíz, gusano elotero, chicharritas y pulgones (vectores de virus), chinches
y gallina ciega (larvas de coleópteros que dañan raíces). El monitoreo periódico en campo es más efectivo que la
aplicación por calendario.

**Rotación y asociación**: alternar gramíneas (maíz, trigo) con leguminosas (frijol, soya) ayuda con plagas y
enfermedades de suelo y con la fertilidad; en milpa, la asociación maíz-frijol-calabaza ya cumple parte de esa
función.

**Fertilización NPK básica**: el nitrógeno impulsa el crecimiento vegetativo, el fósforo la raíz y floración temprana,
el potasio el llenado de grano y la resistencia al estrés; el análisis de suelo define las dosis, no un valor genérico.

**Punto de cosecha**: depende de la humedad del grano y del destino; el elote para consumo fresco se cosecha mucho
antes de la madurez fisiológica del grano seco."""

PROFILE_MODULES_MX: dict[ProfileType, list[str]] = {
    "guardian": [GENERAL_AGRONOMY_MX, HORTICULTURE_MODULE],
    "purist": [GENERAL_AGRONOMY_MX, HORTICULTURE_MODULE, GREENHOUSE_MODULE],
    "alchemist": [GENERAL_AGRONOMY_MX, GREENHOUSE_MODULE, VITICULTURE_MODULE_MX],
    "professional": [
        GENERAL_AGRONOMY_MX, HORTICULTURE_MODULE, GREENHOUSE_MODULE, VITICULTURE_MODULE_MX, EXTENSIVE_GRAINS_MODULE_MX,
    ],
}

# Same families as Argentina, with the Mexican module in place of the Argentine one.
FAMILY_TO_MODULE_MX: dict[str, str] = {
    family: {"Vitaceae": VITICULTURE_MODULE_MX, "Poaceae": EXTENSIVE_GRAINS_MODULE_MX}.get(family, module)
    for family, module in _AR_FAMILY_TO_MODULE.items()
}


def modules_for_account_mx(profile: Optional[ProfileType], crop_families: set[str], field_texts: list[str]) -> str:
    base = PROFILE_MODULES_MX.get(profile or "guardian", PROFILE_MODULES_MX["guardian"])
    extra = [FAMILY_TO_MODULE_MX.get(family, HORTICULTURE_MODULE) for family in crop_families]
    if any(any(kw in text.lower() for kw in _GREENHOUSE_KEYWORDS) for text in field_texts):
        extra.append(GREENHOUSE_MODULE)
    return "\n\n".join(dict.fromkeys((*base, *extra)))
