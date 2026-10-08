"""Exposes the `specific/` manuals (src/agent/knowledge_base/specific/*.md) as ADK Skills instead
of always-loading them into the cached system prompt like `core/` does.

Each manual runs 100k+ tokens, too big to keep permanently in `_static_instruction` once more than
one or two exist — see knowledge_base/README.md. `SkillToolset` gives the agent `load_skill`/
`unload_skill` tools: it decides which manual (if any) applies to the question, loads only that
one, and ADK's own request processor (see `skill_toolset._prune_unloaded_skill_instructions`)
strips a manual's full text back down to a short "unloaded" notice on every request sent after
it stops being active — it stays in the persisted session for the record, but never rides along
in full on turns that don't need it, so it can't bloat every later request even inside the same
conversation.

`SkillDiscoveryMode.EAGER` puts the (short) skill descriptions directly in the system prompt
instead of behind a `list_skills` call: fine for a catalog this small and slow-growing, and it
means the agent can call `load_skill` on the first turn that needs one instead of spending a
turn discovering it first.

Lifecycle follows two layers (see `specific_manuals_toolset`): the big manuals are the *field-type*
layer — `BOUNDED` with `max_active_skills=1`, so loading a second manual evicts the first (one field type
at a time, no `unload_skill` to remember). The per-crop skills (`ficha-*`, `plagas-*`) are `PERSISTENT`:
no cap and never evicted, because a question about a whole cajón/parcela involves several crops at once and
a user usually works with several. The model can release one it no longer needs with `unload_skill`.

Besides the manuals, every crop of the catalog has a short technical sheet (`specific/cultivos/`,
~4–5k tokens each) exposed the same way, one skill per crop (`ficha-<slug>`): small enough that
carrying several at once is cheap, and specific enough that the model can pick the right one from
the crop name in the question. Each crop can also have a companion `plagas-<slug>` skill (general pest
and disease identification, `specific/plagas/<slug>.md`) that carries no products or doses.
"""
import re
from functools import lru_cache
from pathlib import Path

from google.adk.features import FeatureName, override_feature_enabled
from google.adk.skills import Frontmatter, Skill
from google.adk.tools.skill_toolset import (
    SkillDiscoveryMode,
    SkillLifecycleConfig,
    SkillLifecycleMode,
    SkillToolset,
)

from .knowledge_base import core_skill_name, deferred_core_files

_SPECIFIC_DIR = Path(__file__).resolve().parent.parent / "knowledge_base" / "specific"

# filename -> (skill name, description shown to the model to decide whether to load it).
_MANUALS: dict[str, tuple[str, str]] = {
    "00_manual_horticultura.md": (
        "manual-horticultura",
        "Manual de Horticultura (INTA / Ministerio de Agroindustria de la Provincia de Buenos "
        "Aires, 1er año de escuela agraria): referencia técnica general de huerta — estructura y "
        "funciones de la planta, tipos de huerta, construcción y diseño de una huerta, "
        "herramientas, requerimientos de clima/suelo/agua, siembra directa y en almácigo, "
        "trasplante, abonos y fertilizantes (incluye fertilizantes minerales NPK), riego, labores "
        "culturales, plagas y malezas (con preparados caseros), cosecha, valor nutricional de las "
        "hortalizas, producción de semillas, plantas aromáticas y planificación de una huerta "
        "familiar con tabla de rendimientos aproximados por cultivo. Cargar para preguntas "
        "técnicas de manejo de huerta en general, incluyendo fertilización mineral.",
    ),
    "01_huerta_organica.md": (
        "huerta-organica",
        "La Huerta Orgánica Familiar (Programa PRO-HUERTA, INTA): manual enfocado en huerta "
        "orgánica/agroecológica de autoconsumo familiar o comunitario — la chacra (asociación "
        "maíz/poroto/zapallo), tierra orgánica y rotaciones, preparación de abono orgánico "
        "(compuesto, verde, de superficie), planificación de siembra, manejo orgánico (riego, "
        "labores culturales, control de plagas con purines e infusiones caseras — sin agroquímicos "
        "de síntesis), plantas aromáticas y medicinales, nutrición familiar y un recetario de "
        "cocina con verduras de la huerta. Cargar para preguntas sobre manejo 100% orgánico, "
        "biopreparados caseros, o nutrición/recetas a partir de la huerta.",
    ),
}


