"""SatelliteIngestService sync logic with in-memory fakes: which windows it asks Copernicus for, how it
records coverage, and when it refuses to spend."""
import asyncio
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from src.application.satellite import ingest as ingest_module
from src.application.satellite.ingest import KIND_BATCH, KIND_ON_DEMAND, BudgetExceeded, SatelliteIngestService
from src.application.satellite.models import SOURCE_S1, SOURCE_S2
from src.providers.satellite.copernicus import CopernicusAdapter, S2Observation, SeriesResult

TODAY = date(2026, 10, 8)


class FakeRepo:
    def __init__(self):
        self.rows: dict[tuple, dict] = {}
        self.sync: dict[tuple, SimpleNamespace] = {}
        self.usage: dict[str, float] = {}
        self.chips: dict[tuple, object] = {}

    async def upsert_many(self, account_id, field_id, source, observations):
        for obs in observations:
            self.rows[(field_id, obs["observed_on"], source)] = obs
        return len(observations)

    async def delete_field_series(self, field_id, source):
        self.rows = {k: v for k, v in self.rows.items() if not (k[0] == field_id and k[2] == source)}
        self.sync.pop((field_id, source), None)
        if source == SOURCE_S2:
            self.chips = {k: v for k, v in self.chips.items() if k[0] != field_id}

    async def series(self, account_id, field_id, source, since=None):
        return [
            SimpleNamespace(**row) for (fid, day, src), row in sorted(self.rows.items(), key=lambda kv: kv[0][1])
            if fid == field_id and src == source and (since is None or day >= since)
        ]

    async def chip_dates(self, field_id):
        return {day for (fid, day) in self.chips if fid == field_id}

    async def add_chip(self, chip):
        self.chips[(chip.field_id, chip.observed_on)] = chip

    async def get_sync(self, field_id, source):
        return self.sync.get((field_id, source))

    async def save_sync(self, account_id, field_id, source, geometry_hash, history_from, synced_to):
        self.sync[(field_id, source)] = SimpleNamespace(
            geometry_hash=geometry_hash, history_from=history_from, synced_to=synced_to
        )

    async def add_usage(self, kind, processing_units, requests=1):
        self.usage[kind] = self.usage.get(kind, 0.0) + (processing_units or 0.0)

    async def usage_this_month(self):
        return dict(self.usage)


class FakeCopernicus:
    configured = True
    geometry_hash = staticmethod(CopernicusAdapter.geometry_hash)

    def __init__(self, fail=False, units=1.5):
        self.calls: list[tuple] = []
        self.fail = fail
        self.units = units

    async def s2_series(self, lat, lon, start, end, polygon=None):
        self.calls.append((SOURCE_S2, start, end))
        if self.fail:
            return None
        obs = [S2Observation(observed_on=end, total_pixels=100, valid_pixels=90, valid_fraction=0.9, ndvi_mean=0.5)]
        return SeriesResult(observations=obs, processing_units=self.units, requests=1)

    async def s1_series(self, lat, lon, start, end, polygon=None, orbit_direction="DESCENDING"):
        self.calls.append((SOURCE_S1, start, end))
        return SeriesResult(observations=[], processing_units=self.units, requests=1)


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(ingest_module, "utcnow", lambda: datetime(2026, 10, 8, 12, tzinfo=timezone.utc))


def _field(boundary=None):
    return SimpleNamespace(id=uuid.uuid4(), account_id=uuid.uuid4(), latitude=-34.6, longitude=-58.4, boundary=boundary)


def _service(repo, copernicus, **kwargs):
    return SatelliteIngestService(repo, copernicus, backfill_years=3, s1_enabled=False, pause_seconds=0, **kwargs)


def run(coro):
    return asyncio.run(coro)


def test_first_sync_backfills_the_configured_years():
    repo, cop, field = FakeRepo(), FakeCopernicus(), _field()
    report = run(_service(repo, cop).sync_field(field))
    assert cop.calls == [(SOURCE_S2, date(2023, 10, 8), TODAY)]
    state = repo.sync[(field.id, SOURCE_S2)]
    assert (state.history_from, state.synced_to) == (date(2023, 10, 8), TODAY)
    assert report.sources[SOURCE_S2] == "backfill"
    assert repo.usage[KIND_BATCH] == 1.5


def test_next_sync_is_incremental_with_overlap_and_upserts():
    repo, cop, field = FakeRepo(), FakeCopernicus(), _field()
    service = _service(repo, cop)
    run(service.sync_field(field))
    repo.sync[(field.id, SOURCE_S2)].synced_to = TODAY - timedelta(days=3)
    run(service.sync_field(field))
    assert cop.calls[-1] == (SOURCE_S2, TODAY - timedelta(days=18), TODAY)
    assert len(repo.rows) == 1  # the same pass date twice is one row


