"""GET /farm-management/fields/{id}/summary: the home screen of a field in one call."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

from src.application.farm.summary import field_state
from src.application.irrigation.schemas import FieldIrrigationResult

from .test_zones import _TINY_PNG, _cycle, _field, _zone_result

FARM = "/api/v1/farm-management"
P = "/api/v1/planning"


def _irrigation(field_id, status="cubierto"):
    return FieldIrrigationResult(field_id=field_id, field_name="Huerta", et0_mm=3.0, rain_forecast_mm=0.0,
                                 field_status=status, field_message="x")


def test_state_rules():
    class A:
        def __init__(self, severity, title="t"):
            self.severity, self.title = severity, title

    assert field_state([], [], None) == ("unknown", [])
    assert field_state([], [], _irrigation(UUID(int=1)))[0] == "ok"
    assert field_state([A("low", "Lluvia")], [], None) == ("attention", ["Lluvia"])
    assert field_state([A("critical", "Helada")], [], None) == ("alert", ["Helada"])
    assert field_state([], [], _irrigation(UUID(int=1), "regar")) == ("attention", ["Hay que regar"])


async def test_summary_brings_zones_analysis_alerts_reminders_and_irrigation(client, signup, container):
    owner = await signup("summary")
    h = owner["headers"]
    field = await _field(client, h)
    await client.put(f"{FARM}/fields/{field['id']}", headers=h, json={"latitude": -34.9, "longitude": -57.9})
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    empty_zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cajon"})).json()
    cycle = await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])
    loose = await _cycle(client, h, field["id"], "lechuga")  # no zone

    with patch.object(container.agent.gemini(), "generate_structured",
                      AsyncMock(return_value=_zone_result([(cycle, "Tomate")]))):
        up = await client.post(
            "/api/v1/upload/zone-tracking", headers=h, data={"zone_id": zone["id"]},
            files=[("image_files", ("a.png", _TINY_PNG, "image/png"))],
        )
    assert up.status_code == 200, up.text

    now = datetime.now(timezone.utc)
    reminder_ids = []
    for title, offset in (("Hoy o antes", -1), ("Mañana", 40)):
        made = await client.post(f"{P}/reminders", headers=h, json={
            "title": title, "field_id": field["id"], "due_at": (now + timedelta(hours=offset)).isoformat()})
        assert made.status_code == 201, made.text
        reminder_ids.append(made.json()["id"])
    await container.application.alert_service().create_system_alert(
        account_id=UUID(owner["account"]["id"]), field_id=UUID(field["id"]), title="Helada probable",
        message="m", severity="high", alert_type="weather", source="smn", dedupe_key="summary-test-1",
    )

    irrigation = _irrigation(UUID(field["id"]), "regar")
    with patch.object(container.application.irrigation_service(), "compute", AsyncMock(return_value=irrigation)):
        body = (await client.get(f"{FARM}/fields/{field['id']}/summary", headers=h)).json()

    assert body["field"]["id"] == field["id"] and body["status"] == "alert"
    assert body["status_reasons"] == ["Helada probable"]
    by_zone = {z["zone"]["id"]: z for z in body["zones"]}
    assert by_zone[zone["id"]]["last_analysis"]["report_id"] == up.json()["report_id"]
    assert by_zone[zone["id"]]["last_analysis"]["overall_health"] == "good"
    assert by_zone[zone["id"]]["last_analysis"]["image_identifier"]
    assert [c["id"] for c in by_zone[zone["id"]]["active_cycles"]] == [cycle["id"]]
    assert by_zone[empty_zone["id"]]["last_analysis"] is None
    assert [c["id"] for c in body["unzoned_cycles"]] == [loose["id"]]
    assert [a["title"] for a in body["alerts"]] == ["Helada probable"]
    assert [r["title"] for r in body["reminders_today"]] == ["Hoy o antes"]  # tomorrow's stays out
    assert body["irrigation"]["field_status"] == "regar"

    # no coordinates / irrigation down: the block is null, the rest still comes
    with patch.object(container.application.irrigation_service(), "compute", AsyncMock(side_effect=RuntimeError("x"))):
        degraded = (await client.get(f"{FARM}/fields/{field['id']}/summary", headers=h)).json()
    assert degraded["irrigation"] is None and degraded["status"] == "alert"

    for reminder_id in reminder_ids:  # an overdue one would be picked up by other tests' reminder batch run
        await client.delete(f"{P}/reminders/{reminder_id}", headers=h)
    stranger = await signup("summary-stranger")
    assert (await client.get(f"{FARM}/fields/{field['id']}/summary", headers=stranger["headers"])).status_code == 404
