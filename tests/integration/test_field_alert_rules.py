"""Alert rules per field: list, switch off, change the limit (owner/tecnico), and the jobs respect it."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert

from src.providers.weather.models import WeatherForecast
from src.providers.weather.service import round_coord

FARM = "/api/v1/farm-management"
ALERTS = "/api/v1/alerts"


async def _field(client, h, name, lat=None, lon=None):
    body = {"name": name, **({"latitude": lat, "longitude": lon} if lat is not None else {})}
    response = await client.post(f"{FARM}/fields", headers=h, json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_list_patch_validate_and_reset(client, signup, add_member):
    owner = await signup("rules-api")
    staff = await add_member(owner, "staff")
    h = owner["headers"]
    field = await _field(client, h, "Quinta")
    url = f"{ALERTS}/fields/{field}/alert-rules"

    rules = {r["rule_id"]: r for r in (await client.get(url, headers=h)).json()}
    cold = rules["temp_cold_stress"]
    assert cold["enabled"] and cold["threshold"] == 5 and cold["default_threshold"] == 5
    assert (cold["min_threshold"], cold["max_threshold"], cold["unit"]) == (-10, 15, "°C")
    assert not cold["customized"]
    assert rules["affected_critical"]["default_threshold"] is None
    assert len(rules) >= 15

    changed = await client.patch(f"{url}/temp_cold_stress", headers=h, json={"threshold": 3})
    assert changed.status_code == 200, changed.text
    assert changed.json()["threshold"] == 3 and changed.json()["default_threshold"] == 5
    assert changed.json()["customized"]
    off = await client.patch(f"{url}/temp_heat_stress", headers=h, json={"enabled": False})
    assert off.json()["enabled"] is False and off.json()["threshold"] == 35 and off.json()["customized"]
    both = (await client.get(url, headers=staff["headers"])).json()  # members can read what is configured
    assert {r["rule_id"] for r in both if r["customized"]} == {"temp_cold_stress", "temp_heat_stress"}

    assert (await client.patch(f"{url}/temp_cold_stress", headers=h, json={"threshold": 99})).status_code == 400
    assert (await client.patch(f"{url}/affected_critical", headers=h, json={"threshold": 10})).status_code == 400
    assert (await client.patch(f"{url}/nope", headers=h, json={"enabled": False})).status_code == 404
    denied = await client.patch(f"{url}/temp_cold_stress", headers=staff["headers"], json={"enabled": False})
    assert denied.status_code == 403
    other = await signup("rules-api-other")
    assert (await client.get(url, headers=other["headers"])).status_code == 404

    # null puts the limit back; turning it on again with the default limit leaves no trace
    back = await client.patch(f"{url}/temp_cold_stress", headers=h, json={"threshold": None})
    assert back.json()["threshold"] == 5 and not back.json()["customized"]
    on = await client.patch(f"{url}/temp_heat_stress", headers=h, json={"enabled": True})
    assert on.json()["enabled"] is True and not on.json()["customized"]
    assert not [r for r in (await client.get(url, headers=h)).json() if r["customized"]]


async def test_the_forecast_job_respects_a_rule_switched_off_for_one_field(client, signup, container):
    owner = await signup("rules-job")
    h = owner["headers"]
    spots = {"silenced": (-27.1, -65.2), "default": (-28.3, -64.9)}
    fields = {name: await _field(client, h, name, *pos) for name, pos in spots.items()}
    assert (await client.patch(
        f"{ALERTS}/fields/{fields['silenced']}/alert-rules/forecast_severe_frost", headers=h, json={"enabled": False}
    )).status_code == 200

    tz = ZoneInfo(container.config.app.timezone())
    tomorrow = datetime.now(tz).date() + timedelta(days=1)
    issued = datetime.now(timezone.utc)
    rows = [{
        "time": datetime.combine(tomorrow, time(0), tzinfo=timezone.utc),
        "latitude": round_coord(lat), "longitude": round_coord(lon), "source": "smn_wrf", "resolution": "24h",
        "issued_at": issued, "tmin": -3.5, "tmax": 12.0,
    } for lat, lon in spots.values()]
    full = [{c: r.get(c) for c in WeatherForecast.__table__.columns.keys()} for r in rows]
    async with container.db_session_factory()() as session:
        await session.execute(insert(WeatherForecast.__table__).values(full).on_conflict_do_nothing())
        await session.commit()

    await container.application.forecast_alert_service().run()
    active = (await client.get(f"{ALERTS}/active", headers=h)).json()
    by_field = {}
    for alert in active:
        by_field.setdefault(alert["field_id"], set()).add(alert["rule_id"])
    assert "forecast_severe_frost" in by_field.get(fields["default"], set())
    assert "forecast_severe_frost" not in by_field.get(fields["silenced"], set())
    assert "forecast_frost" not in by_field.get(fields["silenced"], set())  # -3.5 is below the frost band as well
