"""Per-zone filters (events, reminders), history paging with `before`, and report date filters."""
from datetime import datetime, timedelta, timezone

FARM = "/api/v1/farm-management"
P = "/api/v1/planning"


async def _field_two_zones(client, h):
    field = (await client.post(f"{FARM}/fields", headers=h, json={"name": "Huerta"})).json()
    zones = []
    for _ in range(2):
        made = await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})
        zones.append(made.json())
    return field, zones


async def test_events_filter_by_zone_and_page_back_with_before(client, signup):
    h = (await signup("zone-events"))["headers"]
    field, (z1, z2) = await _field_two_zones(client, h)
    base = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)

    async def event(zone, day, notes):
        response = await client.post(f"{FARM}/events", headers=h, json={
            "field_id": field["id"], "zone_id": zone["id"], "type": "irrigation", "notes": notes,
            "occurred_at": (base + timedelta(days=day)).isoformat(),
        })
        assert response.status_code == 201, response.text

    for day in range(5):
        await event(z1, day, f"z1-{day}")
    await event(z2, 2, "z2-2")

    only_z1 = (await client.get(f"{FARM}/events?field_id={field['id']}&zone_id={z1['id']}", headers=h)).json()
    assert [e["notes"] for e in only_z1] == [f"z1-{d}" for d in (4, 3, 2, 1, 0)]
    assert {e["zone_id"] for e in only_z1} == {z1["id"]}
    whole = (await client.get(f"{FARM}/events?field_id={field['id']}", headers=h)).json()
    assert len(whole) == 6

    page1 = (await client.get(f"{FARM}/events?zone_id={z1['id']}&limit=2", headers=h)).json()
    assert [e["notes"] for e in page1] == ["z1-4", "z1-3"]
    cursor = page1[-1]["occurred_at"]
    older = {"zone_id": z1["id"], "limit": 2, "before": cursor}
    page2 = (await client.get(f"{FARM}/events", headers=h, params=older)).json()
    assert [e["notes"] for e in page2] == ["z1-2", "z1-1"]


async def test_reminders_filter_by_zone_and_history_pages_newest_first(client, signup):
    h = (await signup("zone-reminders"))["headers"]
    field, (z1, z2) = await _field_two_zones(client, h)
    now = datetime.now(timezone.utc)

    async def reminder(zone, days, title):
        response = await client.post(f"{P}/reminders", headers=h, json={
            "title": title, "field_id": field["id"], "zone_id": zone["id"],
            "due_at": (now + timedelta(days=days)).isoformat(),
        })
        assert response.status_code == 201, response.text

    for days in (-3, -2, -1):
        await reminder(z1, days, f"a{days}")
    await reminder(z2, -2, "b")

    mine = (await client.get(f"{P}/reminders?zone_id={z1['id']}", headers=h)).json()
    assert [r["title"] for r in mine] == ["a-3", "a-2", "a-1"]  # agenda order: oldest first

    history = (await client.get(f"{P}/reminders", headers=h, params={
        "zone_id": z1["id"], "before": (now - timedelta(hours=36)).isoformat(), "limit": 1,
    })).json()
    assert [r["title"] for r in history] == ["a-2"]  # newest of those due before the cursor
    for r in mine:  # overdue ones would be picked up by other tests' reminder batch run
        await client.delete(f"{P}/reminders/{r['id']}", headers=h)
    for r in (await client.get(f"{P}/reminders?zone_id={z2['id']}", headers=h)).json():
        await client.delete(f"{P}/reminders/{r['id']}", headers=h)


async def test_reports_filter_by_date_range(client, signup, container):
    from uuid import UUID

    from src.application.reports.repository import ReportModel
    from src.shared.domain.base import utcnow

    owner = await signup("report-dates")
    h = owner["headers"]
    ids = []
    for day in (1, 10, 20):
        response = await client.post(
            "/api/v1/reports", headers=h, json={"title": f"día {day}", "report_type": "diagnosis"}
        )
        assert response.status_code in (200, 201), response.text
        ids.append(response.json()["id"])
    session_factory = container.db_session_factory()
    async with session_factory() as session:
        for rid, day in zip(ids, (1, 10, 20), strict=True):
            row = await session.get(ReportModel, UUID(rid))
            row.created_at = utcnow().replace(year=2026, month=9, day=day)
        await session.commit()

    def titles(response):
        return sorted(r["title"] for r in response.json())

    async def listed(**params):
        return titles(await client.get("/api/v1/reports", headers=h, params=params))

    assert await listed(since="2026-09-05T00:00:00Z", until="2026-09-15T00:00:00Z") == ["día 10"]
    assert await listed(since="2026-09-05T00:00:00Z") == ["día 10", "día 20"]
    assert await listed(until="2026-09-05T00:00:00Z") == ["día 1"]


