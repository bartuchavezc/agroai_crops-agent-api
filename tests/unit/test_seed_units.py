import pytest

from src.application.inventory.units import (
    SeedWeightRequiredError,
    as_seeds,
    convert,
    effective_tsw,
    equivalent,
    normalize_tags,
    normalize_unit,
)


def test_normalize_unit():
    assert normalize_unit(" Gr. ") == "gramos"
    assert normalize_unit("u") == "semillas"
    assert normalize_unit("plantines") is None


def test_convert_both_ways():
    assert convert(16, "semillas", "gramos", 3.0) == pytest.approx(0.048)
    assert convert(12, "gramos", "semillas", 3.0) == pytest.approx(4000)
    assert convert(5, "gr", "gramos", None) == 5


def test_convert_needs_weight():
    with pytest.raises(SeedWeightRequiredError):
        convert(16, "semillas", "gramos", None)


def test_lot_weight_overrides_crop():
    assert effective_tsw(2.5, 3.0) == 2.5
    assert effective_tsw(None, 3.0) == 3.0
    assert effective_tsw(0, None) is None


def test_equivalent_and_as_seeds():
    assert equivalent(12, "gramos", 3.0) == (pytest.approx(4000), "semillas")
    assert equivalent(12, "gramos", None) == (None, None)
    assert as_seeds(12, "gramos", 3.0) == pytest.approx(4000)
    assert as_seeds(7, "semillas", None) == 7
    assert as_seeds(7, "plantines", 3.0) is None


def test_normalize_tags():
    assert normalize_tags([" Prueba ", "prueba", "", "Semillas  Nativas"]) == ["prueba", "semillas nativas"]
