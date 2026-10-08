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
                f"Ficha técnica de {name} ({scientific}, {m['family']}) para Argentina: variedades y "
                "tipos, composición nutricional, clima, suelo, fertilización, riego y Kc, siembra, etapas, "
                "plagas, enfermedades, fisiopatías, asociaciones y rotación, cosecha y poscosecha. Cargar "
                f"para preguntas puntuales sobre {name.lower()}; para manejo general de huerta, usar los manuales."
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
                f"de la búsqueda web con fuente. Cargar para diagnosticar o describir un problema de {name.lower()}."
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
            skill_overrides={name: SkillLifecycleMode.BOUNDED for name, _ in _MANUALS.values()},
        ),
        # Plain text skills with no scripts or resources. `unload_skill` lets the model drop a persistent crop
        # skill it is done with, so a long conversation doesn't keep carrying every sheet it ever opened.
        tool_filter=["load_skill", "unload_skill"],
    )
