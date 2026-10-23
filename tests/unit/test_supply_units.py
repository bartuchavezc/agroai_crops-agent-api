import pytest

from src.application.supplies.units import convert, normalize
from src.shared.utils.errors import InvalidInputError


def test_units_normalize_and_convert_within_their_dimension():
    assert [normalize(u) for u in ("Litros", "cc", "Kilos", "bidones")] == ["l", "ml", "kg", "unidad"]
    assert normalize("puñado") is None
    assert convert(250, "ml", "l") == 0.25
    assert convert(2, "kg", "g") == 2000
    assert convert(3, "unidades", "unidad") == 3


def test_volume_and_weight_dont_mix_without_a_density():
    with pytest.raises(InvalidInputError):
        convert(1, "l", "kg")
    with pytest.raises(InvalidInputError):
        convert(1, "puñado", "kg")
