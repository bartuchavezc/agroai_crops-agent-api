"""The models run on a real lot: its weather, its zone (a pot holds less water), its logged waterings and readings."""
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from src.providers.weather.open_meteo import OpenMeteoHour
from src.shared.domain.actor import Actor

FARM = "/api/v1/farm-management"


def _weather(days_back: int, forecast: int = 0, tmin=14, tmax=26, et0=5.0, rain=0.0):
    today = date.today()
    return [{"date": (today - timedelta(days=days_back - i)).isoformat(), "forecast": i > days_back,
             "temp_min_c": tmin, "temp_max_c": tmax, "precipitation_mm": rain, "et0_mm": et0}
            for i in range(days_back + 1 + forecast)]


async def test_water_thermal_time_and_disease_risk_on_a_lot(client, signup, container):
    user = await signup("agro")
    h = user["headers"]
    field = (await client.post(f"{FARM}/fields", headers=h, json={
        "name": "Patio", "latitude": -34.6, "longitude": -58.4, "soil_type": "franco arcilloso"})).json()
    pot = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "maceta"})).json()
    crop = (await client.get(f"{FARM}/crop-masters?q=tomate", headers=h)).json()[0]["id"]
    planted = date.today() - timedelta(days=20)
    lot = (await client.post(f"{FARM}/lots", headers=h, json={
        "field_id": field["id"], "crop_master_id": crop, "zone_id": pot["id"], "status": "planted",
        "planting_date": planted.isoformat()})).json()
    actor = Actor(user_id=uuid.UUID(user["user"]["id"]), account_id=uuid.UUID(user["account"]["id"]), role="owner",
                  timezone="America/Argentina/Buenos_Aires")
    models = container.application.agronomy_models()
    meteo = container.data_providers.weather_service().open_meteo
    lot_id = uuid.UUID(lot["id"])

    with patch.object(meteo, "daily_window", AsyncMock(return_value=_weather(20))):
        dry = await models.water_balance(actor, lot_id)
        assert dry["root_depth_m"] == 0.2 and "sustrato de maceta" in dry["assumptions"]
        assert dry["status"] == "estres" and dry["days_since_calibration"] is None
        await models.record_soil_moisture(actor, lot_id, None, "humedo", 10, None)
        calibrated = await models.water_balance(actor, lot_id)
        assert calibrated["days_since_calibration"] == 0 and calibrated["status"] in ("ok", "exceso")
        assert calibrated["uncertainty_mm"] < dry["uncertainty_mm"]

    with patch.object(meteo, "daily_window", AsyncMock(return_value=_weather(20, forecast=7))):
        gdd = await models.thermal_time(actor, lot_id)
    assert gdd["tbase_c"] == 10 and gdd["gdd"] == 21 * 10 and gdd["counted_from"] == "siembra"
    assert gdd["projected_days_to_harvest"] > 0

    now = date.today()
    hours = [OpenMeteoHour(f"{(now - timedelta(days=d)).isoformat()}T{h:02d}:00", 22, 95 if h < 14 else 60, 1, 0, None)
             for d in range(7, -1, -1) for h in range(24)]
    with patch.object(meteo, "hourly_window", AsyncMock(return_value=hours)):
        risk = await models.disease_risk(actor, uuid.UUID(field["id"]), "Tomate")
    assert risk["models"] == ["tomcast", "blitecast", "oidio", "fulvia"]
    assert next(r for r in risk["risks"] if r["model"] == "TOM-CAST")["level"] == "alto"