# One short sheet per catalog crop (knowledge_base/specific/cultivos/<slug>.md, slug = the
# stage_templates key). Files starting with "_" (the blank template) aren't skills. The description
# is built from the sheet's own title line, `# Nombre — *Científico* (Familia)`, so adding a crop is
# just dropping a new file in the folder.
_CROPS_DIR = _SPECIFIC_DIR / "cultivos"
_PLAGUES_DIR = _SPECIFIC_DIR / "plagas"
_CROP_TITLE = re.compile(r"^# (?P<name>.+?) — (?P<scientific>\*.+\*) \((?P<family>[^()]+)\)\s*$")


# Reference guides of the *catalog* layer (specific/guias/): Mexican SENASICA guides on good practices, traceability and
# organic production. Not tied to one crop or to the one-at-a-time manuals: the model picks them from these
# descriptions according to the field type and the user's profile (organic or not). PERSISTENT, so several can be
# active together (e.g. the horticulture BPA manual + the organic guide for an organic vegetable grower).
_GUIDES_DIR = _SPECIFIC_DIR / "guias"
_GUIDES: dict[str, tuple[str, str]] = {
    "inocuidad_produccion_primaria_vegetales_mx.md": (
        "inocuidad-produccion-primaria-vegetales",
        "Guía de apoyo de SENASICA (México) para el análisis de peligros y el plan técnico de inocuidad en la "
        "producción primaria de vegetales (Sistemas de Reducción de Riesgos de Contaminación): diagnóstico de la "
        "unidad de producción, peligros físicos, químicos y microbiológicos, medidas de control y registros. Cargar "
        "SOLO cuando se planifica un cultivo o ciclo de hortalizas/vegetales (qué peligros prever y qué medidas y "
        "registros incluir en el plan), no para consultas generales de manejo.",
    ),
    "bpa_hortofruticolas_campo_empaque_mx.md": (
        "bpa-hortofruticolas-campo-empaque",
        "Manual de Buenas Prácticas Agrícolas de campo y empaque de frutas y hortalizas frescas (México): inocuidad, "
        "higiene del personal, agua de riego y de lavado, suelo y abonos, uso de plaguicidas, cosecha, empaque, "
        "transporte y formatos de registro. Cargar para huerta/hortalizas y frutas cuando el usuario venda o quiera "
        "cumplir inocuidad, certificación de BPA o llevar registros.",
    ),
    "bpa_granos_almacenamiento_mx.md": (
        "bpa-granos-almacenamiento",
        "Manual de Buenas Prácticas en granos básicos de SENASICA (México): producción primaria, cosecha, "
        "acondicionamiento, almacenamiento, transporte y distribución de granos (maíz, trigo, frijol, arroz...), "
        "inocuidad y micotoxinas. Cargar para campos de granos/cereales y preguntas de poscosecha y almacenamiento.",
    ),
    "trazabilidad_vegetales_consumo_fresco_mx.md": (
        "trazabilidad-vegetales-consumo-fresco",
        "Guía de SENASICA (México) de trazabilidad de vegetales para consumo en fresco: trazabilidad hacia atrás, "
        "interna y hacia adelante, códigos de lote, bitácoras y procedimiento de retiro de producto. Cargar cuando el "
        "usuario necesite identificar lotes, llevar registros de trazabilidad o vender a mercados que lo exijan.",
    ),
    "bp_centrales_de_abasto_vegetales_mx.md": (
        "bp-centrales-de-abasto-vegetales",
        "Guía de buenas prácticas de manufactura de SENASICA (México) para establecimientos que manejan vegetales "
        "frescos, como las centrales de abasto: infraestructura, higiene, control de fauna, capacitación y "
        "documentación. Cargar solo si el usuario comercializa o maneja vegetales en una central de abasto o "
        "bodega mayorista; no es para producción en campo.",
    ),
    "produccion_organica_vegetal_mx.md": (
        "produccion-organica-vegetal-mx",
        "Guía de SENASICA-DGIAAP (México, 2026) para la producción vegetal orgánica bajo la Ley de Productos "
        "Orgánicos: prácticas de manejo orgánico, fertilización, control de plagas y enfermedades, manejo de "
        "semillas, conversión y requisitos para la certificación. Cargar cuando el perfil del usuario es orgánico "
        "o quiere certificarse como orgánico en México.",
    ),
    "etiquetado_organico_distintivo_nacional_mx.md": (
        "etiquetado-organico-distintivo-nacional-mx",
        "Guía de SENASICA-DGIAAP (México, 2026) para calcular el porcentaje de ingredientes orgánicos y autorizar el "
        "término «orgánico» y el Distintivo Nacional en el etiquetado (dirigida a organismos de certificación). "
        "Cargar solo para preguntas de etiquetado, rotulación o venta de productos orgánicos elaborados, no para "
        "manejo del cultivo."
    ),
}


