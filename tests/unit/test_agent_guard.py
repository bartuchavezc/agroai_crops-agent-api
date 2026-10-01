"""Which user messages count as confirming a pending deletion."""
import pytest

from src.agent.tools.guard import is_affirmative


@pytest.mark.parametrize("message", ["sí", "Si", "dale", "Sí, dale, borralo", "ok confirmo", "OK!", "sí, eliminalo"])
def test_short_yes_confirms(message):
    assert is_affirmative(message)


@pytest.mark.parametrize(
    "message",
    [
        "no",
        "no, esperá",
        "sí no, mejor no",
        "",
        "¿cuándo cosecho?",
        "gracias",
        "dale que sí, y además contame cuándo conviene sembrar las habas en La Plata este año",
    ],
)
def test_anything_else_does_not(message):
    assert not is_affirmative(message)
