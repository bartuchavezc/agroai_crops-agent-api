"""Crop-cycle progress: expected % and stage from dates and the stage plan; ok/late/affected from the last analysis."""
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from src.application.planning.progress import assess, current_and_next, expected_pct

from .test_zones import _TINY_PNG, FARM, _cycle, _field, _zone_result

P = "/api/v1/planning"


def test_expected_pct_is_the_elapsed_share_of_the_span_and_clamped():
    start, end = date(2026, 9, 1), date(2026, 11, 30)  # 90 days
    assert expected_pct(start, end, date(2026, 10, 16)) == 50.0
    assert expected_pct(start, end, date(2026, 8, 1)) == 0.0 and expected_pct(start, end, date(2027, 1, 1)) == 100.0
    assert expected_pct(None, end, start) is None and expected_pct(start, None, start) is None


def test_current_and_next_stage_from_the_plan():
    stages = [("germinacion", "Germinación", date(2026, 9, 1)), ("vegetativo", "Crecimiento", date(2026, 9, 10)),
              ("cosecha", "Posible cosecha", date(2026, 11, 20))]
    assert current_and_next(stages, date(2026, 9, 15)) == (("vegetativo", "Crecimiento"), date(2026, 11, 20))
    assert current_and_next(stages, date(2026, 8, 1)) == (None, date(2026, 9, 1))
    assert current_and_next(stages, date(2026, 12, 1))[1] is None
    assert current_and_next([], date(2026, 9, 1)) == (None, None)


def test_status_comes_from_the_analysis_not_from_dates_alone():
    today, harvest = date(2026, 10, 1), date(2026, 11, 1)
    assert assess(None, harvest, today)[0] == "unknown"
    assert assess({"health_status": "good", "growth_on_track": True}, harvest, today) == ("ok", None)
    assert assess({"growth_on_track": False, "health_status": "good"}, harvest, today)[0] == "late"
    assert assess({"health_status": "poor"}, harvest, today)[0] == "affected"
    status, reason = assess({"stress_signals": ["hojas amarillas"], "growth_on_track": False}, harvest, today)
    assert status == "affected" and "hojas amarillas" in reason  # affected beats late
    assert assess({"health_status": "good", "growth_on_track": True}, date(2026, 9, 1), today)[0] == "late"  # overdue
    assert assess(None, date(2026, 9, 1), today)[0] == "late"


async def test_progress_endpoint_uses_the_plan_and_the_latest_zone_analysis(client, signup, container):
    h = (await signup("progress"))["headers"]
    field = await _field(client, h)
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    cycle = await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])
    planted = date.today() - timedelta(days=30)
    await client.put(f"{FARM}/crop-cycles/{cycle['id']}", headers=h, json={
        "planting_date": planted.isoformat(), "expected_harvest_date": (planted + timedelta(days=120)).isoformat(),
    })

    before = (await client.get(f"{P}/crop-cycles/{cycle['id']}/progress", headers=h)).json()
    assert before["expected_pct"] == 25.0 and before["status"] == "unknown" and before["evidence_report_id"] is None
    assert before["current_stage"] is not None and before["next_stage_at"] is not None

    result = _zone_result([(cycle, "Tomate")])
    result.crops[0].growth_on_track = False
    result.crops[0].stress_signals = ["hojas amarillas"]
    with patch.object(container.agent.gemini(), "generate_structured", AsyncMock(return_value=result)):
        up = await client.post(
            "/api/v1/upload/zone-tracking", headers=h, data={"zone_id": zone["id"]},
            files=[("image_files", ("a.png", _TINY_PNG, "image/png"))],
        )
    assert up.status_code == 200, up.text

    after = (await client.get(f"{P}/crop-cycles/{cycle['id']}/progress", headers=h)).json()
    assert after["status"] == "affected" and "hojas amarillas" in after["reason"]
    assert after["evidence_report_id"] == up.json()["report_id"]
    missing = await client.get(f"{P}/crop-cycles/00000000-0000-0000-0000-000000000000/progress", headers=h)
    assert missing.status_code == 404
