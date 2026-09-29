import math

import pytest

from src.application.farm.schemas import LayoutObject
from src.application.farm.shadows import cells_inside, footprint, shadow_of, sun_map
from src.application.farm.solar import solar_positions


def _wall(height=3.0, points=((-5, 10), (5, 10)), thickness=0.4):
    return LayoutObject(
        id="w", type="pared", label="Pared", kind="polyline", points=list(points),
        thickness_m=thickness, height_m=height,
    )


def test_shadow_length_is_height_over_tan_of_the_altitude_pointing_away_from_the_sun():
    # Sun due south (azimuth 180) at 45 degrees: a 3 m wall at y=10 throws a 3 m shadow to the north.
    shadow = shadow_of(_wall(), altitude_deg=45, azimuth_deg=180)
    minx, miny, maxx, maxy = shadow.bounds
    assert maxy == pytest.approx(10.2 + 3.0, abs=0.01)
    assert miny == pytest.approx(9.8, abs=0.01)
    assert (minx, maxx) == (pytest.approx(-5), pytest.approx(5))


def test_shadow_points_away_from_the_sun_in_every_direction():
    # sun in the west -> the shadow falls east
    east = shadow_of(_wall(points=((0, 0), (0, 4))), altitude_deg=45, azimuth_deg=270)
    assert east.bounds[2] == pytest.approx(0.2 + 3.0, abs=0.01)
    low = shadow_of(_wall(), altitude_deg=15, azimuth_deg=180)  # lower sun -> longer shadow
    assert low.bounds[3] == pytest.approx(10.2 + 3.0 / math.tan(math.radians(15)), abs=0.01)


def test_flat_things_and_a_grazing_sun_cast_no_shadow():
    pool = LayoutObject(
        id="p", type="pileta", label="Pileta", kind="polygon", points=[(0, 0), (4, 0), (4, 2), (0, 2)], height_m=0
    )
    assert shadow_of(pool, 45, 180) is None
    assert shadow_of(_wall(), 0.5, 180) is None


def test_a_tree_shadow_is_its_crown_shifted_not_a_swept_solid():
    tree = LayoutObject(id="t", type="arbol", label="Pino", kind="circle", x_m=0, y_m=0, radius_m=2, height_m=6)
    shadow = shadow_of(tree, altitude_deg=45, azimuth_deg=180)
    assert shadow.centroid.y == pytest.approx(6.0, abs=0.1)
    assert shadow.area == pytest.approx(footprint(tree).area, rel=0.01)  # the crown's disc, not stretched


def test_solar_positions_match_the_known_noon_altitude():
    # Buenos Aires (-34.6): winter solstice noon altitude = 90 - 34.6 - 23.45 = 31.95 deg, sun due north.
    noon = min(solar_positions(-34.6, "invierno", 15), key=lambda s: abs(s.hour - 12))
    assert noon.altitude_deg == pytest.approx(31.95, abs=0.5)
    assert noon.azimuth_deg == pytest.approx(0, abs=1) or noon.azimuth_deg == pytest.approx(360, abs=1)


def test_sun_map_without_obstacles_gives_every_cell_the_full_day():
    site = [(-10, -10), (10, -10), (10, 10), (-10, 10)]
    result = sun_map([], site, latitude=-34.6, season="verano")
    assert result.mean_hours == pytest.approx(result.max_hours, abs=0.05)
    assert result.max_hours > 13  # summer day in Buenos Aires
    assert result.site_area_m2 == pytest.approx(400)


def test_a_wall_to_the_north_shades_the_terrain_side_that_faces_it_in_winter():
    # Southern hemisphere: the winter sun sits in the north, so a tall wall north of the terrain shades it.
    site = [(-10, -10), (10, -10), (10, 10), (-10, 10)]
    wall = _wall(height=6, points=((-10, 12), (10, 12)))
    shaded = sun_map([wall], site, -34.6, "invierno")
    open_ = sun_map([], site, -34.6, "invierno")
    assert shaded.mean_hours < open_.mean_hours
    north = [h for _, y, h in shaded.cells if y > 5]
    south = [h for _, y, h in shaded.cells if y < -5]
    assert sum(north) / len(north) < sum(south) / len(south)  # nearest the wall loses the most sun
    assert shaded.timeline == []  # shadows are only returned when asked for
    with_shadows = sun_map([wall], site, -34.6, "invierno", include_shadows=True)
    assert with_shadows.timeline and any(m.shadows for m in with_shadows.timeline)


