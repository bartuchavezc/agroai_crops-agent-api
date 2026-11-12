"""How closely the agent follows a person: the intensity starts from the enrollment and the person can change it."""
from types import SimpleNamespace

from src.agent.prompts.knowledge import intensity_for, short_style
from src.agent.prompts.nudges import build_nudge_prompt
from src.auth.services.tracking_profile import (
    WEEKLY_ASKS, GrowingContext, growing_context_lines, intensity_from_form, merge_resources, tracking_profile_read,
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
        "resources": [{"name": "tester de pH barato", "note": "no sé si está calibrado"},
                      {"name": "botellas como riego por goteo", "source": "agent"}],
        "notes": "Riego los fines de semana, poco presupuesto"}, profile="purist")
    read = tracking_profile_read(chosen)
    assert (read.intensity, read.intensity_source, read.enroll_intensity) == ("baja", "person", "alta")
    lines = "\n".join(growing_context_lines(read))
    assert "tester de pH barato (no sé si está calibrado)" in lines and "botellas como riego por goteo" in lines
    assert "Riego los fines de semana" in lines
    assert tracking_profile_read(None).intensity_source == "default"


def test_without_means_the_agent_is_told_not_to_assume_instruments_and_to_ask():
    lines = growing_context_lines(tracking_profile_read(None))
    assert any("no supongas instrumentos" in line and "preguntá" in line for line in lines)


def test_contexts_saved_with_the_old_fixed_fields_become_words():
    ctx = GrowingContext.model_validate({"tools": ["medidor_ph", "malla_sombra"], "other_tools": "pala",
                                         "weekly_hours": 3, "budget": "bajo"})
    assert [r.name for r in ctx.resources] == ["medidor de pH", "malla de sombra", "pala"]
    assert ctx.notes == "Le dedica unas 3 horas por semana. Presupuesto para invertir: bajo."


def test_the_agent_adds_and_removes_means_in_the_persons_words():
    ctx = GrowingContext.model_validate({"resources": [{"name": "Tester de pH"}], "notes": "poco tiempo"})
    merged = merge_resources(ctx, [{"name": "malla media sombra", "note": "35 %"}, {"name": "tester de pH",
                                                                                  "note": "se le gastó la pila"}],
                             [], "agent")
    assert [(r.name, r.note, r.source) for r in merged.resources] == [
        ("Tester de pH", "se le gastó la pila", "person"), ("malla media sombra", "35 %", "agent")]
    assert merged.notes == "poco tiempo"
    gone = merge_resources(merged, [], ["TESTER DE PH"], "agent", notes="")
    assert [r.name for r in gone.resources] == ["malla media sombra"] and gone.notes is None


def test_profile_guides_say_how_to_ask_and_how_to_give_bad_news():
    for profile in ("guardian", "purist", "alchemist", "professional"):
        guide = short_style(profile)
        assert "Cómo pedir un dato" in guide and "Malas noticias" in guide
        assert not guide.startswith("##")
    assert "baja" in intensity_for("baja") and "alta" in intensity_for("alta")
    assert intensity_for(None) == intensity_for("media")


def test_the_nudge_prompt_carries_each_persons_voice_budget_and_habits():
    people = [{"id": "u1", "name": "Ana", "role": "owner", "left": 2, "quiet": False, "intensity": "baja",
               "weekly_asks": 2, "asks_left": 0, "profile": "professional",
               "means": ["Con qué cuenta (en sus palabras): tensiómetro."],
               "engagement": "sin entrar hace 5 días; responde por audio (3)"}]
    prompt = build_nudge_prompt(people, [], [], "jueves 5/11 09:00")
    assert "intensidad baja · pedidos de datos disponibles esta semana: 0 · perfil professional" in prompt
    assert "responde por audio" in prompt and "tensiómetro" in prompt
    assert "### professional" in prompt and "Cómo pedir un dato" in prompt
