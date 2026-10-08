from decimal import Decimal

from src.application.products.models import normalize_name
from src.scripts.seed_products import IngredientIndex, match_key, parse_composition


def test_normalize_name_strips_accents_case_and_spaces():
    assert normalize_name("  Tizón   tardío ") == "TIZON TARDIO"
    assert normalize_name(None) == ""


def test_single_component_with_unit():
    [c] = parse_composition("PIRIMETANIL 40% p/v")
    assert (c.raw_name, c.concentration, c.unit) == ("PIRIMETANIL", Decimal("40"), "p/v")


def test_decimal_comma_and_multiple_components():
    a, b = parse_composition("FLUDIOXONIL 2,5%, METALAXIL -M 1%")
    assert (a.raw_name, a.concentration) == ("FLUDIOXONIL", Decimal("2.5"))
    assert (b.raw_name, b.concentration) == ("METALAXIL -M", Decimal("1"))


def test_concentration_without_leading_zero():
    [c] = parse_composition("FIPRONIL ,003%")
    assert c.concentration == Decimal("0.003")
    names = [c.raw_name for c in parse_composition("ACIDO INDOL 3 BUTIRICO ,85%, KINETINA ,15%")]
    assert names == ["ACIDO INDOL 3 BUTIRICO", "KINETINA"]


def test_unparseable_text_is_kept_whole_and_empty_is_empty():
    [c] = parse_composition("EXTRACTO DE ALGAS")
    assert (c.raw_name, c.concentration) == ("EXTRACTO DE ALGAS", None)
    assert parse_composition("") == []


def test_variants_with_different_punctuation_share_an_ingredient():
    import uuid

    known = uuid.uuid4()
    index = IngredientIndex({"2,4-D": (known, "2,4-D")})
    assert match_key("2,4 D") == match_key("2,4-D")
    assert index.resolve("2,4 D", "senasa") == known
    assert index.new_rows == [] and index.new_aliases[0]["alias"] == "2,4 D"
    assert index.resolve("GLIFOSATO", "senasa") != known and len(index.new_rows) == 1
