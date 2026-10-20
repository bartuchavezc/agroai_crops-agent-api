from src.agent.reasoning.periodic_report import (
    ZoneCropAssessment,
    ZoneGroupAssessment,
    ZoneOverviewResult,
    ZoneSynthesisResult,
)
from src.agent.reasoning.zone_grouping import MAX_CYCLES_PER_GROUP, group_cycles, merge_zone_result


def _crop(cycle_id: str, name: str, health: str = "good") -> ZoneCropAssessment:
    return ZoneCropAssessment(
        lot_id=cycle_id,
        crop_name=name,
        visible_in_photos=True,
        growth_stage="vegetativo",
        health_status=health,
        health_summary="ok",
        expected_vs_actual="ok",
        harvest_ready=False,
        harvest_verdict="Sin frutos",
    )


def _group(
    crops: list[ZoneCropAssessment], risk="low", confidence=0.8, needs_human_expert=False
) -> ZoneGroupAssessment:
    return ZoneGroupAssessment(
        crops=crops,
        group_risk_severity=risk,
        group_recommendations=[],
        group_notes="",
        confidence=confidence,
        needs_human_expert=needs_human_expert,
    )


def _overview(unlisted=None) -> ZoneOverviewResult:
    return ZoneOverviewResult(zone_observations="prolijo", unlisted_plants=unlisted or [])


def _synthesis() -> ZoneSynthesisResult:
    return ZoneSynthesisResult(
        zone_summary="Resumen", past_actions_assessment="ok", objectives_assessment="ok"
    )


def test_group_cycles_separates_crops_with_different_fichas():
    groups = group_cycles([("c1", "Tomate Cherry"), ("c2", "Lechuga Criolla")])
    assert [g.id for g in groups] == ["tomate", "lechuga"]
    assert groups[0].cycle_ids == ("c1",) and groups[1].cycle_ids == ("c2",)


def test_group_cycles_bundles_crops_without_a_ficha_together():
    groups = group_cycles([("c1", "Orquídea"), ("c2", "Bonsai")])
    assert len(groups) == 1 and groups[0].id == "_sin_ficha"
    assert groups[0].cycle_ids == ("c1", "c2")


def test_group_cycles_splits_an_oversized_group():
    cycles = [(f"c{i}", "Tomate") for i in range(MAX_CYCLES_PER_GROUP + 2)]
    groups = group_cycles(cycles)
    assert len(groups) == 2
    assert groups[0].id == "tomate-1" and len(groups[0].cycle_ids) == MAX_CYCLES_PER_GROUP
    assert groups[1].id == "tomate-2" and len(groups[1].cycle_ids) == 2


def test_group_cycles_keeps_order_of_first_appearance():
    groups = group_cycles([("c1", "Lechuga"), ("c2", "Tomate"), ("c3", "Lechuga")])
    assert [g.id for g in groups] == ["lechuga", "tomate"]
    assert groups[0].cycle_ids == ("c1", "c3")


def test_merge_overall_health_is_the_worst_of_every_crop():
    resolved = [_group([_crop("c1", "Tomate", "good")]), _group([_crop("c2", "Lechuga", "poor")])]
    result = merge_zone_result(["c1", "c2"], resolved, _overview(), _synthesis())
    assert result.overall_health == "poor"


def test_merge_ignores_unknown_health_when_rolling_up():
    resolved = [_group([_crop("c1", "Tomate", "unknown")]), _group([_crop("c2", "Lechuga", "good")])]
    result = merge_zone_result(["c1", "c2"], resolved, _overview(), _synthesis())
    assert result.overall_health == "good"


def test_merge_risk_severity_is_worst_of_every_group():
    resolved = [_group([_crop("c1", "Tomate")], risk="low"), _group([_crop("c2", "Lechuga")], risk="critical")]
    result = merge_zone_result(["c1", "c2"], resolved, _overview(), _synthesis())
    assert result.risk_severity == "critical"


def test_merge_confidence_is_the_minimum_not_an_average():
    resolved = [_group([_crop("c1", "Tomate")], confidence=0.9), _group([_crop("c2", "Lechuga")], confidence=0.4)]
    result = merge_zone_result(["c1", "c2"], resolved, _overview(), _synthesis())
    assert result.confidence == 0.4


def test_merge_needs_human_expert_is_true_if_any_group_says_so():
    resolved = [
        _group([_crop("c1", "Tomate")], needs_human_expert=False),
        _group([_crop("c2", "Lechuga")], needs_human_expert=True),
    ]
    result = merge_zone_result(["c1", "c2"], resolved, _overview(), _synthesis())
    assert result.needs_human_expert is True


def test_merge_fills_a_defensive_entry_for_a_cycle_missing_from_every_group():
    resolved = [_group([_crop("c1", "Tomate")])]  # c2's group failed entirely, or dropped the id
    result = merge_zone_result(["c1", "c2"], resolved, _overview(), _synthesis())
    ids = [c.lot_id for c in result.crops]
    assert ids == ["c1", "c2"]
    assert result.crops[1].health_status == "unknown" and result.crops[1].visible_in_photos is False


def test_merge_uses_the_overview_and_synthesis_verbatim():
    result = merge_zone_result(
        ["c1"], [_group([_crop("c1", "Tomate")])], _overview(unlisted=["Malva"]), _synthesis()
    )
    assert result.unlisted_plants == ["Malva"]
    assert result.zone_summary == "Resumen"
