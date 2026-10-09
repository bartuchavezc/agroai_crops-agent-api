import uuid
from datetime import date
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.shared.domain.base import utcnow

from .models import CopernicusUsage, FieldSatelliteObservation, FieldSatelliteSync, ZoneSatelliteReading


class ZoneSatelliteRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def create(self, reading: ZoneSatelliteReading) -> ZoneSatelliteReading:
        async with self.session_factory() as session:
            session.add(reading)
            await session.commit()
            await session.refresh(reading)
        return reading

    async def latest_image(
        self, account_id: UUID, field_id: UUID, layer: str = "ndvi", observed_on: Optional[date] = None
    ) -> Optional[str]:
        """The most recent reading that actually has a saved image — not necessarily the most recent
        reading overall, since a stats-only check_field() row has none. `observed_on` picks the map of one
        pass; without it, the maps rendered "as of the latest pass". Rows from before layers existed
        (layer NULL) are NDVI."""
        stmt = select(ZoneSatelliteReading.image_identifier).where(
            ZoneSatelliteReading.account_id == account_id,
            ZoneSatelliteReading.field_id == field_id,
            ZoneSatelliteReading.image_identifier.is_not(None),
        )
        stmt = stmt.where(
            ZoneSatelliteReading.observed_on == observed_on if observed_on
            else ZoneSatelliteReading.observed_on.is_(None)
        )
        stmt = stmt.where(
            or_(ZoneSatelliteReading.layer == layer, ZoneSatelliteReading.layer.is_(None))
            if layer == "ndvi" else ZoneSatelliteReading.layer == layer
        )
        async with self.session_factory() as session:
            return (
                await session.execute(stmt.order_by(ZoneSatelliteReading.captured_at.desc()).limit(1))
            ).scalar_one_or_none()


class SatelliteSeriesRepository:
    """The per-field time series (field_satellite_observations), its sync bookkeeping and the monthly
    Copernicus processing-unit usage."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def upsert_many(self, account_id: UUID, field_id: UUID, source: str, observations: list[dict]) -> int:
        """Idempotent on (field_id, observed_on, source): re-ingesting a window refreshes the numbers (a
        reprocessed tile, a late one) instead of duplicating the pass."""
        if not observations:
            return 0
        table = FieldSatelliteObservation.__table__
        now = utcnow()
        rows = [
            {**obs, "id": uuid.uuid4(), "account_id": account_id, "field_id": field_id, "source": source,
             "created_at": now, "updated_at": now}
            for obs in observations
        ]
        key_cols = ("id", "account_id", "field_id", "observed_on", "source", "created_at")
        update_cols = [c for c in rows[0] if c not in key_cols]
        async with self.session_factory() as session:
            for start in range(0, len(rows), 500):
                stmt = insert(table).values(rows[start:start + 500])
                stmt = stmt.on_conflict_do_update(
                    index_elements=["field_id", "observed_on", "source"],
                    set_={c: stmt.excluded[c] for c in update_cols},
                )
                await session.execute(stmt)
            await session.commit()
        return len(rows)

    async def series(
        self, account_id: UUID, field_id: UUID, source: str, since: Optional[date] = None
    ) -> Sequence[FieldSatelliteObservation]:
        stmt = select(FieldSatelliteObservation).where(
            FieldSatelliteObservation.account_id == account_id,
            FieldSatelliteObservation.field_id == field_id,
            FieldSatelliteObservation.source == source,
        )
        if since:
            stmt = stmt.where(FieldSatelliteObservation.observed_on >= since)
        async with self.session_factory() as session:
            return (await session.execute(stmt.order_by(FieldSatelliteObservation.observed_on))).scalars().all()

    async def delete_field_series(self, field_id: UUID, source: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                delete(FieldSatelliteObservation).where(
                    FieldSatelliteObservation.field_id == field_id, FieldSatelliteObservation.source == source
                )
            )
            await session.execute(
                delete(FieldSatelliteSync).where(
                    FieldSatelliteSync.field_id == field_id, FieldSatelliteSync.source == source
                )
            )
            await session.commit()

    async def get_sync(self, field_id: UUID, source: str) -> Optional[FieldSatelliteSync]:
        async with self.session_factory() as session:
            return await session.get(FieldSatelliteSync, (field_id, source))

    async def save_sync(
        self, account_id: UUID, field_id: UUID, source: str, geometry_hash: str, history_from: date, synced_to: date
    ) -> None:
        table = FieldSatelliteSync.__table__
        values = {
            "field_id": field_id,
            "source": source,
            "account_id": account_id,
            "geometry_hash": geometry_hash,
            "history_from": history_from,
            "synced_to": synced_to,
            "last_synced_at": utcnow(),
        }
        stmt = insert(table).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["field_id", "source"],
            set_={k: stmt.excluded[k] for k in ("geometry_hash", "history_from", "synced_to", "last_synced_at")},
        )
        async with self.session_factory() as session:
            await session.execute(stmt)
            await session.commit()

    async def add_usage(self, kind: str, processing_units: Optional[float], requests: int = 1) -> None:
        table = CopernicusUsage.__table__
        stmt = insert(table).values(
            month=_month_start(), kind=kind, processing_units=processing_units or 0.0, requests=requests,
            updated_at=utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["month", "kind"],
            set_={
                "processing_units": table.c.processing_units + stmt.excluded.processing_units,
                "requests": table.c.requests + stmt.excluded.requests,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        async with self.session_factory() as session:
            await session.execute(stmt)
            await session.commit()

    async def usage_this_month(self) -> dict[str, float]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(CopernicusUsage.kind, CopernicusUsage.processing_units).where(
                        CopernicusUsage.month == _month_start()
                    )
                )
            ).all()
        return {kind: float(units or 0.0) for kind, units in rows}


def _month_start() -> date:
    today = utcnow().date()
    return today.replace(day=1)
