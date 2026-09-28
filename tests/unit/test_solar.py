from src.application.farm.solar import Obstacle, compute_sun_exposure, sun_hours_by_octant


def test_no_obstacles_gets_some_sun_in_every_octant_except_due_south_over_the_year():
    # Buenos Aires (Southern Hemisphere, subtropical latitude): the sun's azimuth never actually reaches
    # due south from here, so S is the one octant that legitimately stays at zero all year — every other
    # octant should see some sun across the three seasons.
    result = compute_sun_exposure(latitude=-34.6, obstacles=[])
    octants = result.by_season["verano"]
    totals = {octant: sum(result.by_season[season][octant] for season in result.by_season) for octant in octants}
    assert totals["S"] == 0
    for octant, hours in totals.items():
        if octant != "S":
            assert hours > 0, octant


def test_obstacle_reduces_sun_in_its_own_octant_only():
    # Winter: midday sun altitude at this latitude (~32 degrees) is low enough for a tall-but-realistic
    # obstacle to fully block it, within the model's own blocking cap (60 degrees).
    baseline = sun_hours_by_octant(latitude=-34.6, obstacles=[], season="invierno")
    obstacle = [Obstacle(type="pared", height_m=10.0, direction="N")]
    blocked = sun_hours_by_octant(latitude=-34.6, obstacles=obstacle, season="invierno")

    assert blocked["N"] < baseline["N"]
    assert blocked["N"] == 0
    # An obstacle declared only to the north should not affect other octants' readings.
    for octant in ("E", "O", "S", "SE", "SO", "NE", "NO"):
        assert blocked[octant] == baseline[octant]


def test_taller_obstacle_blocks_at_least_as_much_sun():
    short = sun_hours_by_octant(-34.6, [Obstacle(type="arbol", height_m=1.0, direction="N")], "verano")
    tall = sun_hours_by_octant(-34.6, [Obstacle(type="arbol", height_m=10.0, direction="N")], "verano")
    assert tall["N"] <= short["N"]


def test_southern_hemisphere_summer_gets_more_total_sun_than_winter():
    # Buenos Aires: summer (Dec) days are longer than winter (Jun) days.
    result = compute_sun_exposure(latitude=-34.6, obstacles=[])
    summer_total = sum(result.by_season["verano"].values())
    winter_total = sum(result.by_season["invierno"].values())
    assert summer_total > winter_total
