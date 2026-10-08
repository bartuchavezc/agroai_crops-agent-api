from src.agent.prompts.knowledge_skills import _CROPS_DIR, _load_manual_skills
from src.application.planning.stage_templates import TEMPLATES


def _skills_by_name():
    return {s.name: s for s in _load_manual_skills()}


def test_every_catalog_crop_has_a_sheet_skill():
    skills = _skills_by_name()
    missing = [crop for crop in TEMPLATES if f"ficha-{crop}" not in skills]
    assert not missing


def test_crop_sheets_have_all_sections_and_no_unfilled_placeholders():
    for path in _CROPS_DIR.glob("*.md"):
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8")
        assert "{{" not in text, path.name
        for n in range(1, 16):
            assert f"\n## {n}. " in text, f"{path.name}: falta la sección {n}"
        assert "\n## Fuentes" in text, path.name


def test_template_is_not_loaded_as_a_skill():
    assert "ficha-_plantilla" not in _skills_by_name()


def test_manuals_are_still_loaded():
    skills = _skills_by_name()
    assert {"manual-horticultura", "huerta-organica"} <= set(skills)


def _toolset():
    from src.agent.prompts.knowledge_skills import specific_manuals_toolset

    return specific_manuals_toolset()


def _activate(toolset, state, name):
    return toolset._record_activation(state, "agent", name, "inv-1")


def test_only_one_field_type_manual_is_active_at_a_time():
    toolset, state = _toolset(), {}
    assert _activate(toolset, state, "manual-horticultura") == []
    assert _activate(toolset, state, "huerta-organica") == ["manual-horticultura"]


def test_crop_skills_are_unbounded_and_do_not_evict_the_manual():
    toolset, state = _toolset(), {}
    _activate(toolset, state, "manual-horticultura")
    crops = [name for name in _skills_by_name() if name.startswith("ficha-")][:6]
    assert len(crops) == 6
    for name in crops:
        assert _activate(toolset, state, name) == [], name
    active = toolset._active_skills(state, "agent", "inv-1")
    assert set(active) == {"manual-horticultura", *crops}


def test_unload_skill_is_offered_to_the_model():
    import asyncio

    names = {t.name for t in asyncio.run(_toolset().get_tools())}
    assert {"load_skill", "unload_skill"} <= names


_PLAGUES_DIR = _CROPS_DIR.parent / "plagas"


def _plague_files():
    return [p for p in _PLAGUES_DIR.glob("*.md") if not p.name.startswith("_")]


def test_every_plague_guide_has_a_crop_sheet_and_a_skill():
    skills = _skills_by_name()
    for path in _plague_files():
        assert (_CROPS_DIR / path.name).is_file(), f"{path.name}: falta la ficha del cultivo"
        assert f"plagas-{path.stem}" in skills


def test_plague_guides_have_all_sections_and_no_products_or_doses():
    import re

    dose = re.compile(r"\d\s?(g|ml|cc|kg|l)\s?/\s?(ha|l|hl|100\s?l|acre)\b", re.IGNORECASE)
    for path in _plague_files():
        text = path.read_text(encoding="utf-8")
        assert "{{" not in text, path.name
        for n in range(1, 10):
            assert f"\n## {n}. " in text, f"{path.name}: falta la sección {n}"
        assert "\n## Fuentes" in text, path.name
        assert not dose.search(text), f"{path.name}: trae dosis"


def test_plague_template_is_not_loaded_and_sheet_points_to_its_guide():
    skills = _skills_by_name()
    assert "plagas-_plantilla" not in skills
    assert "plagas-tomate" in skills["ficha-tomate"].description
    assert "plagas-lechuga" not in skills["ficha-lechuga"].description


def test_guides_are_catalog_skills_that_coexist_with_each_other_and_with_a_manual():
    from src.agent.prompts.knowledge_skills import _GUIDES

    toolset, state = _toolset(), {}
    skills = _skills_by_name()
    names = [name for name, _ in _GUIDES.values()]
    assert set(names) <= set(skills) and len(names) == len(set(names)) == 7
    _activate(toolset, state, "manual-horticultura")
    for name in names:
        assert _activate(toolset, state, name) == [], name  # none evicts the manual or another guide
    assert set(toolset._active_skills(state, "agent", "inv-1")) == {"manual-horticultura", *names}


def test_converted_markdown_has_no_layout_leftovers():
    import re

    base = _CROPS_DIR.parent
    files = list((base.parent / "core").glob("0[2-4]_*.md")) + list((base / "guias").glob("*.md"))
    assert len(files) == 3 + 7
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"</?(u|mark|br)>", text), path.name
        assert not re.search(r"\.{5,}", text), f"{path.name}: puntos de índice"
        assert "intentionally omitted" not in text, path.name


def test_core_starts_with_the_knowledge_map_and_it_names_real_skill_prefixes():
    from src.agent.prompts.knowledge_base import core_knowledge_base

    core = core_knowledge_base()
    assert core.startswith("# Mapa del conocimiento del agente")
    skills = _skills_by_name()
    for prefix in ("ficha-", "plagas-"):
        assert any(name.startswith(prefix) for name in skills), prefix
        assert f"`{prefix}<cultivo>`" in core
    for name in ("manual-horticultura", "huerta-organica", "inocuidad-produccion-primaria-vegetales"):
        assert name in skills


def _reload_with_core_setting(monkeypatch, value):
    from src.agent.prompts import knowledge_base, knowledge_skills

    if value is None:
        monkeypatch.delenv("KNOWLEDGE_CORE_ALWAYS", raising=False)
    else:
        monkeypatch.setenv("KNOWLEDGE_CORE_ALWAYS", value)
    knowledge_base.core_knowledge_base.cache_clear()
    knowledge_skills.specific_manuals_toolset.cache_clear()
    return knowledge_base, knowledge_skills