# Core documents that a deployment may serve on demand instead of in every request (KNOWLEDGE_CORE_ALWAYS, see
# knowledge_base.py): file prefix -> description shown to the model. EPHEMERAL: loaded for the turn that needs it
# and released after, so a big reference never keeps riding along in the following requests.
_CORE_DESCRIPTIONS: dict[str, str] = {
    "01": (
        "Manual de fertilizantes y enmiendas (PASOLAC/PROMIPAC, Zamorano): requerimientos nutricionales, análisis "
        "de suelo, tipos de fertilizantes y enmiendas, cálculo de dosis y aplicación. Cargar para decidir qué "
        "fertilizar, con qué y cuánto, o corregir un suelo. No cargar para explicar por qué falta un nutriente en "
        "la planta (usar `fisiologia-*`) ni para productos comerciales registrados."
    ),
    "02": (
        "HRAC (en inglés): resistencia a herbicidas — definiciones, evaluación de riesgo, rotación de modos de "
        "acción, mezclas, qué hacer ante resistencia confirmada y monitoreo. Cargar para control de malezas con "
        "herbicidas y resistencia. No cargar para fungicidas o insecticidas."
    ),
    "03": (
        "Manual de SENASICA (México) para el buen uso y manejo de plaguicidas en campo: manejo integrado de plagas, "
        "equipos de aplicación, calibración, seguridad del aplicador, envases y marco jurídico mexicano. Cargar "
        "antes de hablar de aplicar cualquier plaguicida o de seguridad del aplicador. La parte legal es de México."
    ),
    "04": (
        "Guía UC (en inglés; productos y registros de California): clases de fungicidas y bactericidas, códigos "
        "FRAC, resistencia, eficacia por enfermedad y momento de aplicación, con tablas por cultivo (frutales, vid, "
        "cítricos, frutilla). Cargar para fungicidas, su eficacia relativa y su momento de aplicación. Nunca como "
        "prueba de que un producto esté registrado en el país del usuario."
    ),
}


def _core_skills() -> list[Skill]:
    skills = []
    for path in deferred_core_files():
        text = path.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip()
        skills.append(
            Skill(
                frontmatter=Frontmatter(
                    name=core_skill_name(path),
                    description=_CORE_DESCRIPTIONS.get(path.name.split("_", 1)[0], title),
                ),
                instructions=text,
            )
        )
    return skills


