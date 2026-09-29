import pytest

from src.agent.schemas import LayoutObjectGuess
from src.application.farm.layout_conversion import DEPTH_METERS, guess_to_layout_object
from src.application.farm.service import _octant_from_xy


def _guess(horizontal="centro", depth="medio", type_="arbol", height=6.0) -> LayoutObjectGuess:
    return LayoutObjectGuess(
        label="Ligustro",
        type=type_,
        horizontal_position=horizontal,
        depth_position=depth,
        estimated_height_m=height,
        confidence=0.7,
    )


def test_centered_object_lies_straight_ahead_of_the_camera():
    north = guess_to_layout_object(_guess(), camera_bearing_degrees=0)
    assert north.x_m == pytest.approx(0, abs=0.01)
    assert north.y_m == pytest.approx(DEPTH_METERS["medio"], abs=0.01)

    east = guess_to_layout_object(_guess(), camera_bearing_degrees=90)
    assert east.x_m == pytest.approx(DEPTH_METERS["medio"], abs=0.01)
    assert east.y_m == pytest.approx(0, abs=0.01)


def test_right_of_frame_is_clockwise_of_the_view_direction():
    # Facing north, "derecha" must land on the east side; facing south, on the west side.
    facing_north = guess_to_layout_object(_guess(horizontal="derecha"), camera_bearing_degrees=0)
    assert facing_north.x_m > 0 and facing_north.y_m > 0
    facing_south = guess_to_layout_object(_guess(horizontal="derecha"), camera_bearing_degrees=180)
    assert facing_south.x_m < 0 and facing_south.y_m < 0


def test_depth_buckets_use_a_fixed_scale_and_keep_distance_from_the_camera():
    for depth, meters in DEPTH_METERS.items():
        obj = guess_to_layout_object(_guess(horizontal="izquierda", depth=depth), camera_bearing_degrees=37)
        assert (obj.x_m**2 + obj.y_m**2) ** 0.5 == pytest.approx(meters, abs=0.05)


def test_conversion_keeps_the_ai_facts_and_marks_the_source():
    obj = guess_to_layout_object(_guess(type_="pared", height=3.0), camera_bearing_degrees=0)
    assert (obj.type, obj.label, obj.height_m) == ("pared", "Ligustro", 3.0)
    assert (obj.source, obj.confidence) == ("photo_ai", 0.7)
    assert len(obj.id) == 32


@pytest.mark.parametrize(
    "x, y, octant",
    [(0, 5, "N"), (5, 5, "NE"), (5, 0, "E"), (5, -5, "SE"), (0, -5, "S"), (-5, -5, "SO"), (-5, 0, "O"), (-5, 5, "NO")],
)
def test_octant_from_xy_follows_compass_axes(x, y, octant):
    assert _octant_from_xy(x, y) == octant


def test_octant_wraps_around_north():
    assert _octant_from_xy(-0.5, 5) == "N"  # just west of due north still rounds to N


def test_reference_note_calibrates_distance_and_height_of_the_whole_scene():
    from src.agent.schemas import PhotoLayoutExtraction, ReferenceMatch
    from src.application.farm.layout_conversion import layout_objects_from_extraction

    pole = _guess(depth="medio", type_="estructura", height=2.0)  # assumed 8 m away, ~2 m tall
    tree = _guess(depth="fondo", height=6.0)  # assumed 15 m away
    extraction = PhotoLayoutExtraction(
        scene_description="patio",
        objects=[pole, tree],
        reference=ReferenceMatch(object_index=0, distance_m=4.0, height_m=3.0),
    )
    pole_obj, tree_obj = layout_objects_from_extraction(extraction, camera_bearing_degrees=0)
    assert (pole_obj.y_m, pole_obj.height_m) == (pytest.approx(4.0), 3.0)  # the anchor gets the exact numbers
    assert tree_obj.y_m == pytest.approx(15.0 * 0.5, abs=0.01)  # distances halve (4 m stated vs 8 m assumed)
    assert tree_obj.height_m == pytest.approx(9.0)  # heights x1.5 (3 m stated vs 2 m guessed)


def test_missing_or_invalid_reference_leaves_the_default_scale():
    from src.agent.schemas import PhotoLayoutExtraction, ReferenceMatch
    from src.application.farm.layout_conversion import layout_objects_from_extraction

    bad = PhotoLayoutExtraction(
        scene_description="x", objects=[_guess()], reference=ReferenceMatch(object_index=5, distance_m=1.0)
    )
    assert layout_objects_from_extraction(bad, 0)[0].y_m == pytest.approx(DEPTH_METERS["medio"])


def test_magnetic_bearing_is_corrected_with_declination():
    from src.application.farm.declination import magnetic_to_true_bearing

    # Buenos Aires: true north is ~10 degrees west of magnetic, so a magnetic 90 reads ~80 true.
    assert magnetic_to_true_bearing(90, -34.6, -58.4) == pytest.approx(80, abs=3)
    assert magnetic_to_true_bearing(90, None, None) == 90
