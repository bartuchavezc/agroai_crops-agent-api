import pytest
from pydantic import ValidationError

from src.application.farm.schemas import LayoutObject
from src.application.farm.service import _octant_from_xy
from src.application.farm.site import latlon_to_local_m, polygon_area, site_polygon_m


def _field(**overrides):
    from datetime import datetime, timezone
    from uuid import uuid4

    from src.application.farm.schemas import FieldRead

    base = dict(
        id=uuid4(), account_id=uuid4(), name="Huerta", latitude=-34.6, longitude=-58.4,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    return FieldRead(**{**base, **overrides})


def test_legacy_point_objects_still_load_as_small_circles():
    obj = LayoutObject(id="a", type="arbol", label="Ligustro", x_m=3, y_m=4, height_m=5, source="photo_ai")
    assert (obj.kind, obj.x_m, obj.y_m) == ("circle", 3, 4)


def test_polygon_and_polyline_need_enough_points_and_get_a_centroid():
    poly = LayoutObject(id="p", type="pileta", label="Pileta", kind="polygon", points=[(0, 0), (4, 0), (4, 2), (0, 2)])
    assert (poly.x_m, poly.y_m) == (2, 1)
    with pytest.raises(ValidationError):
        LayoutObject(id="p", type="pileta", label="x", kind="polygon", points=[(0, 0), (1, 1)])
    with pytest.raises(ValidationError):
        LayoutObject(id="w", type="pared", label="x", kind="polyline", points=[(0, 0)])


def test_octant_uses_the_centroid_of_shapes():
    wall = LayoutObject(id="w", type="pared", label="Pared", kind="polyline", points=[(-5, 20), (5, 20)], height_m=3)
    assert _octant_from_xy(wall.x_m, wall.y_m) == "N"


def test_latlon_projection_is_in_meters_with_north_up():
    x, y = latlon_to_local_m(-34.6 + 0.001, -58.4, -34.6, -58.4)
    assert (x, y) == (pytest.approx(0, abs=1e-6), pytest.approx(110.54, abs=0.01))
    east, _ = latlon_to_local_m(-34.6, -58.4 + 0.001, -34.6, -58.4)
    assert east == pytest.approx(111.32 * 0.8231, abs=0.5)  # cos(34.6deg) ~ 0.8231


def test_site_polygon_prefers_drawn_terrain_then_boundary_then_rectangle():
    rect = _field(length_m=40, width_m=18)
    assert polygon_area(site_polygon_m(rect)) == pytest.approx(720)
    boundary = [(-34.6, -58.4), (-34.6, -58.399), (-34.599, -58.399), (-34.599, -58.4)]
    with_boundary = _field(length_m=40, width_m=18, boundary=boundary)
    assert polygon_area(site_polygon_m(with_boundary)) == pytest.approx(110.54 * 91.6, rel=0.02)
    drawn = LayoutObject(
        id="t", type="terreno", label="Terreno", kind="polygon", points=[(0, 0), (10, 0), (10, 10), (0, 10)]
    )
    assert polygon_area(site_polygon_m(_field(boundary=boundary, layout_objects=[drawn]))) == pytest.approx(100)
    assert site_polygon_m(_field()) is None