# Plant physiology textbook (Vol. I), split into 7 topic fragments with no text removed (specific/fisiologia/).
# EPHEMERAL: a reference lookup for the turn that needs it, released afterwards so 12-19k tokens don't keep riding
# along. Several fragments can be loaded in the same step (parallel `load_skill` calls).
_FISIOLOGIA_DIR = _SPECIFIC_DIR / "fisiologia"
_FISIOLOGIA: dict[str, tuple[str, str]] = {
    "01_fundamentos_y_cambio_climatico.md": (
        "fisiologia-fundamentos",
        "Fisiología vegetal, fundamentos (texto universitario, Ecuador): qué estudia la fisiología vegetal, su "
        "historia, su importancia para la producción vegetal y las respuestas fisiológicas de las plantas al cambio "
        "climático. Cargar para preguntas conceptuales o sobre cambio climático y cultivos. No cargar para "
        "diagnosticar un problema concreto ni para agua o nutrientes: están en los otros fragmentos `fisiologia-*`.",
    ),
    "02_agua_en_el_suelo_y_absorcion.md": (
        "fisiologia-agua-suelo-y-absorcion",
        "Fisiología vegetal, agua (1/3): el agua en el suelo, su importancia para la planta, el contenido hídrico, "
        "las relaciones hídricas a nivel celular y la absorción de agua por la planta. Cargar para entender "
        "marchitez, estrés hídrico, retención de agua del suelo o cómo absorben agua las raíces. No cargar para "
        "calcular riego (usar get_irrigation_recommendation).",
    ),
    "03_estomas_y_transpiracion.md": (
        "fisiologia-estomas-y-transpiracion",
        "Fisiología vegetal, agua (2/3): el aparato estomático (apertura y cierre) y la transpiración. Cargar para "
        "explicar cierre de estomas, marchitez al mediodía, efecto del calor y del viento, eficiencia en el uso del "
        "agua. No cargar para calcular riego.",
    ),
    "04_balance_hidrico_y_clima.md": (
        "fisiologia-balance-hidrico-y-clima",
        "Fisiología vegetal, agua (3/3): el movimiento del agua suelo-planta-atmósfera, el balance de agua de la "
        "planta y cómo responden los indicadores hídricos al cambio climático; incluye el cierre del capítulo "
        "(resumen, glosario, bibliografía). Cargar para balance hídrico y estrés hídrico en un contexto de clima "
        "cambiante.",
    ),
    "05_nutricion_mineral_fundamentos.md": (
        "fisiologia-nutricion-mineral-fundamentos",
        "Fisiología vegetal, nutrición mineral (1/3): composición mineral de las plantas, elementos esenciales y su "
        "clasificación, suelo-raíz-microorganismos, absorción, permeabilidad y potencial de membrana, asimilación, "
        "transporte de iones y cambio climático. Cargar para nutrición mineral en general, movilidad de los "
        "nutrientes en la planta y por qué un síntoma aparece en hojas jóvenes o viejas. Para un nutriente "
        "concreto, cargar además el fragmento correspondiente.",
    ),
    "06_macronutrientes_n_p_k_s.md": (
        "fisiologia-macronutrientes-npk-s",
        "Fisiología vegetal, nutrición mineral (2/3): nitrógeno, azufre, fósforo y potasio — funciones, absorción, "
        "deficiencias y toxicidad. Cargar para hojas amarillas o pálidas, crecimiento lento, floración y raíces, "
        "calidad de fruto y exceso de nitrógeno. Para decidir qué fertilizante aplicar y cuánto, cargar "
        "`core-fertilizantes-y-enmiendas`.",
    ),
    "07_calcio_magnesio_y_microelementos.md": (
        "fisiologia-calcio-magnesio-microelementos",
        "Fisiología vegetal, nutrición mineral (3/3): magnesio, calcio y microelementos — funciones, deficiencias y "
        "toxicidad; incluye el cierre del capítulo (resumen, glosario, bibliografía). Cargar para clorosis entre "
        "nervaduras, desórdenes por calcio o magnesio y deficiencias de micronutrientes.",
    ),
}


def _crop_sheet_skill(path: Path) -> Skill:
    title = path.read_text(encoding="utf-8").splitlines()[0]
    m = _CROP_TITLE.match(title)
    if not m:
        raise ValueError(f"{path.name}: first line must be '# Nombre — *Científico* (Familia)', got {title!r}")
    name, scientific = m["name"], m["scientific"].replace("*", "")
    return Skill(
        frontmatter=Frontmatter(
            name=f"ficha-{path.stem}",
            description=(
                f"Ficha técnica de {name} ({scientific}, {m['family']}), con datos de Argentina: variedades y "
                "tipos, composición nutricional, clima, suelo, fertilización, riego y Kc, siembra, etapas, "
                "plagas, enfermedades, fisiopatías, asociaciones y rotación, cosecha y poscosecha. Cargar "
                f"para cualquier pregunta sobre {name.lower()}. Los calendarios son del hemisferio sur: en el "
                "hemisferio norte invertir las estaciones. Para manejo general de huerta, usar los manuales."
                + (
                    f" Para identificar una plaga o enfermedad de {name.lower()} en detalle, cargar también "
                    f"plagas-{path.stem}."
                    if (_PLAGUES_DIR / path.name).is_file()
                    else ""
                )
            ),
        ),
        instructions=path.read_text(encoding="utf-8"),
    )


