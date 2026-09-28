"""Loads the fixed "core" knowledge-base manuals (src/agent/knowledge_base/core/*.md) that the
agent's system prompt includes on every turn, regardless of crop or profile.

This is separate from `knowledge_ar.py`: that module holds short, hand-written Argentina-specific
modules selected per profile/crop; this one loads full reference manuals stored as Markdown files,
starting with the plant-physiology/mineral-nutrition core. See knowledge_base/README.md for the
full folder layout, including the `specific/` and `inputs/` manuals to be wired in later.
"""
from functools import lru_cache
from pathlib import Path

_CORE_DIR = Path(__file__).resolve().parent.parent / "knowledge_base" / "core"


@lru_cache(maxsize=1)
def core_knowledge_base() -> str:
    """Concatenated Markdown content of every manual in knowledge_base/core/, sorted by filename.
    Cached: the files are static within a deployed container, no need to re-read them per turn."""
    if not _CORE_DIR.is_dir():
        return ""
    manuals = [path.read_text(encoding="utf-8") for path in sorted(_CORE_DIR.glob("*.md"))]
    return "\n\n---\n\n".join(manuals)
