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
turn discovering it first. `SkillLifecycleMode.BOUNDED` with `max_active_skills=1` means loading
a second manual automatically evicts whichever was active — appropriate given how large each one
is; there's no `unload_skill` call for the agent to remember to make.
"""
from functools import lru_cache
from pathlib import Path

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
    return skills


@lru_cache(maxsize=1)
def specific_manuals_toolset() -> SkillToolset:
    """Cached like `core_knowledge_base()`: the manuals are static within a deployed container."""
    return SkillToolset(
        skills=_load_manual_skills(),
        discovery_mode=SkillDiscoveryMode.EAGER,
        lifecycle_config=SkillLifecycleConfig(
            default_mode=SkillLifecycleMode.BOUNDED,
            max_active_skills=1,
        ),
        # These skills are plain manual text with no scripts or extra resources attached, and
        # bounded lifecycle already evicts the previous manual on load, so nothing else is needed.
        tool_filter=["load_skill"],
    )
