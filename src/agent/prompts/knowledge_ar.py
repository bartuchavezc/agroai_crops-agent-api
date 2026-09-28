"""
Agronomic knowledge for the system prompt, scoped to Argentina, and behavior per onboarding profile.

Two separate concerns, kept apart on purpose:
  - "modules" are facts (regions, pests, practices) — adapted from public INTA material (Pro-Huerta
    calendario de siembra, biopreparados caseros, guía de identificación de plagas hortícolas,
    regiones agroecológicas). They never carry exact sowing dates or per-province windows — those change,
    and the agent already has better sources for that at hand: `find_crop_in_catalog`, `get_forecast`,
    `web_search`. Only stable, structural knowledge lives here.
  - "profile prompts" are style/behavior — how technical to be, how to treat risk, what to prioritize.

Module selection is direct-load (not RAG): the catalog is 5 fixed modules today, too small to justify
indexing. If the manual library grows into dozens of crop-specific documents, index them with pgvector
(already used for agent memory) and fetch by tool instead of always sending everything.
"""
import re
from typing import Optional

from src.auth.services.profile_calculator import ProfileType

GENERAL_AGRONOMY = """## Agronomía general (Argentina)

**Macro-regiones y su régimen de heladas/riego** (para razonar con criterio aun sin pronóstico SMN cargado,
p. ej. campos sin coordenadas todavía):
- **Región húmeda / pampeana** (Buenos Aires, sur de Santa Fe y Córdoba, Entre Ríos, La Pampa): clima
  templado, heladas invernales moderadas y regulares (mayo-septiembre aprox.), lluvias suficientes la mayor
  parte del año, riego complementario más que imprescindible.
- **NOA / NEA** (Salta, Jujuy, Tucumán, Santiago del Estero, Misiones, Corrientes, Formosa, Chaco): clima
  subtropical, ventana libre de heladas larga o nula en el norte, pero humedad y calor elevan el riesgo de
  hongos y bacterias; las lluvias suelen concentrarse en el semestre cálido.
- **Cuyo** (Mendoza, San Juan, San Luis): región árida/semiárida, amplitud térmica diaria alta, heladas
  tardías de primavera frecuentes, el riego (por lo general por surco o goteo) no es opcional.
- **Patagonia** (desde Río Negro/Neuquén hacia el sur): heladas prolongadas y tardías, ventana libre de
  heladas corta (a veces 2-3 meses en zona cordillerana), viento intenso — conviene priorizar cultivos de
  ciclo corto y protección física (túneles, media sombra como cortaviento).
Esto es un marco cualitativo, no un calendario: para fechas concretas de la zona del usuario, preferir
`get_forecast` (si el campo tiene coordenadas) o `web_search`.

**Manejo integrado de plagas (MIP)**, el enfoque que hay que priorizar siempre por default: monitoreo antes
que aplicación, umbral de daño económico/estético antes de intervenir, alternativas de menor impacto primero
(barreras físicas, control biológico/cultural, biopreparados) y agroquímicos de síntesis como último recurso
y dentro de etiqueta — nunca recomendar dosis o productos fuera de eso.

**Suelo y fertilidad**: el compost casero (restos de cocina + material seco, volteado periódico, 2-4 meses)
es la base de la fertilidad orgánica; los abonos verdes (leguminosas de cobertura) fijan nitrógeno y mejoran
estructura; la rotación de cultivos (no repetir la misma familia botánica en el mismo lugar temporada tras
temporada) corta ciclos de plagas y enfermedades del suelo; la asociación de cultivos (consociación) puede
repeler plagas o aprovechar mejor el espacio y la luz.

**Riego**: la frecuencia depende del cultivo, la etapa fenológica, el sustrato (arenoso drena y seca más
rápido que arcilloso) y el clima — mejor regar profundo y espaciado que superficial y seguido, para
favorecer raíces profundas. El riego por goteo es más eficiente que el riego manual/aspersión y moja menos
el follaje (menor riesgo fúngico).

**Léxico** que se usa en el resto de la app: cantero (bancal de cultivo), almácigo (semillero previo al
trasplante), repique (trasplante del almácigo a su lugar definitivo), aporque (acumular tierra en la base del
tallo, típico en papa/maíz)."""

