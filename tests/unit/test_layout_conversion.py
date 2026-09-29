import math

import pytest

from src.agent.prompts.farm import LAYOUT_EXAMPLES, LAYOUT_EXTRACTION_INSTRUCTION, format_layout_context
from src.agent.schemas import PlanElement, PlanExtraction, PlanPoint
from src.application.farm.declination import magnetic_to_true_bearing
from src.application.farm.layout_conversion import (
    campo_element,
    default_camera_position,
    enu_to_frame,
    entorno_from_measures,
    frame_to_enu,
    plan_to_layout_objects,
)
from src.application.farm.service import _octant_from_xy
from tests.unit.test_layout_geometry import _field

FRAME_ENTORNO = [(-9, 0), (9, 0), (9, 42), (-9, 42)]


def test_frame_axes_follow_the_bearing():
    # camera at the origin looking north: +y is north, +x is east
    assert frame_to_enu((0, 10), (0, 0), 0) == pytest.approx((0, 10))
    assert frame_to_enu((5, 0), (0, 0), 0) == pytest.approx((5, 0))
    # looking east: forward is east, the photo's right is south
    assert frame_to_enu((0, 10), (0, 0), 90) == pytest.approx((10, 0))
    assert frame_to_enu((5, 0), (0, 0), 90) == pytest.approx((0, -5))
    # the camera's own position is added
    assert frame_to_enu((0, 10), (2, 3), 90) == pytest.approx((12, 3))


@pytest.mark.parametrize("bearing", [0, 37, 90, 230, 359])
def test_frame_round_trip(bearing):
    camera = (4.0, -7.5)
    back = enu_to_frame(frame_to_enu((3.2, 11.0), camera, bearing), camera, bearing)
    assert back == pytest.approx((3.2, 11.0))


@pytest.mark.parametrize("bearing", [0, 90, 230])
def test_entorno_from_measures_is_the_users_rectangle_with_the_camera_on_the_near_edge(bearing):
    outline, camera = entorno_from_measures(18, 42, bearing)
    frame = [enu_to_frame(p, camera, bearing) for p in outline]
    flat = [c for p in frame for c in p]
    assert flat == pytest.approx([c for p in FRAME_ENTORNO for c in p], abs=1e-6)  # 18 across, 42 to the far wall
    assert (sum(p[0] for p in outline) / 4, sum(p[1] for p in outline) / 4) == pytest.approx((0, 0), abs=1e-6)


def test_default_camera_stands_on_the_edge_behind_the_view():
    rect = [(-9, -20), (9, -20), (9, 20), (-9, 20)]
    x, y = default_camera_position(rect, bearing_deg=0)  # looking north -> standing at the south edge
    assert x == pytest.approx(0, abs=1e-6) and -20 <= y < -17
    x, y = default_camera_position(rect, bearing_deg=90)  # looking east -> the west edge
    assert x < -7 and y == pytest.approx(0, abs=1e-6)
    assert default_camera_position(None, 45) == (0.0, 0.0)


def _plan(*elements: PlanElement) -> PlanExtraction:
    return PlanExtraction(elements=list(elements))


def _el(**overrides) -> PlanElement:
    base = dict(label="Pared", type="pared", kind="polyline", height_m=2.4, confidence=0.8,
                points=[PlanPoint(x=-9, y=42), PlanPoint(x=9, y=42)])
    return PlanElement(**{**base, **overrides})


def test_plan_elements_are_converted_to_east_north_with_shape_height_and_photo_id():
    pool = _el(label="Pileta", type="pileta", kind="polygon", height_m=1.0,
               points=[PlanPoint(x=-5, y=8), PlanPoint(x=-1, y=8), PlanPoint(x=-1, y=14)])
    tree = _el(
        label="Pino", type="arbol", kind="circle", points=None, center=PlanPoint(x=2, y=45), radius_m=3, height_m=14
    )
    wall, pool_o, tree_o = plan_to_layout_objects(
        _plan(_el(), pool, tree), camera_enu=(0, -21), bearing_deg=0, entorno_frame=FRAME_ENTORNO, photo_id="p1"
    )
    assert (wall.kind, wall.type, wall.photo_id, wall.source) == ("polyline", "pared", "p1", "photo_ai")
    assert wall.points == [(-9, 21), (9, 21)]  # 42 m in front of a camera 21 m south of the origin
    assert wall.thickness_m == 0.3  # default for a wall
    assert (pool_o.kind, pool_o.height_m) == ("polygon", 0.0)  # flat things cast no shadow, whatever the model said
    assert (tree_o.kind, tree_o.x_m, tree_o.y_m, tree_o.radius_m) == ("circle", 2, 24, 3)


