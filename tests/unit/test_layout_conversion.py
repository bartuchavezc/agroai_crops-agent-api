import math

import pytest

from src.agent.schemas import ImagePoint, PhotoSceneExtraction, ReferenceMatch, SceneElementGuess
from src.application.farm.declination import magnetic_to_true_bearing
from src.application.farm.layout_conversion import (
    CameraModel,
    default_camera_position,
    ground_point,
    height_above_ground,
    pitch_from_horizon,
    scene_to_layout_objects,
    to_plan,
)
from src.application.farm.service import _octant_from_xy


def _row_below_horizon(cam: CameraModel, degrees: float) -> float:
    """Image row whose ray points `degrees` below the (pitch 0) horizon."""
    return 0.5 + cam.focal * math.tan(math.radians(degrees))


def _element(**overrides) -> SceneElementGuess:
    base = dict(
        label="Pared", type="pared", kind="polyline", estimated_height_m=2.5, confidence=0.8,
        ground_points=[ImagePoint(x=0.3, y=0.7), ImagePoint(x=0.7, y=0.7)],
    )
    return SceneElementGuess(**{**base, **overrides})


def test_ground_distance_follows_height_over_tan_of_the_angle_below_the_horizon():
    cam = CameraModel(height_m=1.5, pitch_deg=0.0, aspect=1.0)
    right, forward = ground_point(cam, 0.5, _row_below_horizon(cam, 10))
    assert right == pytest.approx(0, abs=1e-6)
    assert forward == pytest.approx(1.5 / math.tan(math.radians(10)), rel=1e-6)  # 8.51 m


def test_points_right_of_center_land_to_the_right():
    cam = CameraModel(aspect=1.0)
    right, forward = ground_point(cam, 0.8, _row_below_horizon(cam, 10))
    assert right > 0 and forward > 0


def test_camera_height_scales_every_distance():
    row = _row_below_horizon(CameraModel(aspect=1.0), 12)
    near = ground_point(CameraModel(height_m=1.0, aspect=1.0), 0.5, row)[1]
    far = ground_point(CameraModel(height_m=2.0, aspect=1.0), 0.5, row)[1]
    assert far == pytest.approx(2 * near)


def test_horizon_pitch_puts_the_horizon_at_infinity():
    cam = CameraModel(aspect=0.75)
    pitch = pitch_from_horizon(cam.aspect, horizon_v=0.4)  # horizon above center -> camera looks down
    assert pitch < 0
    tilted = cam.with_pitch(pitch)
    _, up, _ = tilted.ray(0.5, 0.4)
    assert up == pytest.approx(0, abs=1e-9)
    # a point just below that horizon is far; the same row without the tilt would be nearer than the horizon
    assert ground_point(tilted, 0.5, 0.42)[1] > 15


def test_points_at_or_above_the_horizon_are_clamped_not_infinite():
    cam = CameraModel(aspect=1.0, max_distance_m=60)
    right, forward = ground_point(cam, 0.5, 0.2)  # sky
    assert math.hypot(right, forward) == pytest.approx(60)


def test_height_is_recovered_from_the_top_edge():
    cam = CameraModel(height_m=1.5, aspect=1.0)
    d = 10.0
    base = (0.0, d)
    top_row = 0.5 - cam.focal * (3.0 - 1.5) / d  # a 3 m wall at 10 m, seen from 1.5 m up
    assert height_above_ground(cam, base, 0.5, top_row) == pytest.approx(3.0, rel=1e-6)


def test_to_plan_rotates_by_true_bearing():
    assert to_plan((0, 10), 0, (0, 0)) == pytest.approx((0, 10))  # forward while facing north -> north
    assert to_plan((0, 10), 90, (0, 0)) == pytest.approx((10, 0))  # facing east -> east
    assert to_plan((5, 0), 0, (0, 0)) == pytest.approx((5, 0))  # right of a north-facing camera -> east
    assert to_plan((5, 0), 90, (2, 3)) == pytest.approx((2, -2))  # right of an east-facing camera -> south


def test_default_camera_stands_on_the_edge_behind_the_view():
    rect = [(-9, -20), (9, -20), (9, 20), (-9, 20)]
    x, y = default_camera_position(rect, bearing_deg=0)  # looking north -> standing at the south edge
    assert x == pytest.approx(0, abs=1e-6) and -20 <= y < -17
    x, y = default_camera_position(rect, bearing_deg=90)  # looking east -> the west edge
    assert x < -7 and y == pytest.approx(0, abs=1e-6)
    assert default_camera_position(None, 45) == (0.0, 0.0)