HORTICULTURE_MODULE = """## Horticultura a campo abierto

**Plagas y enfermedades comunes en huerta familiar** y su manejo integrado (biopreparados típicos de
Pro-Huerta, de bajo impacto y accesibles):
- **Pulgón** (verde o negro): purín de ají picante, ajo y jabón potásico pulverizado sobre el follaje;
  favorecer enemigos naturales (vaquitas de San Antonio, sírfidos) evitando insecticidas de amplio espectro.
- **Mosca blanca**: trampas amarillas engomadas, purín de ajo/cebolla, buena ventilación entre plantas.
- **Oídio** (hongo blanco polvoriento en hojas): mejorar circulación de aire, evitar exceso de nitrógeno,
  bicarbonato de sodio diluido o leche diluida como preventivo casero.
- **Tizón** (manchas necróticas, típico en solanáceas con humedad): evitar mojar el follaje al regar, marco
  de plantación con buena aireación, rotación de cultivos.
- **Caracoles y babosas**: trampas de cerveza, ceniza o cáscara de huevo molida alrededor de la planta,
  recolección manual nocturna.
- **Hormigas**: suelen ser indicador de pulgón (las "cultivan" por la melaza) más que plaga directa sobre la
  hoja; controlar el pulgón primero.

**Rotación y asociación** en huerta: no repetir familia botánica en el mismo cantero (evitar solanácea tras
solanácea, por ejemplo); asociaciones clásicas como aromáticas (albahaca, romero) entre hortalizas para
repeler insectos, o leguminosas antes de un cultivo exigente en nitrógeno.

Para calendarios de siembra exactos de una hortaliza puntual, usar `find_crop_in_catalog` (trae
`planting_season`/`harvest_season` del catálogo) en vez de asumir fechas."""

GREENHOUSE_MODULE = """## Cultivo bajo cubierta (invernadero)

El factor de riesgo dominante bajo cubierta no es el frío sino la **humedad estancada**: sin buena
ventilación, la condensación sobre hojas y frutos dispara enfermedades fúngicas (botrytis, oídio, mildiu)
mucho más rápido que a campo abierto. Ventilar en las horas centrales del día, evitar riego por aspersión
que moje el follaje, y espaciar plantas para que circule el aire son las medidas de mayor impacto.

**Plagas que se agravan bajo cubierta** (menos enemigos naturales, clima estable todo el año): mosca blanca,
trips y ácaros (arañuela roja) son los más frecuentes — trampas cromáticas (amarillas para mosca blanca y
trips, azules para trips) como monitoreo temprano.

**Sustratos e hidroponía básica**: sustratos inertes (perlita, fibra de coco, lana de roca) permiten mejor
control de riego/nutrición que la tierra directa; en sistemas hidropónicos simples (NFT, raíz flotante) el pH
de la solución (idealmente 5.5-6.5 para la mayoría de las hortalizas) y la conductividad eléctrica (nutrición
disuelta) son los dos parámetros a monitorear con más frecuencia que en cultivo en suelo.

El plástico/cubierta también filtra luz y acumula calor: en días muy soleados de primavera-verano, revisar
que no se generen golpes de calor internos (ventilar o encalar/sombrear si hace falta)."""

VITICULTURE_MODULE = """## Viticultura

**Estados fenológicos** de la vid, útiles para ubicar en qué momento del ciclo está una consulta:
brotación (yemas abren, alta sensibilidad a heladas tardías) → floración (cuajado del fruto) → envero
(la baya cambia de color y empieza a acumular azúcar) → maduración → cosecha (vendimia). Cada estado tiene
riesgos distintos: la brotación es la más vulnerable a helada tardía, el envero en adelante a enfermedades
que afectan directamente el racimo.

**Enfermedades típicas**: peronóspora (mildiu de la vid, favorecida por lluvia y humedad, ataca hoja y
racimo), oídio de la vid (polvillo blanco, favorecido por calor y humedad moderada, distinto hongo que la
peronóspora aunque se confunden), botrytis (podredumbre gris, sobre todo cerca de cosecha con racimos
compactos y humedad). El manejo preventivo (poda que abra la planta a la luz y el aire, deshojado en la zona
de racimos) reduce mucho el riesgo antes de necesitar cualquier tratamiento.

**Conducción y poda**: los sistemas más comunes en Argentina son espaldero (alambrado vertical, más fácil de
mecanizar) y parral (horizontal, tradicional en mesa/consumo). La poda de invierno define la carga de yemas
del año siguiente — muy ligada al vigor de la planta y al rendimiento buscado.

**Regiones vitivinícolas** de referencia: Cuyo (Mendoza y San Juan, la de mayor superficie, clima árido de
altura con gran amplitud térmica), Salta (altura extrema, Valles Calchaquíes), Patagonia (Río Negro y
Neuquén, clima más fresco). Cada región tiene su perfil de riesgo de helada tardía en brotación distinto —
consultar `get_forecast` para el campo puntual."""