async def test_zone_timeline_merges_events_analyses_and_done_reminders(client, signup, container):
    from unittest.mock import AsyncMock, patch

    from .test_zones import _TINY_PNG, _cycle, _zone_result

    h = (await signup("timeline"))["headers"]
    field, (zone, other) = await _field_two_zones(client, h)
    cycle = await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])
    base = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    for day, notes in ((1, "riego chico"), (3, "riego grande")):
        await client.post(f"{FARM}/events", headers=h, json={
            "field_id": field["id"], "zone_id": zone["id"], "type": "irrigation", "notes": notes,
            "occurred_at": (base + timedelta(days=day)).isoformat(),
        })
    await client.post(f"{FARM}/events", headers=h, json={
        "field_id": field["id"], "zone_id": other["id"], "type": "pruning", "occurred_at": base.isoformat(),
    })

    fake = AsyncMock(return_value=_zone_result([(cycle, "Tomate")]))
    with patch.object(container.agent.gemini(), "generate_structured", fake):
        up = await client.post(
            "/api/v1/upload/zone-tracking", headers=h, data={"zone_id": zone["id"]},
            files=[("image_files", ("a.png", _TINY_PNG, "image/png"))],
        )
    assert up.status_code == 200, up.text

    # a recurring reminder done twice leaves two records (only the first used to be visible, as `due_at`)
    reminder = (await client.post(f"{P}/reminders", headers=h, json={
        "title": "Regar el cantero", "field_id": field["id"], "zone_id": zone["id"], "recurrence": "daily",
        "due_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    })).json()
    for _ in range(2):
        assert (await client.post(f"{P}/reminders/{reminder['id']}/complete", headers=h)).status_code == 200

    await client.delete(f"{P}/reminders/{reminder['id']}", headers=h)  # keep the batch of other tests clean
    items = (await client.get(f"{FARM}/zones/{zone['id']}/timeline", headers=h)).json()
    assert [i["kind"] for i in items] == ["reminder", "reminder", "analysis", "event", "event"]  # newest first
    assert items[0]["title"] == "Regar el cantero" and items[2]["ref_id"] == up.json()["report_id"]
    assert [i["detail"] for i in items if i["kind"] == "event"] == ["riego grande", "riego chico"]
    assert not any(i["type"] == "pruning" for i in items)  # the other zone's event stays out

    page = {"before": items[2]["at"]}
    older = (await client.get(f"{FARM}/zones/{zone['id']}/timeline", headers=h, params=page)).json()
    assert [i["kind"] for i in older] == ["event", "event"]
    assert len((await client.get(f"{FARM}/zones/{zone['id']}/timeline?limit=2", headers=h)).json()) == 2
    assert (await client.get(f"{FARM}/zones/{zone['id']}", headers=h)).json()["id"] == zone["id"]
    stranger = await signup("timeline-stranger")
    assert (await client.get(f"{FARM}/zones/{zone['id']}/timeline", headers=stranger["headers"])).status_code == 404


async def test_planning_calendar_expands_recurrences_and_lists_stages_and_sowings(client, signup):
    owner = await signup("calendar")
    h = owner["headers"]
    field, (zone, _) = await _field_two_zones(client, h)
    other_field = (await client.post(f"{FARM}/fields", headers=h, json={"name": "Otro"})).json()
    start = datetime(2026, 11, 2, 9, tzinfo=timezone.utc)

    async def reminder(title, **extra):
        response = await client.post(f"{P}/reminders", headers=h, json={
            "title": title, "field_id": field["id"], "due_at": start.isoformat(), **extra,
        })
        assert response.status_code == 201, response.text
        return response.json()

    weekly = await reminder("Revisar riego", recurrence="weekly")
    await reminder("Una vez", due_at=(start + timedelta(days=3)).isoformat())
    await client.post(f"{P}/reminders", headers=h, json={
        "title": "De otro campo", "field_id": other_field["id"], "due_at": start.isoformat()})

    plan = (await client.post(f"{P}/plans", headers=h, json={
        "name": "Temporada", "field_id": field["id"], "kind": "largo", "status": "activo",
    })).json()
    stage = await client.post(f"{P}/plans/{plan['id']}/stages", headers=h, json={
        "name": "Crecimiento", "stage": "vegetativo", "start_date": "2026-11-10", "end_date": "2026-12-20",
    })
    assert stage.status_code == 201, stage.text
    tomato = (await client.get(f"{FARM}/crop-masters?q=tomate", headers=h)).json()[0]["id"]
    sowing = await client.post(f"{P}/plans/{plan['id']}/sowings", headers=h, json={
        "crop_master_id": tomato, "sow_date": "2026-11-15", "zone_id": zone["id"],
    })
    assert sowing.status_code == 201, sowing.text

    month = (await client.get(f"{P}/calendar", headers=h, params={
        "since": "2026-11-01", "until": "2026-11-30", "field_id": field["id"],
    })).json()
    weekly_days = [i["date"] for i in month["items"] if i["ref_id"] == weekly["id"]]
    assert weekly_days == ["2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23", "2026-11-30"]
    titles = {(i["kind"], i["title"]) for i in month["items"]}
    assert ("reminder", "Una vez") in titles and ("sowing", "Sembrar Tomate") in titles
    assert ("stage", "Crecimiento") in titles and not any(t == "De otro campo" for _, t in titles)
    spans = [(r["start"], r["end"], r["stage"]) for r in month["ranges"]]
    assert spans == [("2026-11-10", "2026-12-20", "vegetativo")]
    assert month["items"] == sorted(month["items"], key=lambda i: (i["date"], i["due_at"] or "", i["kind"]))

    dec = {"since": "2026-12-01", "until": "2026-12-31"}
    december = (await client.get(f"{P}/calendar", headers=h, params=dec)).json()
    assert [i["date"] for i in december["items"] if i["ref_id"] == weekly["id"]][:2] == ["2026-12-07", "2026-12-14"]
    assert len(december["ranges"]) == 1 and not any(i["kind"] == "stage" for i in december["items"])  # started in Nov

    backwards = await client.get(f"{P}/calendar", headers=h, params={"since": "2026-12-01", "until": "2026-11-01"})
    assert backwards.status_code == 400
    too_long = await client.get(f"{P}/calendar", headers=h, params={"since": "2024-01-01", "until": "2026-01-01"})
    assert too_long.status_code == 400
