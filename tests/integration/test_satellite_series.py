"""
Satellite series end to end against the real database: idempotent upserts, the usage ledger, and the
status/series endpoints reading a seeded multi-year history (Copernicus itself isn't configured in tests,
so every read works from stored data — exactly the degraded path production takes when the budget runs out).
"""
import math
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import text

from src.application.satellite.models import SOURCE_S2
from src.shared.domain.base import utcnow

FARM = "/api/v1/farm-management"
SAT = "/api/v1/satellite"


def _seed_rows(today: date, years: int = 3) -> list[dict]:
    """Every 5 days for `years`+ years; the season peaks ~3 weeks before today, and this year's peak is
    clearly lower than the previous ones."""
    peak_doy = (today - timedelta(days=20)).timetuple().tm_yday
    rows, day = [], today - timedelta(days=365 * years + 60)
    while day <= today - timedelta(days=2):
        doy = day.timetuple().tm_yday
        distance = ((doy - peak_doy + 182) % 365) - 182
        amplitude = 0.35 if day > today - timedelta(days=150) else 0.6
        ndvi = 0.2 + amplitude * math.exp(-(distance ** 2) / (2 * 35 ** 2))
        rows.append({
            "observed_on": day, "total_pixels": 120, "valid_pixels": 110, "valid_fraction": 0.92,
            "ndvi_mean": round(ndvi, 4), "ndre_mean": round(ndvi * 0.6, 4), "ndmi_mean": round(ndvi * 0.3, 4),
            "evi_mean": round(ndvi * 0.8, 4), "ndwi_mean": round(-ndvi * 0.7, 4),
        })
        day += timedelta(days=5)
    return rows


async def test_series_upsert_status_and_endpoints(client, signup, container):
    owner = await signup("satellite")
    h = owner["headers"]
    payload = {"name": "Lote Norte", "latitude": -34.6, "longitude": -58.4}
    r = await client.post(f"{FARM}/fields", headers=h, json=payload)
    assert r.status_code == 201, r.text
    field_id = UUID(r.json()["id"])
    account_id = UUID(owner["account"]["id"])

    repo = container.application.satellite_series_repository()
    today = utcnow().date()
    rows = _seed_rows(today)
    assert await repo.upsert_many(account_id, field_id, SOURCE_S2, rows) == len(rows)
    # Same passes again (an on-demand refresh racing the batch): updated, never duplicated.
    rows[-1]["ndvi_mean"] = 0.33
    await repo.upsert_many(account_id, field_id, SOURCE_S2, rows)
    stored = await repo.series(account_id, field_id, SOURCE_S2)
    assert len(stored) == len(rows)
    assert stored[-1].ndvi_mean == 0.33

    status = await client.get(f"{SAT}/fields/{field_id}/status", headers=h)
    assert status.status_code == 200, status.text
    body = status.json()
    ndvi = body["analysis"]["metrics"]["ndvi"]
    assert ndvi["normal_years"] >= 2
    assert ndvi["vs_normal"] < -0.1
    assert body["reading"]["source"] == "sentinel2"
    assert body["baseline_ndvi_mean"] is not None
    assert any("normal" in a or "año pasado" in a for a in body["alerts"])
    assert "Copernicus" in body["assessment"]  # credentials missing: says so, still answers from stored data

    # A second read the same week doesn't duplicate the alerts.
    await client.get(f"{SAT}/fields/{field_id}/status", headers=h)
    async with container.db_session_factory()() as session:
        count = (await session.execute(
            text("SELECT count(*) FROM alerts WHERE field_id = :f AND rule_id = 'satellite_below_normal'"),
            {"f": field_id},
        )).scalar_one()
    assert count == 1

    series = await client.get(f"{SAT}/fields/{field_id}/series?metric=ndvi", headers=h)
    assert series.status_code == 200, series.text
    weekly = series.json()["weekly"]
    assert weekly and weekly[-1]["normal_p50"] is not None
    assert (await client.get(f"{SAT}/fields/{field_id}/series?metric=bogus", headers=h)).status_code in (400, 422)

    sync = await client.post(f"{SAT}/fields/{field_id}/sync", headers=h)
    assert sync.json()["synced"] is False

    # Another account can't read this field's series.
    other = await signup("satellite-other")
    assert (await client.get(f"{SAT}/fields/{field_id}/series", headers=other["headers"])).status_code == 404


