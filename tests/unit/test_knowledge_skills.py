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