def test_more_years_backfills_only_the_missing_older_window():
    repo, cop, field = FakeRepo(), FakeCopernicus(), _field()
    service = _service(repo, cop)
    run(service.sync_field(field, history_years=1))
    run(service.sync_field(field, history_years=3))
    assert cop.calls[1] == (SOURCE_S2, date(2023, 10, 8), date(2025, 10, 7))
    assert repo.sync[(field.id, SOURCE_S2)].history_from == date(2023, 10, 8)


def test_redrawn_boundary_rebuilds_the_series():
    repo, cop, field = FakeRepo(), FakeCopernicus(), _field()
    service = _service(repo, cop)
    run(service.sync_field(field))
    field.boundary = [(-34.60, -58.40), (-34.61, -58.40), (-34.61, -58.41)]
    report = run(service.sync_field(field))
    assert report.sources[SOURCE_S2].startswith("rebuilt")
    assert cop.calls[-1] == (SOURCE_S2, date(2023, 10, 8), TODAY)
    expected = CopernicusAdapter.geometry_hash(-34.6, -58.4, field.boundary)
    assert repo.sync[(field.id, SOURCE_S2)].geometry_hash == expected


def test_failed_request_does_not_mark_the_window_as_covered():
    repo, field = FakeRepo(), _field()
    report = run(_service(repo, FakeCopernicus(fail=True)).sync_field(field))
    assert report.sources[SOURCE_S2].endswith("failed")
    assert (field.id, SOURCE_S2) not in repo.sync


def test_budget_is_checked_per_kind_before_spending():
    repo, cop, field = FakeRepo(), FakeCopernicus(), _field()
    repo.usage[KIND_BATCH] = 7000.0
    service = _service(repo, cop, batch_pu_budget=7000, on_demand_pu_budget=100)
    with pytest.raises(BudgetExceeded):
        run(service.sync_field(field, kind=KIND_BATCH))
    assert cop.calls == []
    run(service.sync_field(field, kind=KIND_ON_DEMAND))  # user-facing share is separate
    assert cop.calls


def test_s1_is_synced_too_when_enabled():
    repo, cop, field = FakeRepo(), FakeCopernicus(), _field()
    service = SatelliteIngestService(repo, cop, backfill_years=1, s1_enabled=True, pause_seconds=0)
    report = run(service.sync_field(field))
    assert {c[0] for c in cop.calls} == {SOURCE_S2, SOURCE_S1}
    assert set(report.sources) == {SOURCE_S2, SOURCE_S1}


class FakeQuality:
    def __init__(self, dates):
        self.dates = dates

    def result(self):
        from src.providers.satellite.copernicus import S2Quality

        return SeriesResult(
            observations=[S2Quality(d, 100, 0.7, 0.2, 0.0) for d in self.dates], processing_units=0.5, requests=1
        )


def test_passes_get_their_loss_causes_and_fully_masked_dates_are_kept_as_discarded_rows():
    repo, cop, field = FakeRepo(), FakeCopernicus(), _field()
    cloudy_day = date(2026, 9, 1)

    async def s2_quality(lat, lon, start, end, polygon=None):
        return FakeQuality([TODAY, cloudy_day]).result()

    cop.s2_quality = s2_quality
    report = run(_service(repo, cop).sync_field(field))
    rows = {k[1]: v for k, v in repo.rows.items() if k[2] == SOURCE_S2}
    clear = rows[TODAY]
    assert (clear["cloud_fraction"], clear["shadow_fraction"], clear["nodata_fraction"]) == (0.7, 0.2, 0.0)
    masked = rows[cloudy_day]
    assert masked["ndvi_mean"] is None and masked["valid_pixels"] == 0 and masked["valid_fraction"] == 0.0
    assert masked["cloud_fraction"] == 0.7
    assert repo.usage[KIND_BATCH] == 2.0  # 1.5 for the indices + 0.5 for the quality request
    assert report.requests == 2


def test_a_failing_quality_request_never_costs_the_series():
    repo, cop, field = FakeRepo(), FakeCopernicus(), _field()

    async def s2_quality(lat, lon, start, end, polygon=None):
        raise RuntimeError("boom")

    cop.s2_quality = s2_quality
    report = run(_service(repo, cop).sync_field(field))
    assert report.sources[SOURCE_S2] == "backfill" and len(repo.rows) == 1
    row = next(iter(repo.rows.values()))
    assert row["cloud_fraction"] is None