def test_the_same_wall_barely_matters_in_summer_when_the_sun_is_high():
    site = [(-10, -10), (10, -10), (10, 10), (-10, 10)]
    wall = _wall(height=6, points=((-10, 12), (10, 12)))
    winter_loss = sun_map([], site, -34.6, "invierno").mean_hours - sun_map([wall], site, -34.6, "invierno").mean_hours
    summer_loss = sun_map([], site, -34.6, "verano").mean_hours - sun_map([wall], site, -34.6, "verano").mean_hours
    assert winter_loss > summer_loss


def test_terrain_summary_reports_shade_percentages_and_zones():
    from src.application.farm.service import _summarize_sun_map

    site = [(-10, -10), (10, -10), (10, 10), (-10, 10)]
    wall = _wall(height=8, points=((-10, 12), (10, 12)))
    summary = _summarize_sun_map(sun_map([wall], site, -34.6, "invierno"), site)
    assert 0 < summary.shade_percent < 100
    assert summary.full_sun_percent + summary.part_shade_percent + summary.shade_percent == pytest.approx(100, abs=0.2)
    assert "N" in summary.shadiest_zone  # the wall is to the north
    open_summary = _summarize_sun_map(sun_map([], site, -34.6, "verano"), site)
    assert open_summary.sunniest_zone == "toda el área por igual"


def test_the_sun_grid_is_one_square_meter_per_cell():
    site = [(0, 0), (18, 0), (18, 42), (0, 42)]  # the 18 x 42 m entorno
    result = sun_map([], site, -34.6, "verano")
    assert result.cell_size_m == 1.0
    assert len(result.cells) == 18 * 42  # one cell per square meter
    xs = sorted({x for x, _, _ in result.cells})
    assert xs[0] == 0.5 and xs[-1] == 17.5  # cell centers, 1 m apart
    assert all(h == pytest.approx(result.max_hours, abs=0.01) for _, _, h in result.cells)  # no obstacles: full day


def test_a_huge_area_gets_coarser_cells_instead_of_an_unbounded_grid():
    big = [(0, 0), (500, 0), (500, 500), (0, 500)]
    result = sun_map([], big, -34.6, "verano", max_cells=6000)
    assert result.cell_size_m > 1 and len(result.cells) <= 6000


def test_each_cell_gets_its_own_hours_from_the_shadows_cast_over_the_grid():
    site = [(0, 0), (20, 0), (20, 20), (0, 20)]
    wall = _wall(height=6, points=((0, 22), (20, 22)))  # north of the area: in winter its shade reaches the north cells
    result = sun_map([wall], site, -34.6, "invierno")
    by_row = {}
    for _, y, h in result.cells:
        by_row.setdefault(y, []).append(h)
    assert len({round(h, 2) for hs in by_row.values() for h in hs}) > 3  # a gradient of hours, not one number
    assert sum(by_row[19.5]) / 20 < sum(by_row[0.5]) / 20  # the row next to the wall gets less sun than the far one


def test_the_campo_average_is_computed_apart_from_the_entornos():
    entorno = [(0, 0), (20, 0), (20, 20), (0, 20)]
    wall = _wall(height=6, points=((0, 22), (20, 22)))
    result = sun_map([wall], entorno, -34.6, "invierno")
    near_wall = cells_inside(result.cells, [(2, 15), (18, 15), (18, 19), (2, 19)])
    far_side = cells_inside(result.cells, [(2, 1), (18, 1), (18, 5), (2, 5)])
    assert len(near_wall) == 16 * 4 and len(far_side) == 16 * 4
    assert sum(c[2] for c in near_wall) / 64 < sum(c[2] for c in far_side) / 64
    assert cells_inside(result.cells, [(1, 1)]) == []
