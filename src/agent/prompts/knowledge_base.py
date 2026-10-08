"""Loads the fixed "core" knowledge-base manuals (src/agent/knowledge_base/core/*.md) that the
agent's system prompt includes on every turn, regardless of crop or profile.

This is separate from `knowledge_ar.py`: that module holds short, hand-written Argentina-specific
modules selected per profile/crop; this one loads full reference manuals stored as Markdown files.
See knowledge_base/README.md for the full folder layout.

Which core documents ride in every request is configurable with `KNOWLEDGE_CORE_ALWAYS`: unset or `none` (the
default) keeps only the knowledge map (`000_*`) fixed; a comma-separated list of the numeric prefixes of the files in
`core/` (e.g. `01,03`) pins those too; `all` pins every document. The rest are served as on-demand skills
`core-<name>` (see `knowledge_skills.py`) and the map is followed by a generated note listing them. The default is
the cheap one: the reference documents are large (20-56k tokens each) and every step of the agent loop re-sends the
fixed prompt, so pinning them costs on each call; `all` is for deployments that prefer to pay for that.
"""
import os
import re
from functools import lru_cache
from pathlib import Path

_CORE_DIR = Path(__file__).resolve().parent.parent / "knowledge_base" / "core"
_MAP_PREFIX = "000"


def _core_files() -> list[Path]:
    return sorted(_CORE_DIR.glob("*.md")) if _CORE_DIR.is_dir() else []


def _prefix(path: Path) -> str:
    return path.name.split("_", 1)[0]


def _always_prefixes() -> set[str] | None:
    """None = everything fixed (`all`). Otherwise the set of numeric prefixes that stay in the system prompt."""
    raw = (os.environ.get("KNOWLEDGE_CORE_ALWAYS") or "").strip().lower()
    if raw == "all":
        return None
    return {p.strip() for p in raw.split(",") if p.strip() and p.strip() != "none"}


def deferred_core_files() -> list[Path]:
    """Core documents that are NOT in the system prompt and are served as `core-*` skills instead."""
    always = _always_prefixes()
    if always is None:
        return []
    return [p for p in _core_files() if _prefix(p) != _MAP_PREFIX and _prefix(p) not in always]


def core_skill_name(path: Path) -> str:
    """`02_resistencia_a_herbicidas_hrac.md` -> `core-resistencia-a-herbicidas-hrac`."""
    return "core-" + re.sub(r"[^a-z0-9]+", "-", path.stem.split("_", 1)[1].lower()).strip("-")


def _pinned_core_files() -> list[Path]:
    """Core documents (besides the map) that ARE in the system prompt."""
    deferred = {p.name for p in deferred_core_files()}
    return [p for p in _core_files() if _prefix(p) != _MAP_PREFIX and p.name not in deferred]


@lru_cache(maxsize=1)
def core_knowledge_base() -> str:
    """Concatenated Markdown content of the always-loaded documents in knowledge_base/core/, sorted by filename: the
    knowledge map plus whatever `KNOWLEDGE_CORE_ALWAYS` pins. Cached: the files and the setting are static within a
    running process, no need to re-read them per turn."""
    deferred = {p.name for p in deferred_core_files()}
    pinned = _pinned_core_files()
    parts = []
    for path in _core_files():
        if path.name in deferred:
            continue
        parts.append(path.read_text(encoding="utf-8"))
        if _prefix(path) == _MAP_PREFIX and pinned:
            parts[-1] += _pinned_note(pinned)
    return "\n\n---\n\n".join(parts)


def _pinned_note(pinned: list[Path]) -> str:
    """The map describes every `core-*` reference as a skill. When some are pinned in the prompt instead, say which."""
    names = ", ".join(f"`{core_skill_name(p)}`" for p in pinned)
    return (
        "\n\n## Referencias fijadas en este prompt\n\n"
        f"En este despliegue {names} no se piden con `load_skill`: su texto completo está pegado a continuación. "
        "Las demás referencias `core-*` de la tabla sí se piden con `load_skill`.\n"
    )