def test_bearing_rotates_the_result():
    (wall,) = plan_to_layout_objects(_plan(_el()), (0, 0), 90, FRAME_ENTORNO)
    assert wall.points[0][0] == pytest.approx(42)  # facing east: the far wall is 42 m east...
    assert wall.points[0][1] == pytest.approx(9) or wall.points[0][1] == pytest.approx(-9)  # ...and spans north-south


def test_everything_the_model_places_is_kept_even_far_away_and_only_absurd_numbers_are_pulled_in():
    def tree(label, x, y):
        return _el(label=label, type="arbol", kind="circle", points=None, center=PlanPoint(x=x, y=y), radius_m=3)

    neighbour, absurd = tree("Árbol del vecino", 6, 60), tree("Poste", 0, 5000)
    out = plan_to_layout_objects(_plan(neighbour, absurd), (0, 0), 0, FRAME_ENTORNO)
    assert [o.label for o in out] == ["Árbol del vecino", "Poste"]
    assert out[0].y_m == 60  # 18 m behind the far wall: kept as given
    assert out[1].y_m == 72  # 42 + 30 m margin: pulled back, not dropped


def test_elements_without_enough_geometry_are_skipped():
    bad = _el(kind="polygon", points=[PlanPoint(x=0, y=0), PlanPoint(x=1, y=1)])
    assert plan_to_layout_objects(_plan(bad), (0, 0), 0, FRAME_ENTORNO) == []


def test_few_shot_examples_are_valid_plan_extractions_and_use_the_same_context_format():
    for entorno, height, pitch, note, output in LAYOUT_EXAMPLES:
        extraction = PlanExtraction.model_validate(output)
        assert len(extraction.elements) >= 5
        context = format_layout_context(entorno, height, pitch, note)
        assert context in LAYOUT_EXTRACTION_INSTRUCTION  # the example shows exactly what a real request looks like
        # every example element lands in or near its entorno when converted (no wild coordinates in the prompt)
        assert plan_to_layout_objects(extraction, (0, 0), 0, entorno)


def test_context_tells_the_model_where_the_camera_is_and_the_measures():
    text = format_layout_context(FRAME_ENTORNO, 1.5, -4.0, "La pared está a 42 m")
    assert "(-9, 0) (9, 0) (9, 42) (-9, 42)" in text and "1.5 m" in text and "-4°" in text and "42 m" in text
    assert "(0, 0)" in text and "+Y" in text


def test_campo_is_drawn_from_the_fields_own_measures_never_the_entornos():
    field = _field(width_m=5, length_m=8)
    campo = campo_element(field, entorno=[(-9, -21), (9, -21), (9, 21), (-9, 21)])
    assert campo.type == "campo"
    xs, ys = [p[0] for p in campo.points], [p[1] for p in campo.points]
    assert (max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx((5, 8))  # the field's 5 x 8, not 18 x 42
    # squared up with the photo: with the camera looking east, the 8 m length runs east-west
    turned = campo_element(field, entorno=None, bearing_deg=90)
    txs, tys = [p[0] for p in turned.points], [p[1] for p in turned.points]
    assert (max(txs) - min(txs), max(tys) - min(tys)) == pytest.approx((8, 5))
    assert campo_element(_field(), entorno=None) is None  # no measures -> nothing drawn
    assert campo_element(_field(width_m=5, length_m=8, layout_objects=[campo]), None) is None  # only one campo


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


def test_rotation_helpers_do_not_drift():
    assert math.isclose(math.hypot(*frame_to_enu((3, 4), (0, 0), 123)), 5)


def test_plan_element_tolerates_out_of_range_values():
    from src.agent.schemas import PlanExtraction

    extraction = PlanExtraction.model_validate_json(
        '{"elements": [{"label": "Pino", "type": "muro", "kind": "circle", "center": {"x": 1, "y": 5},'
        ' "radius_m": 0, "height_m": 80, "confidence": 1.4},'
        ' {"label": "Cerco", "type": "cerco", "kind": "polyline", "points": [{"x": 0, "y": 1}, {"x": 3, "y": 1}],'
        ' "thickness_m": 0, "height_m": null}]}'
    )
    assert extraction.elements[0].type == "otro"
    assert extraction.elements[0].confidence == 1.0
    assert extraction.elements[1].height_m == 0.0
