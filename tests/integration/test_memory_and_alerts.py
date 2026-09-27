"""Hybrid agent memory (tsvector + pgvector) and proactive forecast alerts."""
import hashlib
import math
from datetime import datetime, time, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert

from src.providers.weather.models import WeatherForecast, round_coord
from src.shared.domain.actor import Actor


def _fake_embedding(texts, dims=768):
    vectors = []
    for t in texts:
        vec = [0.0] * dims
        for word in t.lower().split():
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % dims] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vectors.append([v / norm for v in vec])
    return vectors


def _actor(user) -> Actor:
    from uuid import UUID

    u = user["user"]
    return Actor(UUID(u["id"]), UUID(u["account_id"]), u["role"])


async def test_memory_hybrid_recall_is_account_scoped(client, signup, container):
    memory = container.agent.memory_service()
    gateway = container.agent.gemini()
    a = await signup("mem-a")
    b = await signup("mem-b")

    async def fake_embed(user_id, texts, task_type):
        return _fake_embedding(texts)

    with patch.object(gateway, "embed", fake_embed):
        await memory.remember(_actor(a), "A la abuela no le gusta el riego por goteo en los tomates", ["riego"])
        await memory.remember(_actor(a), "El pulgón apareció en las habas en octubre de 2025")
        await memory.remember(_actor(b), "Riego por goteo instalado en el invernadero")

        results = await memory.recall(_actor(a), "riego por goteo")
        assert results and "abuela" in results[0].content
        assert all("invernadero" not in r.content for r in results)

    # Without a usable key, recall degrades to lexical search instead of failing.
    lexical = await memory.recall(_actor(a), "pulgón habas")
    assert lexical and "pulgón" in lexical[0].content

    listed = (await client.get("/api/v1/agent/memories", headers=a["headers"])).json()
    assert len(listed) == 2
    target = listed[0]["id"]
    assert (await client.delete(f"/api/v1/agent/memories/{target}", headers=b["headers"])).status_code == 404
    assert (await client.delete(f"/api/v1/agent/memories/{target}", headers=a["headers"])).status_code == 204
    assert len((await client.get("/api/v1/agent/memories", headers=a["headers"])).json()) == 1


async def test_forecast_alerts_are_created_once(client, signup, container):
    owner = await signup("alerts")
    other = await signup("alerts-other")
    lat, lon = -31.4, -64.18
    await client.post(
        "/api/v1/farm-management/fields",
        headers=owner["headers"],
        json={"name": "Quinta", "latitude": lat, "longitude": lon},
    )

    tz = ZoneInfo(container.config.app.timezone())
    tomorrow = datetime.now(tz).date() + timedelta(days=1)
    issued = datetime.now(timezone.utc)
    rows = [
        {
            "time": datetime.combine(tomorrow, time(0), tzinfo=timezone.utc),
            "latitude": round_coord(lat), "longitude": round_coord(lon), "source": "smn_wrf", "resolution": "24h",
            "issued_at": issued, "tmin": -3.5, "tmax": 12.0,
        },
    ]
    for hour in range(0, 24, 3):
        rows.append({
            "time": datetime.combine(tomorrow, time(hour), tzinfo=tz).astimezone(timezone.utc),
            "latitude": round_coord(lat), "longitude": round_coord(lon), "source": "smn_wrf", "resolution": "1h",
            "issued_at": issued, "temperature": 18.0, "humidity": 92.0, "precipitation_accum": hour * 2.0,
        })
    full_rows = [{c: r.get(c) for c in WeatherForecast.__table__.columns.keys()} for r in rows]
    async with container.db_session_factory()() as session:
        await session.execute(insert(WeatherForecast.__table__).values(full_rows).on_conflict_do_nothing())
        await session.commit()

    service = container.application.forecast_alert_service()
    first = await service.run()
    second = await service.run()
    assert first.alerts_created >= 2  # severe frost + fungal risk
    assert second.alerts_created == 0

    active = (await client.get("/api/v1/alerts/active", headers=owner["headers"])).json()
    rule_ids = {a["rule_id"] for a in active}
    assert {"forecast_severe_frost", "forecast_fungal_risk"} <= rule_ids
    assert all(a["source"] == "smn" for a in active)
    assert (await client.get("/api/v1/alerts/active", headers=other["headers"])).json() == []

    forecast = (
        await client.get(
            f"/api/v1/weather/forecast?latitude={lat}&longitude={lon}&days=3", headers=owner["headers"]
        )
    ).json()
    assert any(d["tmin"] == -3.5 for d in forecast["daily"])

    ack = await client.put(f"/api/v1/alerts/{active[0]['id']}/acknowledge", headers=owner["headers"])
    assert ack.status_code == 200 and ack.json()["acknowledged"] is True
