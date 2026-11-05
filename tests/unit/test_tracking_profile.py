"""How closely the agent follows a person: the intensity starts from the enrollment and the person can change it."""
from types import SimpleNamespace

from src.agent.prompts.knowledge import intensity_for, short_style
from src.agent.prompts.nudges import build_nudge_prompt
from src.auth.services.tracking_profile import (
    WEEKLY_ASKS, growing_context_lines, intensity_from_form, tracking_profile_read,
)


def test_the_enrollment_sets_the_starting_intensity():
    assert intensity_from_form({"q10": "C"}) == "alta"
    assert intensity_from_form({"q10": "B", "q1": "C", "q2": "C"}) == "media"
    assert intensity_from_form({"q10": "A", "q1": "C", "q2": "B"}) == "baja"
    # a beginner who wants the agent to keep the records still gets a nudge at the right moments
    assert intensity_from_form({"q10": "A", "q1": "A", "q2": "A"}) == "media"
    assert intensity_from_form({}) == "media"


def test_the_persons_choice_wins_over_the_enrollment():
    enrolled = SimpleNamespace(form={"q10": "C"}, tracking_intensity=None, growing_context={}, profile="purist")
    read = tracking_profile_read(enrolled)
    assert (read.intensity, read.intensity_source, read.weekly_asks) == ("alta", "enroll", WEEKLY_ASKS["alta"])
    chosen = SimpleNamespace(form={"q10": "C"}, tracking_intensity="baja", growing_context={
        "tools": ["medidor_ph", "malla_sombra"], "weekly_hours": 3, "budget": "bajo"}, profile="purist")
    read = tracking_profile_read(chosen)
    assert (read.intensity, read.intensity_source, read.enroll_intensity) == ("baja", "person", "alta")
    lines = "\n".join(growing_context_lines(read))
    assert "medidor de pH" in lines and "malla de sombra" in lines and "3 horas" in lines
    assert tracking_profile_read(None).intensity_source == "default"


def test_without_tools_the_agent_is_told_not_to_assume_instruments():
    lines = growing_context_lines(tracking_profile_read(None))
    assert any("no supongas instrumentos" in line for line in lines)


def test_profile_guides_say_how_to_ask_and_how_to_give_bad_news():
    for profile in ("guardian", "purist", "alchemist", "professional"):
        guide = short_style(profile)
        assert "Cómo pedir un dato" in guide and "Malas noticias" in guide
        assert not guide.startswith("##")
    assert "baja" in intensity_for("baja") and "alta" in intensity_for("alta")
    assert intensity_for(None) == intensity_for("media")


def test_the_nudge_prompt_carries_each_persons_voice_budget_and_habits():
    people = [{"id": "u1", "name": "Ana", "role": "owner", "left": 2, "quiet": False, "intensity": "baja",
               "weekly_asks": 2, "asks_left": 0, "profile": "professional", "means": ["Herramientas: tensiómetro."],
               "engagement": "sin entrar hace 5 días; responde por audio (3)"}]
    prompt = build_nudge_prompt(people, [], [], "jueves 5/11 09:00")
    assert "intensidad baja · pedidos de datos disponibles esta semana: 0 · perfil professional" in prompt
    assert "responde por audio" in prompt and "tensiómetro" in prompt
    assert "### professional" in prompt and "Cómo pedir un dato" in prompt