class ChipCopernicus(FakeCopernicus):
    """Also serves chips: records which days were asked for; `broken` days fail."""

    def __init__(self, broken=(), **kwargs):
        super().__init__(**kwargs)
        self.chip_calls: list[tuple] = []
        self.broken = set(broken)

    async def s2_chip(self, bbox, width, height, day):
        import numpy as np

        self.chip_calls.append((tuple(bbox), width, height, day))
        if day in self.broken:
            return None
        return SimpleNamespace(pixels=np.ones((8, height, width), dtype="<u2"), processing_units=0.01)


def _series(repo, field, days, valid=0.9, ndvi=0.5):
    for day in days:
        repo.rows[(field.id, day, SOURCE_S2)] = {
            "observed_on": day, "ndvi_mean": ndvi, "valid_fraction": valid, "valid_pixels": 90,
        }


def test_fill_chips_fetches_only_usable_passes_that_have_none_newest_first():
    repo, cop, field = FakeRepo(), ChipCopernicus(), _field()
    usable = [TODAY - timedelta(days=n) for n in (2, 7, 12)]
    _series(repo, field, usable)
    _series(repo, field, [TODAY - timedelta(days=20)], valid=0.02)  # almost fully clouded: adds nothing to a map
    _series(repo, field, [TODAY - timedelta(days=25)], ndvi=None)  # fully masked, no values
    done = run(_service(repo, cop).fill_chips(field))
    assert [call[3] for call in cop.chip_calls] == usable and done.fetched == 3 and done.stopped is None
    assert set(repo.chips) == {(field.id, d) for d in usable}
    stored = repo.chips[(field.id, usable[0])]
    assert stored.geometry_hash == CopernicusAdapter.geometry_hash(-34.6, -58.4, None)
    assert (stored.width, stored.height) == (cop.chip_calls[0][1], cop.chip_calls[0][2])
    assert repo.usage[KIND_BATCH] == pytest.approx(0.03) and done.processing_units == pytest.approx(0.03)

    cop.chip_calls.clear()
    again = run(_service(repo, cop).fill_chips(field))  # nothing missing: no request at all
    assert cop.chip_calls == [] and again.fetched == 0


def test_the_daily_sync_keeps_the_last_days_and_the_backfill_every_pass():
    repo, cop, field = FakeRepo(), ChipCopernicus(), _field()
    old = TODAY - timedelta(days=100)
    _series(repo, field, [old, TODAY - timedelta(days=5)])
    report = run(_service(repo, cop).sync_field(field))
    assert {call[3] for call in cop.chip_calls} == {TODAY - timedelta(days=5), TODAY}  # recent only (+ the new pass)
    assert report.chips == 2

    cop.chip_calls.clear()
    report = run(_service(repo, cop).sync_field(field, chips="all"))
    assert {call[3] for call in cop.chip_calls} == {old}  # what was still missing
    assert report.chips == 1

    cop.chip_calls.clear()
    other_repo, other_field = FakeRepo(), _field()
    _series(other_repo, other_field, [TODAY - timedelta(days=5)])
    assert run(_service(other_repo, cop).sync_field(other_field, chips="none")).chips == 0
    assert cop.chip_calls == []


def test_chips_stop_when_the_budget_is_used_up_or_requests_keep_failing():
    repo, cop, field = FakeRepo(), ChipCopernicus(), _field()
    days = [TODAY - timedelta(days=n) for n in range(1, 7)]
    _series(repo, field, days)
    repo.usage[KIND_BATCH] = 6999.995
    done = run(_service(repo, cop, batch_pu_budget=7000).fill_chips(field))
    assert done.fetched == 1 and done.stopped == "budget"  # the second request found the month used up

    repo2, field2 = FakeRepo(), _field()
    _series(repo2, field2, days)
    failing = ChipCopernicus(broken=days)
    done = run(_service(repo2, failing).fill_chips(field2))
    assert done.fetched == 0 and done.stopped == "failed" and len(failing.chip_calls) == 3  # gave up after 3 in a row
    flaky = ChipCopernicus(broken=[days[0]])
    repo3, field3 = FakeRepo(), _field()
    _series(repo3, field3, days)
    assert run(_service(repo3, flaky).fill_chips(field3)).fetched == 5  # one failure doesn't stop the rest


def test_a_redrawn_boundary_drops_the_old_chips_with_the_series():
    repo, cop, field = FakeRepo(), ChipCopernicus(), _field()
    run(_service(repo, cop).sync_field(field))
    assert repo.chips
    field.boundary = [(-34.60, -58.40), (-34.61, -58.40), (-34.61, -58.41)]
    cop.chip_calls.clear()
    run(_service(repo, cop).sync_field(field))
    assert {k[0] for k in repo.chips} == {field.id}
    assert all(chip.geometry_hash == CopernicusAdapter.geometry_hash(-34.6, -58.4, field.boundary)
               for chip in repo.chips.values())
