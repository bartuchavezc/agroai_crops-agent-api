from datetime import datetime

from src.agent.prompts.knowledge import modules_for, style_for
from src.agent.prompts.voice import local_now_label, localize, voice_for
from src.shared.domain.locale import default_locale, default_timezone, today_in, validate_timezone

import pytest


def test_localize_swaps_only_the_language_phrase():
    text = "Sos un agrónomo.\n- Respondé en español rioplatense, claro y concreto."
    assert "español rioplatense" in localize(text, "AR") and "voseo" in localize(text, "AR")
    assert "español de México (tuteo, sin voseo)" in localize(text, "MX")
    assert localize(text, "MX").startswith("Sos un agrónomo.")  # the rest is untouched
    assert localize(text, None) == localize(text, "AR")  # Argentina by default


def test_voice_blocks_are_country_specific():
    assert "voseo" in voice_for("AR") and "SENASA" in voice_for("AR") and "hemisferio sur" in voice_for("AR").lower()
    mx = voice_for("MX")
    assert "tuteo" in mx and "jitomate" in mx and "COFEPRIS" in mx and "Hemisferio norte" in mx
    assert voice_for("XX") == voice_for("AR")


def test_modules_follow_the_country_and_keep_the_shared_practices():
    mx = modules_for("MX", "guardian", set(), [])
    assert "## Agronomía general (México)" in mx and "## Horticultura a campo abierto" in mx
    assert "Argentina" not in mx.split("## Horticultura a campo abierto")[0]
    ar = modules_for("AR", "guardian", set(), [])
    assert "## Agronomía general (Argentina)" in ar
    grains_mx = modules_for("MX", "guardian", {"Poaceae"}, [])
    assert "Cultivos extensivos / granos (México)" in grains_mx
    assert "## Estilo: El Guardián" in style_for("guardian")


def test_local_now_label_uses_spanish_weekdays():
    assert local_now_label(datetime(2026, 10, 7, 15, 30)) == "miércoles 07/10/2026 15:30"


def test_locale_helpers():
    assert default_timezone("MX") == "America/Mexico_City" and default_locale("MX") == "es-MX"
    assert default_timezone("??") == "America/Argentina/Buenos_Aires"
    assert validate_timezone("America/Mexico_City") == "America/Mexico_City"
    with pytest.raises(ValueError):
        validate_timezone("Mars/Olympus")
    assert all(today_in(tz) for tz in ("America/Mexico_City", "garbage", None))  # bad/missing zone -> default


def test_colombia_has_its_own_voice_knowledge_and_sources():
    co = voice_for("CO")
    assert "tuteo" in co and "ICA" in co and "ahuyama" in co and "COP" in co and co != voice_for("AR")
    assert "español de Colombia (tuteo, sin voseo)" in localize("Respondé en español rioplatense.", "CO")
    modules = modules_for("CO", "guardian", set(), [])
    assert "## Agronomía general (Colombia)" in modules and "piso térmico" in modules
    assert "Agronomía general (Argentina)" not in modules and "Agronomía general (México)" not in modules
    assert default_timezone("CO") == "America/Bogota" and default_locale("CO") == "es-CO"