def _plagues_skill(path: Path) -> Skill:
    title = path.read_text(encoding="utf-8").splitlines()[0]
    m = _CROP_TITLE.match(title)
    if not m:
        raise ValueError(f"{path.name}: first line must be '# Nombre — *Científico* (Familia)', got {title!r}")
    name, scientific = m["name"], m["scientific"].replace("*", "")
    return Skill(
        frontmatter=Frontmatter(
            name=f"plagas-{path.stem}",
            description=(
                f"Guía de identificación de plagas y enfermedades de {name} ({scientific}): cómo reconocer cada "
                "una (síntomas, daño, ciclo y condiciones que la favorecen), cómo monitorearla y qué medidas "
                "culturales y biológicas existen. Sin productos ni dosis: esos salen de las tablas de registro y "
                "de la búsqueda web con fuente. Cargar para diagnosticar o describir un síntoma, plaga o "
                f"enfermedad de {name.lower()}; combinar con su ficha. No cargar para fertilizar o regar."
            ),
        ),
        instructions=path.read_text(encoding="utf-8"),
    )


def _load_manual_skills() -> list[Skill]:
    skills = []
    for filename, (name, description) in _MANUALS.items():
        path = _SPECIFIC_DIR / filename
        if not path.is_file():
            continue
        skills.append(
            Skill(
                frontmatter=Frontmatter(name=name, description=description),
                instructions=path.read_text(encoding="utf-8"),
            )
        )
    skills.extend(_core_skills())
    for filename, (name, description) in _FISIOLOGIA.items():
        path = _FISIOLOGIA_DIR / filename
        if path.is_file():
            skills.append(Skill(frontmatter=Frontmatter(name=name, description=description),
                                instructions=path.read_text(encoding="utf-8")))
    for filename, (name, description) in _GUIDES.items():
        path = _GUIDES_DIR / filename
        if path.is_file():
            skills.append(Skill(frontmatter=Frontmatter(name=name, description=description),
                                instructions=path.read_text(encoding="utf-8")))
    if _CROPS_DIR.is_dir():
        skills.extend(
            _crop_sheet_skill(path) for path in sorted(_CROPS_DIR.glob("*.md")) if not path.name.startswith("_")
        )
    if _PLAGUES_DIR.is_dir():
        skills.extend(
            _plagues_skill(path) for path in sorted(_PLAGUES_DIR.glob("*.md")) if not path.name.startswith("_")
        )
    return skills


@lru_cache(maxsize=1)
def specific_manuals_toolset() -> SkillToolset:
    """Cached like `core_knowledge_base()`: the manuals are static within a deployed container.

    Two lifecycle layers: the manuals (field type: horticultura, huerta orgánica, later granos/vid/flores) are
    BOUNDED with a cap of 1; every other skill (`ficha-*`, `plagas-*`) uses the PERSISTENT default, which ADK
    exempts from the cap and never evicts.

    Turns on ADK's experimental SKILL_LIFECYCLE feature (off by default). Without it the toolset still applies
    the cap, but it neither offers `unload_skill` nor strips a released skill's text from later requests, so
    every manual or sheet ever loaded would keep riding along in the conversation history.
    """
    override_feature_enabled(FeatureName.SKILL_LIFECYCLE, True)
    return SkillToolset(
        skills=_load_manual_skills(),
        discovery_mode=SkillDiscoveryMode.EAGER,
        lifecycle_config=SkillLifecycleConfig(
            default_mode=SkillLifecycleMode.PERSISTENT,
            max_active_skills=1,
            skill_overrides={
                **{name: SkillLifecycleMode.BOUNDED for name, _ in _MANUALS.values()},
                **{core_skill_name(p): SkillLifecycleMode.EPHEMERAL for p in deferred_core_files()},
                **{name: SkillLifecycleMode.EPHEMERAL for name, _ in _FISIOLOGIA.values()},
            },
        ),
        # Plain text skills with no scripts or resources. `unload_skill` lets the model drop a persistent crop
        # skill it is done with, so a long conversation doesn't keep carrying every sheet it ever opened.
        tool_filter=["load_skill", "unload_skill"],
    )


def skill_catalog() -> dict[str, Skill]:
    """Every skill by name, as the toolset serves them (the preflight loads from here without a model round trip)."""
    return {skill.name: skill for skill in specific_manuals_toolset()._list_skills()}
