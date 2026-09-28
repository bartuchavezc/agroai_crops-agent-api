import re

from src.agent.prompts.knowledge_ar import (
    EXTENSIVE_GRAINS_MODULE,
    GENERAL_AGRONOMY,
    GREENHOUSE_MODULE,
    HORTICULTURE_MODULE,
    PROFILE_MODULES,
    PROFILE_PROMPTS,
    VITICULTURE_MODULE,
    modules_for_account,
    style_for_profile,
)

PROFILES = ("guardian", "purist", "alchemist", "professional")
ALL_MODULES = (GENERAL_AGRONOMY, HORTICULTURE_MODULE, GREENHOUSE_MODULE, VITICULTURE_MODULE, EXTENSIVE_GRAINS_MODULE)
# Years only appear in things like "NPK" style facts, not sowing dates; guard against a stray date creeping in.
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def test_all_profiles_have_modules_and_style():
    assert set(PROFILE_MODULES) == set(PROFILES)
    assert set(PROFILE_PROMPTS) == set(PROFILES)


def test_general_agronomy_is_always_included():
    for profile in PROFILES:
        assert GENERAL_AGRONOMY in PROFILE_MODULES[profile]


def test_professional_is_the_only_full_set_with_grains():
    assert PROFILE_MODULES["professional"] == list(ALL_MODULES)
    for profile in ("guardian", "purist", "alchemist"):
        assert EXTENSIVE_GRAINS_MODULE not in PROFILE_MODULES[profile]


def test_modules_and_prompts_have_real_content():
    for module in ALL_MODULES:
        assert len(module) > 500
    for profile in PROFILES:
        assert len(PROFILE_PROMPTS[profile]) > 300


def test_no_module_hardcodes_a_specific_year():
    for module in ALL_MODULES:
        assert not _YEAR.search(module), "modules must stay date-free; use tools for anything that changes"


def test_modules_for_account_falls_back_to_guardian_without_a_profile():
    result = modules_for_account(None, crop_families=set(), field_texts=[])
    assert result == "\n\n".join(PROFILE_MODULES["guardian"])
    assert style_for_profile(None) == PROFILE_PROMPTS["guardian"]


def test_modules_for_account_adds_extra_module_by_crop_family():
    # A guardian growing grapes still gets viticulture, even though it's not in guardian's default set.
    result = modules_for_account("guardian", crop_families={"Vitaceae"}, field_texts=[])
    assert VITICULTURE_MODULE in result
    assert EXTENSIVE_GRAINS_MODULE not in result


def test_modules_for_account_adds_greenhouse_from_field_text_heuristic():
    result = modules_for_account("guardian", crop_families=set(), field_texts=["Cultivo bajo invernadero"])
    assert GREENHOUSE_MODULE in result


def test_modules_for_account_deduplicates():
    # alchemist already includes greenhouse; the heuristic must not duplicate it.
    result = modules_for_account("alchemist", crop_families=set(), field_texts=["invernadero de vidrio"])
    assert result.count("## Cultivo bajo cubierta") == 1