def test_scene_becomes_plan_elements_with_shapes_heights_and_photo_id():
    cam = CameraModel(height_m=1.5, aspect=1.0)
    row = _row_below_horizon(cam, 10)
    extraction = PhotoSceneExtraction(
        scene_description="patio",
        elements=[
            _element(ground_points=[ImagePoint(x=0.3, y=row), ImagePoint(x=0.7, y=row)], top_y=row - 0.2),
            _element(
                label="Pino", type="arbol", kind="circle", ground_points=[ImagePoint(x=0.5, y=row)], crown_width=0.2
            ),
            _element(
                label="Pileta", type="pileta", kind="polygon", estimated_height_m=1,
                ground_points=[ImagePoint(x=0.2, y=row), ImagePoint(x=0.4, y=row), ImagePoint(x=0.4, y=row + 0.1)],
            ),
        ],
    )
    wall, tree, pool = scene_to_layout_objects(extraction, cam, bearing_deg=0, camera_xy=(0, -20), photo_id="p1")
    assert (wall.kind, wall.type, wall.photo_id) == ("polyline", "pared", "p1")
    assert wall.points[0][1] == pytest.approx(-20 + 8.51, abs=0.02)  # 8.51 m north of where the camera stands
    assert wall.thickness_m == 0.3 and 1.0 < wall.height_m < 3.0  # measured from its top edge, not the 2.5 m guess
    assert (tree.kind, tree.radius_m is not None and tree.radius_m > 0.3) == ("circle", True)
    assert (pool.kind, pool.height_m) == ("polygon", 0.0)  # flat things cast no shadow


def test_reference_note_calibrates_the_whole_scene():
    cam = CameraModel(height_m=1.5, aspect=1.0)
    near, far = _row_below_horizon(cam, 20), _row_below_horizon(cam, 5)  # ~4.1 m and ~17 m
    extraction = PhotoSceneExtraction(
        scene_description="patio",
        elements=[
            _element(label="Poste", type="otro", kind="circle", ground_points=[ImagePoint(x=0.5, y=near)]),
            _element(label="Pared", ground_points=[ImagePoint(x=0.3, y=far), ImagePoint(x=0.7, y=far)]),
        ],
        reference=ReferenceMatch(object_index=0, distance_m=8.0, height_m=3.0),
    )
    uncal = PhotoSceneExtraction(**{**extraction.model_dump(), "reference": None})
    pole, wall = scene_to_layout_objects(extraction, cam, 0, (0, 0))
    pole0, wall0 = scene_to_layout_objects(uncal, cam, 0, (0, 0))
    k = 8.0 / pole0.y_m  # the anchor lands exactly on the stated distance...
    assert pole.y_m == pytest.approx(8.0, abs=0.02)
    assert wall.points[0][1] == pytest.approx(wall0.points[0][1] * k, rel=0.01)  # ...and everything scales with it
    assert pole.height_m == 3.0


def test_absurd_reference_is_clamped():
    cam = CameraModel(aspect=1.0)
    row = _row_below_horizon(cam, 10)
    extraction = PhotoSceneExtraction(
        scene_description="x",
        elements=[_element(kind="circle", ground_points=[ImagePoint(x=0.5, y=row)])],
        reference=ReferenceMatch(object_index=0, distance_m=190),
    )
    (obj,) = scene_to_layout_objects(extraction, cam, 0, (0, 0))
    assert obj.y_m == pytest.approx(1.5 / math.tan(math.radians(10)) * 4, rel=0.01)  # capped at 4x


@pytest.mark.parametrize(
    "x, y, octant",
    [(0, 5, "N"), (5, 5, "NE"), (5, 0, "E"), (5, -5, "SE"), (0, -5, "S"), (-5, -5, "SO"), (-5, 0, "O"), (-5, 5, "NO")],
)
def test_octant_from_xy_follows_compass_axes(x, y, octant):
    assert _octant_from_xy(x, y) == octant


def test_octant_wraps_around_north():
    assert _octant_from_xy(-0.5, 5) == "N"  # just west of due north still rounds to N


def test_magnetic_bearing_is_corrected_with_declination():
    # Buenos Aires: true north is ~10 degrees west of magnetic, so a magnetic 90 reads ~80 true.
    assert magnetic_to_true_bearing(90, -34.6, -58.4) == pytest.approx(80, abs=3)
    assert magnetic_to_true_bearing(90, None, None) == 90
