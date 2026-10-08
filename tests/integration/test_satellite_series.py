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


async def test_usage_ledger_accumulates_per_kind(container):
    repo = container.application.satellite_series_repository()
    before = await repo.usage_this_month()
    await repo.add_usage("batch", 1.25, requests=2)
    await repo.add_usage("batch", 0.75)
    await repo.add_usage("on_demand", None)
    after = await repo.usage_this_month()
    assert math.isclose(after["batch"] - before.get("batch", 0.0), 2.0)
    assert "on_demand" in after