def test_default_pins_only_the_map_and_serves_the_references_as_ephemeral_skills(monkeypatch):
    from google.adk.tools.skill_toolset import SkillLifecycleMode

    kb, ks = _reload_with_core_setting(monkeypatch, None)
    try:
        core = kb.core_knowledge_base()
        assert core.startswith("# Mapa del conocimiento del agente") and len(core) < 12_000  # ~1.3k tokens
        assert "Fungicides, Bactericides, Biocontrols" not in core
        deferred = {ks.core_skill_name(p) for p in kb.deferred_core_files()}
        assert deferred == {
            "core-fertilizantes-y-enmiendas", "core-resistencia-a-herbicidas-hrac",
            "core-uso-y-manejo-de-plaguicidas-mx", "core-fungicidas-eficacia-y-momento-uc",
        }
        toolset = ks.specific_manuals_toolset()
        skills = {s.name: s for s in ks._load_manual_skills()}
        assert deferred <= set(skills)
        assert all(toolset._lifecycle_for(n) is SkillLifecycleMode.EPHEMERAL for n in deferred)
        assert "Cross-Resistance" in skills["core-resistencia-a-herbicidas-hrac"].instructions  # full document
    finally:
        _reload_with_core_setting(monkeypatch, None)


def test_pinned_documents_ride_in_the_prompt_and_stop_being_skills(monkeypatch):
    kb, ks = _reload_with_core_setting(monkeypatch, "01,03")
    try:
        core = kb.core_knowledge_base()
        assert "Manual de Fertilizantes y Enmiendas" in core
        assert "Manual para el buen uso y manejo de plaguicidas" in core
        assert "Fungicides, Bactericides, Biocontrols" not in core  # the UC guide stayed on demand
        assert "Referencias fijadas en este prompt" in core  # the map is told which ones no longer need load_skill
        assert {ks.core_skill_name(p) for p in kb.deferred_core_files()} == {
            "core-resistencia-a-herbicidas-hrac", "core-fungicidas-eficacia-y-momento-uc",
        }
        assert len(core) < 250_000
    finally:
        _reload_with_core_setting(monkeypatch, None)


def test_all_pins_the_complete_reference_manuals(monkeypatch):
    kb, ks = _reload_with_core_setting(monkeypatch, "all")
    try:
        core = kb.core_knowledge_base()
        for marker in (
            "Guideline to the Management of Herbicide Resistance",  # HRAC 2025
            "Monitoring and Mitigation of Herbicide Resistance",  # HRAC perspectives
            "Manual para el buen uso y manejo de plaguicidas en campo",  # SENASICA
            "Fungicides, Bactericides, Biocontrols, and Natural Products",  # UC
            "Alcance regional",  # caveat: California products are not a local registration
        ):
            assert marker in core, marker
        # the two-column HRAC intro keeps its definitions (they were once swallowed with the table of contents)
        assert "Cross-Resistance" in core and "Non-target site resistance" in core
        assert kb.deferred_core_files() == []
        assert not [s for s in ks._load_manual_skills() if s.name.startswith("core-")]
    finally:
        _reload_with_core_setting(monkeypatch, None)


def test_none_is_the_same_as_the_default(monkeypatch):
    kb, _ = _reload_with_core_setting(monkeypatch, "none")
    try:
        assert len(kb.deferred_core_files()) == 4 and len(kb.core_knowledge_base()) < 12_000
    finally:
        _reload_with_core_setting(monkeypatch, None)


# --- physiology textbook, split into 7 skills without removing a line ---------------------------------------------

def _physiology_files():
    return sorted((_CROPS_DIR.parent / "fisiologia").glob("*.md"))


def test_physiology_fragments_hold_every_section_of_the_book_exactly_once():
    import re

    files = _physiology_files()
    assert len(files) == 7
    text = "\n".join(p.read_text(encoding="utf-8") for p in files)
    headings = re.findall(r"(?m)^#{2,3} (.+)$", text)
    expected = (
        ["Introducción"]
        + [f"Capítulo {n}: " for n in (1, 2, 3)]
        + [f"{c}.{i}. " for c, last in ((1, 13), (2, 16), (3, 23)) for i in range(1, last + 1)]
    )
    assert len(headings) == len(expected) == 56
    for prefix in expected:
        assert sum(h.startswith(prefix) for h in headings) == 1, prefix
    assert sum(len(p.read_text(encoding="utf-8")) for p in files) >= 423_000  # nothing was trimmed (~106k tokens)


def test_physiology_fragments_are_ephemeral_skills_with_a_trigger_in_the_description():
    from google.adk.tools.skill_toolset import SkillLifecycleMode

    toolset, skills = _toolset(), _skills_by_name()
    names = [n for n in skills if n.startswith("fisiologia-")]
    assert len(names) == 7
    for name in names:
        assert toolset._lifecycle_for(name) is SkillLifecycleMode.EPHEMERAL, name
        assert "Cargar" in skills[name].description, name  # says when to load it


def test_every_skill_the_map_names_exists():
    import re

    from src.agent.prompts.knowledge_base import core_knowledge_base

    map_text = _CROPS_DIR.parent.parent / "core" / "000_mapa_del_conocimiento.md"
    skills = set(_skills_by_name())
    known = re.compile(r"^(fisiologia|core|manual|huerta|bpa|trazabilidad|bp|produccion|etiquetado|inocuidad)-")
    named = {t for t in re.findall(r"`([a-z0-9-]+)`", map_text.read_text(encoding="utf-8")) if known.match(t)}
    assert len(named) >= 18
    assert not (named - skills), named - skills
    assert core_knowledge_base().startswith("# Mapa del conocimiento")