EXTENSIVE_GRAINS_MODULE = """## Cultivos extensivos / granos

Pensado para maíz (incluye choclo para consumo), soja, trigo y girasol — los más comunes en cultivo
extensivo en Argentina.

**Densidad de siembra**: depende del cultivo, el híbrido/variedad y la disponibilidad de agua/nutrientes de
la zona — nunca asumir una densidad fija sin confirmarla (`web_search` o la ficha del híbrido).

**Plagas típicas**: isoca (oruga defoliadora/cogollera, ataca varios cultivos), chicharrita del maíz (vector
de enfermedades, requiere monitoreo temprano y ha causado pérdidas importantes en campañas recientes en
Argentina), chinches (afectan llenado de grano en soja/girasol). El monitoreo periódico a campo (no solo
reactivo ante daño visible) es más efectivo que la aplicación calendario.

**Rotación de cultivos extensivos**: alternar gramíneas (maíz, trigo) con leguminosas (soja) ayuda a
manejar plagas/enfermedades de suelo específicas de cada familia y a la fertilidad (la soja fija nitrógeno,
el maíz lo consume).

**Fertilización NPK básica**: nitrógeno (N) impulsa crecimiento vegetativo, fósforo (P) es clave en
raíz/floración temprana, potasio (K) en llenado de grano y resistencia a estrés — el análisis de suelo previo
es lo que define dosis reales, no un valor genérico.

**Punto de cosecha**: se define por humedad de grano (distinta según el cultivo y el destino comercial vs.
consumo, como el choclo que se cosecha mucho antes, en estado "lechoso-pastoso", para consumo fresco). Para
choclo destinado a consumo familiar, el punto óptimo es antes de la madurez fisiológica plena del grano seco."""

# --- assignment ------------------------------------------------------------------------------------------

PROFILE_MODULES: dict[ProfileType, list[str]] = {
    "guardian": [GENERAL_AGRONOMY, HORTICULTURE_MODULE],
    "purist": [GENERAL_AGRONOMY, HORTICULTURE_MODULE, GREENHOUSE_MODULE],
    "alchemist": [GENERAL_AGRONOMY, GREENHOUSE_MODULE, VITICULTURE_MODULE],
    "professional": [
        GENERAL_AGRONOMY,
        HORTICULTURE_MODULE,
        GREENHOUSE_MODULE,
        VITICULTURE_MODULE,
        EXTENSIVE_GRAINS_MODULE,
    ],
}

# Botanical family (crop_masters.family) -> extra module to include, on top of the profile's default set,
# when the account actually grows something of that family. Anything not listed here defaults to
# HORTICULTURE_MODULE (covers the rest of the seeded catalog: Solanaceae, Cucurbitaceae, Brassicaceae, ...).
FAMILY_TO_MODULE: dict[str, str] = {
    "Vitaceae": VITICULTURE_MODULE,
    "Poaceae": EXTENSIVE_GRAINS_MODULE,
}

_GREENHOUSE_KEYWORDS = ("invernadero", "bajo cubierta", "greenhouse")

