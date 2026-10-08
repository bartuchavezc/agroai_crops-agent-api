from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID

from sqlalchemy import delete

from src.application.satellite.models import ZoneSatelliteReading
from src.providers.satellite.copernicus import NdviStats
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow


async def _field_with_reading(client, signup, container, hours_old: float):
    owner = await signup("sat")
    created = await client.post(
        "/api/v1/farm-management/fields", headers=owner["headers"],
        json={"name": "Lote", "latitude": -34.92, "longitude": -57.95},
    )
    field_id = UUID(created.json()["id"])
    actor = Actor(UUID(owner["user"]["id"]), UUID(owner["user"]["account_id"]), "owner")
    repo = container.application.zone_satellite_repository()
    # Creating a field already triggers a satellite check (live, if Copernicus is configured in this environment):
    # start from a clean slate so the only reading is the one this test controls.
    async with repo.session_factory() as session:
        await session.execute(delete(ZoneSatelliteReading).where(ZoneSatelliteReading.field_id == field_id))
        await session.commit()
    await repo.create(ZoneSatelliteReading(
        account_id=actor.account_id, field_id=field_id, captured_at=utcnow() - timedelta(hours=hours_old),
        ndvi_mean=0.62, ndvi_min=0.4, ndvi_max=0.8, ndwi_mean=0.1,
    ))
    return actor, field_id


async def test_recent_stored_reading_is_reused_without_calling_copernicus(client, signup, container):
    actor, field_id = await _field_with_reading(client, signup, container, hours_old=3)
    service = container.application.satellite_service()
    stats = NdviStats(ndvi_mean=0.1, ndvi_min=0.0, ndvi_max=0.2, ndwi_mean=0.0)
    with patch.object(type(service.copernicus), "configured", True), \
            patch.object(service.copernicus, "ndvi_stats", AsyncMock(return_value=stats)) as live:
        reused = await service.check_field(actor, field_id, max_age_hours=12)
        assert reused.reading.ndvi_mean == 0.62 and "reutilizada" in reused.assessment
        live.assert_not_awaited()
        assert len(await service.repo.recent(actor.account_id, field_id)) == 1  # nothing was written

        fresh = await service.check_field(actor, field_id)  # no max age -> the live call, as before
        live.assert_awaited_once()
        assert fresh.reading.ndvi_mean == 0.1


async def test_stale_stored_reading_is_not_reused(client, signup, container):
    actor, field_id = await _field_with_reading(client, signup, container, hours_old=30)
    service = container.application.satellite_service()
    stats = NdviStats(ndvi_mean=0.55, ndvi_min=0.3, ndvi_max=0.7, ndwi_mean=0.05)
    with patch.object(type(service.copernicus), "configured", True), \
            patch.object(service.copernicus, "ndvi_stats", AsyncMock(return_value=stats)) as live:
        status = await service.check_field(actor, field_id, max_age_hours=12)
    live.assert_awaited_once()
    assert status.reading.ndvi_mean == 0.55
