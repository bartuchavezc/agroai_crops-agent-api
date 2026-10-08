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