PROFILE_PROMPTS: dict[ProfileType, str] = {
    "guardian": """## Estilo: El Guardián
Tu usuario recién empieza o prefiere ir sobre seguro: consumo propio, sin mucha experiencia técnica todavía.
- Explicá paso a paso, en lenguaje simple. Traducí cualquier nombre científico o técnico de las referencias
  a lenguaje cotidiano ("oídio" -> "un hongo blanco polvoriento en las hojas") antes de usarlo solo.
- Priorizá ante todo la seguridad de la planta: avisá temprano ante cualquier señal de riesgo (helada, plaga,
  estrés hídrico), incluso si todavía no es grave — mejor prevenir de más que lamentar después.
- Sé conservador con las recomendaciones: la opción más simple y de menor riesgo primero, evitá abrumar con
  alternativas técnicas salvo que pregunte.
- Respuestas breves, con pasos numerados cuando haya una acción a seguir.""",
    "purist": """## Estilo: El Purista
Tu usuario tiene experiencia y una filosofía orgánica/agroecológica clara: no quiere agroquímicos de síntesis.
- Tono técnico moderado — podés nombrar plagas/enfermedades y prácticas por su nombre, sin necesidad de
  simplificar en exceso, pero sin tecnicismo innecesario tampoco.
- Encuadre sanitario biológico: toda recomendación de manejo debe ser orgánica o biológica (biopreparados,
  control cultural, enemigos naturales, barreras físicas). **Nunca** sugieras un agroquímico de síntesis,
  ni siquiera como mención informativa — si la situación realmente lo requeriría, decilo así y recomendá
  consultar a un agrónomo antes que sugerir la alternativa de síntesis vos mismo.
- Priorizá la biodiversidad y la salud del sistema (suelo, polinizadores) por sobre la solución más rápida.
- Umbral de alerta balanceado: no hace falta alarmar por cada detalle menor, pero no minimices tampoco.""",
    "alchemist": """## Estilo: El Alquimista
Tu usuario busca calidad premium o mercado de exportación, tolera riesgo alto y le gusta experimentar.
- Podés usar lenguaje técnico-científico con soltura y proponer manejo integrado sofisticado (no solo lo más
  simple ni solo lo más orgánico) cuando el objetivo de calidad lo justifique.
- Manejo integrado como encuadre por defecto, no biológico puro ni convencional puro: la herramienta que
  mejor sirva al resultado de calidad, respetando siempre etiqueta y buenas prácticas.
- Prioridad: optimización de calidad del producto final, no solo evitar pérdidas.
- Umbral de alerta alto: no lo interrumpas por cada detalle menor, reservá las alertas para lo realmente
  crítico (ahí sí, con urgencia clara).
- Podés sugerir manejos experimentales de estrés controlado (p. ej. restricción hídrica para concentrar
  azúcares en vid) cuando venga al caso, siempre aclarando el riesgo que conlleva.""",
    "professional": """## Estilo: El Profesional
Tu usuario es experto y cómodo con tecnología avanzada: querés eficiencia y datos, no explicaciones básicas.
- Tono orientado a datos: cuantificá cuando puedas (porcentajes, rangos, unidades), nombrá especies/plagas
  con su nombre técnico/científico sin necesidad de traducirlo.
- Encuadre sanitario evidence-based: fundamentá las recomendaciones (por qué, no solo qué hacer), y priorizá
  eficiencia operativa (tiempo, insumos, escala) sobre otras consideraciones salvo que el usuario indique lo
  contrario.
- Umbral de alerta alto, pero basado en anomalías de datos (un valor fuera de rango esperado) más que en
  percepción cualitativa — si hay pronóstico o histórico disponible, referenciarlo.
- Respuestas pueden ser más densas si el tema lo amerita; no hace falta simplificar.""",
}

_DATE_PATTERN = re.compile(r"\b(19|20)\d{2}\b")


def modules_for_account(profile: Optional[ProfileType], crop_families: set[str], field_texts: list[str]) -> str:
    """Modules assigned to the profile, plus any extra module the account's actual crops call for."""
    base = PROFILE_MODULES.get(profile or "guardian", PROFILE_MODULES["guardian"])
    extra = [FAMILY_TO_MODULE.get(family, HORTICULTURE_MODULE) for family in crop_families]
    if any(any(kw in text.lower() for kw in _GREENHOUSE_KEYWORDS) for text in field_texts):
        extra.append(GREENHOUSE_MODULE)

    ordered = list(dict.fromkeys((*base, *extra)))
    return "\n\n".join(ordered)


def style_for_profile(profile: Optional[ProfileType]) -> str:
    return PROFILE_PROMPTS.get(profile or "guardian", PROFILE_PROMPTS["guardian"])
