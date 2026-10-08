"""
Keeps each field's satellite series (field_satellite_observations) complete and fresh, within the
Copernicus free tier's monthly processing-unit budget.

`sync_field` is idempotent and does whatever the field needs, in this order:
  1. the drawn boundary changed since the series was built -> drop it (different pixels) and rebuild;
  2. history shorter than wanted -> backfill the older years, one Statistical API request per year;
  3. incremental -> re-request from a few days before the last synced date up to today (tiles get
     published late or reprocessed), upserting on (field, date, source).

Budget: every request's real cost (x-processingunits-spent) is added to copernicus_usage under `batch` or
`on_demand`; each kind has its own monthly cap, so the scheduled job can never eat the headroom user-facing
requests (and NDVI map renders) need.
"""
import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from src.providers.satellite.copernicus import CopernicusAdapter, SeriesResult
from src.shared.domain.base import utcnow

from .models import SOURCE_S1, SOURCE_S2
from .repository import SatelliteSeriesRepository

logger = logging.getLogger(__name__)

KIND_BATCH = "batch"
KIND_ON_DEMAND = "on_demand"
INCREMENTAL_OVERLAP_DAYS = 15
S2_FIRST_DATE = date(2017, 3, 28)  # Sentinel-2 L2A archive start
S1_FIRST_DATE = date(2014, 10, 3)


@dataclass
class SyncReport:
    field_id: str
    sources: dict[str, str] = field(default_factory=dict)  # source -> what happened
    observations: int = 0
    processing_units: float = 0.0
    requests: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class BudgetExceeded(Exception):
    pass


class SatelliteIngestService:
    def __init__(
        self,
        repository: SatelliteSeriesRepository,
        copernicus: CopernicusAdapter,
        backfill_years: int = 3,
        batch_pu_budget: float = 7000.0,
        on_demand_pu_budget: float = 2000.0,
        s1_enabled: bool = True,
        s1_orbit_direction: str = "DESCENDING",
        pause_seconds: float = 1.0,
    ):
        self.repo = repository
        self.copernicus = copernicus
        self.backfill_years = int(backfill_years)
        self.budgets = {KIND_BATCH: float(batch_pu_budget), KIND_ON_DEMAND: float(on_demand_pu_budget)}
        self.s1_enabled = bool(s1_enabled)
        self.s1_orbit_direction = s1_orbit_direction
        self.pause_seconds = float(pause_seconds)

    @property
    def sources(self) -> list[str]:
        return [SOURCE_S2, SOURCE_S1] if self.s1_enabled else [SOURCE_S2]

    async def budget_left(self, kind: str) -> float:
        usage = await self.repo.usage_this_month()
        return self.budgets[kind] - usage.get(kind, 0.0)

    async def usage(self) -> dict:
        usage = await self.repo.usage_this_month()
        return {
            kind: {"spent": round(usage.get(kind, 0.0), 2), "budget": budget}
            for kind, budget in self.budgets.items()
        }

    async def sync_field(
        self,
        field: Any,
        kind: str = KIND_BATCH,
        history_years: Optional[int] = None,
        sources: Optional[list[str]] = None,
    ) -> SyncReport:
        """`field` is a Field row or FieldRead (id, account_id, latitude, longitude, boundary). Raises
        BudgetExceeded before spending anything once this kind's monthly budget is used up."""
        report = SyncReport(field_id=str(field.id))
        if not self.copernicus.configured or field.latitude is None or field.longitude is None:
            report.sources = {s: "skipped" for s in (sources or self.sources)}
            return report
        years = self.backfill_years if history_years is None else history_years
        today = utcnow().date()
        geometry = self.copernicus.geometry_hash(field.latitude, field.longitude, field.boundary)
        for source in sources or self.sources:
            if await self.budget_left(kind) <= 0:
                raise BudgetExceeded(f"Copernicus {kind} budget for this month is used up")
            report.sources[source] = await self._sync_source(field, source, kind, geometry, years, today, report)
        return report

    async def _sync_source(
        self, field: Any, source: str, kind: str, geometry: str, years: int, today: date, report: SyncReport
    ) -> str:
        first_available = S2_FIRST_DATE if source == SOURCE_S2 else S1_FIRST_DATE
        wanted_from = max(first_available, _years_before(today, years))
        state = await self.repo.get_sync(field.id, source)
        action = "incremental"
        if state is not None and state.geometry_hash != geometry:
            await self.repo.delete_field_series(field.id, source)
            state = None
            action = "rebuilt (boundary changed)"

        backfill: Optional[tuple[date, date]] = None
        incremental: tuple[date, date]
        if state is None:
            incremental = (wanted_from, today)
            if action == "incremental":
                action = "backfill"
        else:
            if wanted_from < state.history_from:
                backfill = (wanted_from, state.history_from - timedelta(days=1))
                action = "backfill + incremental"
            incremental = (max(state.history_from, state.synced_to - timedelta(days=INCREMENTAL_OVERLAP_DAYS)), today)

        history_from = state.history_from if state else wanted_from
        if backfill and await self._ingest_window(field, source, kind, *backfill, report):
            history_from = wanted_from
        if not await self._ingest_window(field, source, kind, *incremental, report):
            # Nothing is marked as covered that wasn't fully fetched; the next sync retries the window.
            if state is not None and history_from != state.history_from:
                await self.repo.save_sync(
                    field.account_id, field.id, source, geometry, history_from, state.synced_to
                )
            return f"{action} failed"
        await self.repo.save_sync(field.account_id, field.id, source, geometry, history_from, today)
        return action

    async def _ingest_window(
        self, field: Any, source: str, kind: str, start: date, end: date, report: SyncReport
    ) -> bool:
        """Fetch + upsert one window. True only when every request of the window succeeded: partial data is
        still upserted (harmless, idempotent) but the window isn't recorded as covered."""
        result = await self._fetch(field, source, start, end)
        requests = result.requests if result else 1
        units = result.processing_units if result else None
        await self.repo.add_usage(kind, units, requests)
        report.requests += requests
        report.processing_units += units or 0.0
        if result is not None:
            report.observations += await self.repo.upsert_many(
                field.account_id, field.id, source, [_row(o) for o in result.observations]
            )
        if self.pause_seconds:
            await asyncio.sleep(self.pause_seconds)
        return result is not None and result.complete

    async def _fetch(self, field: Any, source: str, start: date, end: date) -> Optional[SeriesResult]:
        if source == SOURCE_S2:
            return await self.copernicus.s2_series(field.latitude, field.longitude, start, end, polygon=field.boundary)
        return await self.copernicus.s1_series(
            field.latitude, field.longitude, start, end, polygon=field.boundary, orbit_direction=self.s1_orbit_direction
        )


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def _row(observation: Any) -> dict:
    return {k: v for k, v in asdict(observation).items()}