async def test_status_without_refresh_is_a_pure_read_and_carries_the_delta(client, signup, container):
    owner = await signup("satellite-pure")
    h = owner["headers"]
    r = await client.post(f"{FARM}/fields", headers=h, json={"name": "Lote", "latitude": -34.6, "longitude": -58.4})
    field_id = UUID(r.json()["id"])
    account_id = UUID(owner["account"]["id"])
    today = utcnow().date()
    rows = _seed_rows(today)
    rows[-1]["ndvi_mean"], rows[-2]["ndvi_mean"] = 0.30, 0.45  # the last clear pass fell 0.15 from the one before
    await container.application.satellite_series_repository().upsert_many(account_id, field_id, SOURCE_S2, rows)

    async def alert_count():
        async with container.db_session_factory()() as session:
            return (await session.execute(
                text("SELECT count(*) FROM alerts WHERE field_id = :f"), {"f": field_id}
            )).scalar_one()

    pure = await client.get(f"{SAT}/fields/{field_id}/status?refresh=false", headers=h)
    assert pure.status_code == 200, pure.text
    body = pure.json()
    assert body["ndvi_delta"] == -0.15 and body["previous_ndvi_mean"] == 0.45 and body["previous_date"]
    assert body["min_valid_fraction"] == 0.6
    assert body["alerts"]  # the rules are evaluated and returned...
    assert await alert_count() == 0  # ...but nothing is written

    await client.get(f"{SAT}/fields/{field_id}/status", headers=h)  # the default read keeps its old behavior
    assert await alert_count() >= 1


async def test_usage_ledger_accumulates_per_kind(container):
    repo = container.application.satellite_series_repository()
    before = await repo.usage_this_month()
    await repo.add_usage("batch", 1.25, requests=2)
    await repo.add_usage("batch", 0.75)
    await repo.add_usage("on_demand", None)
    after = await repo.usage_this_month()
    assert math.isclose(after["batch"] - before.get("batch", 0.0), 2.0)
    assert "on_demand" in after


async def test_series_with_several_metrics_a_range_and_discarded_passes(client, signup, container):
    owner = await signup("satellite-multi")
    h = owner["headers"]
    r = await client.post(f"{FARM}/fields", headers=h, json={"name": "Lote", "latitude": -34.6, "longitude": -58.4})
    field_id = UUID(r.json()["id"])
    account_id = UUID(owner["account"]["id"])
    today = utcnow().date()
    rows = _seed_rows(today)
    # a fully clouded date and a thin one, recorded with their causes
    rows += [
        {"observed_on": today - timedelta(days=61), "total_pixels": 120, "valid_pixels": 0, "valid_fraction": 0.0,
         "cloud_fraction": 0.9, "shadow_fraction": 0.1, "nodata_fraction": 0.0},
        {"observed_on": today - timedelta(days=56), "total_pixels": 120, "valid_pixels": 30, "valid_fraction": 0.25,
         "ndvi_mean": 0.4, "ndmi_mean": 0.1, "cloud_fraction": 0.0, "shadow_fraction": 0.7, "nodata_fraction": 0.05},
    ]
    keys = set().union(*[row.keys() for row in rows])
    rows = [{key: row.get(key) for key in keys} for row in rows]
    await container.application.satellite_series_repository().upsert_many(account_id, field_id, SOURCE_S2, rows)

    start = (today - timedelta(days=90)).isoformat()
    body = (await client.get(f"{SAT}/fields/{field_id}/series", headers=h, params={
        "metrics": "ndvi,ndmi", "since": start, "until": (today - timedelta(days=30)).isoformat(),
        "include_masked": "true",
    })).json()
    assert body["metrics"] == ["ndvi", "ndmi"] and set(body["weekly_by_metric"]) == {"ndvi", "ndmi"}
    assert body["weekly"] == body["weekly_by_metric"]["ndvi"] and body["min_valid_fraction"] == 0.6
    assert body["until"] == (today - timedelta(days=30)).isoformat()
    assert max(p["date"] for p in body["passes"]) <= body["until"] and min(p["date"] for p in body["passes"]) >= start
    by_date = {p["date"]: p for p in body["passes"]}
    cloudy = by_date[(today - timedelta(days=61)).isoformat()]
    assert (cloudy["discarded"], cloudy["discard_reason"], cloudy["ndvi_mean"]) == (True, "clouds", None)
    thin = by_date[(today - timedelta(days=56)).isoformat()]
    assert (thin["discarded"], thin["discard_reason"]) == (True, "shadow")
    assert all(p["ndmi_mean"] is not None for p in body["passes"] if not p["discarded"])
    assert any(not p["discarded"] for p in body["passes"])

    default = (await client.get(f"{SAT}/fields/{field_id}/series", headers=h, params={"since": start})).json()
    default_dates = {p["date"] for p in default["passes"]}
    assert (today - timedelta(days=61)).isoformat() not in default_dates  # fully masked: opt-in
    assert (today - timedelta(days=56)).isoformat() in default_dates  # thin but measured
    single = (await client.get(f"{SAT}/fields/{field_id}/series?metric=ndre", headers=h)).json()  # old contract
    assert single["metric"] == "ndre" and single["weekly"] and "passes" in single
    bad = await client.get(f"{SAT}/fields/{field_id}/series?metrics=ndvi,nope", headers=h)
    assert bad.status_code in (400, 422)


