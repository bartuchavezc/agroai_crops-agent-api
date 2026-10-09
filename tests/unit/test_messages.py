from src.shared.domain.locale import localized
from src.shared.domain.messages import adapt


def test_adapt_swaps_only_the_listed_words_of_the_locale():
    text = "Plantín en almácigo: Ralear dejando 10 cm; revisar el cantero"
    assert adapt(text, "es-AR") == text and adapt(text, None) == text
    mx = adapt(text, "es-MX")
    assert mx == "Plantín en semillero: Aclarar dejando 10 cm; revisar el cama"
    assert adapt("Plantín en almácigo", "es-CO") == "Plantín en semillero"
    assert adapt("almácigos", "es-MX") == "almácigos"  # whole words only
    assert adapt("", "es-MX") == ""


def test_localized_names_fall_back_to_the_neutral_one():
    names = {"es-MX": "Jitomate", "es": "Tomate (genérico)"}
    assert localized("Tomate", names, "es-MX") == "Jitomate"
    assert localized("Tomate", names, "es-CO") == "Tomate (genérico)"
    assert localized("Tomate", {}, "es-MX") == "Tomate" and localized("Tomate", None, None) == "Tomate"
