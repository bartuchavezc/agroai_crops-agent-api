from uuid import uuid4

from src.agent.reasoning.zone_photos import group_parts, overview_parts, photo_count, zone_photos
from src.application.reports.schemas import PhotoRole

TOMATO, LETTUCE = str(uuid4()), str(uuid4())
CROPS = {TOMATO: "Tomate", LETTUCE: "Lechuga"}
# Stand-ins for the model-ready images: anything but a str (labels are the str parts).
G, T, L = b"general", b"tomate", b"lechuga"


def _images(parts):
    return [p for p in parts if not isinstance(p, str)]


def _walk():
    """A guided walk's zone: a general shot, a tomato close-up, a follow-up of the lettuce."""
    return zone_photos(
        [G, T, L],
        [
            PhotoRole(role="general"),
            PhotoRole(role="detalle", lot_id=TOMATO, hint="brotes nuevos"),
            PhotoRole(role="seguimiento", lot_id=LETTUCE, hint="envés de las hojas"),
        ],
    )


def test_without_roles_every_pass_sees_every_photo_unlabeled():
    photos = zone_photos([G, T], [])
    assert overview_parts(photos, CROPS) == [G, T]
    assert group_parts(photos, [TOMATO], CROPS) == [G, T]


def test_roles_that_dont_match_the_photos_are_ignored():
    photos = zone_photos([G, T], [PhotoRole(role="general")])
    assert all(p.role is None for p in photos)
    assert group_parts(photos, [TOMATO], CROPS) == [G, T]


def test_overview_gets_only_the_general_shots_labeled():
    parts = overview_parts(_walk(), CROPS)
    assert parts == ["Foto 1: vista general de la zona.", G]
    assert photo_count(parts) == 1


def test_a_group_gets_the_general_shots_and_its_own_close_ups():
    tomato = group_parts(_walk(), [TOMATO], CROPS)
    assert _images(tomato) == [G, T]
    assert f"Foto 2: primer plano de Tomate (lot_id={TOMATO}) — se pidió: brotes nuevos." in tomato

    lettuce = group_parts(_walk(), [LETTUCE], CROPS)
    assert _images(lettuce) == [G, L]
    assert any(isinstance(p, str) and "Foto 3: foto de seguimiento de algo ya visto de Lechuga" in p for p in lettuce)


def test_a_close_up_of_the_whole_zone_goes_to_every_group():
    photos = zone_photos([G, T], [PhotoRole(role="general"), PhotoRole(role="detalle")])
    assert _images(group_parts(photos, [LETTUCE], CROPS)) == [G, T]


def test_falls_back_to_every_photo_when_nothing_fits():
    # No general shot: the overview reads the close-ups, and a group with no close-up of its own still sees them.
    photos = zone_photos([T], [PhotoRole(role="detalle", lot_id=TOMATO)])
    assert photo_count(overview_parts(photos, CROPS)) == 1
    assert photo_count(group_parts(photos, [LETTUCE], CROPS)) == 1