async def test_images_are_rendered_per_pass_and_layer_and_cached(client, signup, container):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from src.providers.satellite.copernicus import RenderedImage

    owner = await signup("satellite-images")
    h = owner["headers"]
    r = await client.post(f"{FARM}/fields", headers=h, json={"name": "Lote", "latitude": -34.6, "longitude": -58.4})
    field_id = UUID(r.json()["id"])
    account_id = UUID(owner["account"]["id"])
    today = utcnow().date()
    clear_day, cloudy_day = today - timedelta(days=10), today - timedelta(days=12)
    base = {"total_pixels": 100, "ndvi_mean": 0.5, "ndmi_mean": 0.2}
    await container.application.satellite_series_repository().upsert_many(account_id, field_id, SOURCE_S2, [
        {**base, "observed_on": clear_day, "valid_pixels": 90, "valid_fraction": 0.9},
        {"observed_on": cloudy_day, "total_pixels": 100, "valid_pixels": 0, "valid_fraction": 0.0, "ndvi_mean": None,
         "ndmi_mean": None},
    ])
    service = container.application.satellite_service()
    render = AsyncMock(return_value=RenderedImage(b"\x89PNG-fake", 0.4))
    def box(lat, lon):
        return [lon - 0.1, lat - 0.1, lon + 0.1, lat + 0.1]

    fake = SimpleNamespace(configured=True, render_layer=render, render_map=render, bbox_for=box)
    url = f"{SAT}/fields/{field_id}/image"

    with patch.object(service, "copernicus", fake):
        first = (await client.get(url, headers=h, params={"layer": "ndmi", "date": clear_day.isoformat()})).json()
        assert first["image_identifier"] and first["layer"] == "ndmi" and first["date"] == clear_day.isoformat()
        args = render.await_args.args
        assert args[2] == "ndmi" and args[3] == args[4] == clear_day.isoformat()
        assert render.await_args.kwargs["max_cloud"] == 100
        again = (await client.get(url, headers=h, params={"layer": "ndmi", "date": clear_day.isoformat()})).json()
        assert again["image_identifier"] == first["image_identifier"] and render.await_count == 1  # cached

        other_layer = (await client.get(url, headers=h, params={"layer": "rgb", "date": clear_day.isoformat()})).json()
        assert other_layer["image_identifier"] != first["image_identifier"] and render.await_count == 2

        latest = (await client.get(url, headers=h)).json()  # the old contract: latest NDVI
        assert latest["layer"] == "ndvi" and latest["date"] is None and render.await_args.args[2] == "ndvi"
        assert render.await_count == 3

        assert (await client.get(url, headers=h, params={"date": cloudy_day.isoformat()})).status_code == 400
        missing = await client.get(url, headers=h, params={"date": (today - timedelta(days=3)).isoformat()})
        assert missing.status_code == 404
        assert (await client.get(url, headers=h, params={"layer": "thermal"})).status_code == 400
        assert render.await_count == 3  # none of the refusals spent a request
