"""
Planning: reminders notified in-app when due (one-off, recurring, per assignee), a crop cycle's stage plan
from its crop's template, and long plans with staggered sowings that split a seed lot over time.
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .test_agent_chat import scripted_model, with_key  # noqa: F401 - fixtures

FARM = "/api/v1/farm-management"
P = "/api/v1/planning"


TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _local(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(TZ).isoformat()


async def _field_zone(client, h):
    field = (await client.post(f"{FARM}/fields", headers=h, json={"name": "Huerta"})).json()
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    return field, zone


async def _crop_id(client, h, q):
    return (await client.get(f"{FARM}/crop-masters?q={q}", headers=h)).json()[0]["id"]


async def _unread(client, user):
    return (await client.get("/api/v1/notifications", headers=user["headers"])).json()


async def test_due_reminders_become_notifications_once(client, signup, add_member, container):
    owner = await signup("rem")
    staff = await add_member(owner, "staff")
    h = owner["headers"]
    past = datetime.now(timezone.utc) - timedelta(minutes=5)

    everyone = await client.post(f"{P}/reminders", headers=h, json={"title": "Regar el cantero", "due_at": _iso(past)})
    assert everyone.status_code == 201, everyone.text
    only_staff = await client.post(
        f"{P}/reminders", headers=h,
        json={"title": "Cosechar lechuga", "due_at": _iso(past), "assigned_to": staff["user"]["id"]},
    )
    future = await client.post(
        f"{P}/reminders", headers=h,
        json={"title": "Más adelante", "due_at": _iso(past + timedelta(days=3))},
    )
    assert only_staff.status_code == 201 and future.status_code == 201

    planning = container.application.planning_service()
    assert (await planning.run_due_reminders())["notified"] == 2
    assert (await planning.run_due_reminders())["notified"] == 0  # once per occurrence

    owner_titles = [n["title"] for n in await _unread(client, owner) if n["type"] == "reminder"]
    staff_titles = sorted(n["title"] for n in await _unread(client, staff) if n["type"] == "reminder")
    assert owner_titles == ["Regar el cantero"]
    assert staff_titles == ["Cosechar lechuga", "Regar el cantero"]
    note = next(n for n in await _unread(client, staff) if n["title"] == "Cosechar lechuga")
    assert note["entity_type"] == "reminder" and note["entity_id"] == only_staff.json()["id"]

    # A notified one-off stays pending (overdue) until it's ticked.
    agenda = (await client.get(f"{P}/reminders?status=pendiente", headers=staff["headers"])).json()
    assert {r["title"] for r in agenda} == {"Regar el cantero", "Cosechar lechuga", "Más adelante"}
    done = await client.post(f"{P}/reminders/{everyone.json()['id']}/complete", headers=staff["headers"])
    assert done.json()["status"] == "hecho" and done.json()["completed_at"]


async def test_recurring_reminders_move_to_the_next_occurrence(client, signup, container):
    owner = await signup("rem-rec")
    h = owner["headers"]
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    weekly = (
        await client.post(
            f"{P}/reminders", headers=h, json={"title": "Fertilizar", "due_at": _iso(start), "recurrence": "weekly"}
        )
    ).json()
    short = (
        await client.post(
            f"{P}/reminders", headers=h,
            json={"title": "Revisar plagas", "due_at": _iso(start), "recurrence": "every_n_days", "interval_days": 3,
                  "until": (date.today() + timedelta(days=1)).isoformat()},
        )
    ).json()
    bad = await client.post(
        f"{P}/reminders", headers=h, json={"title": "x", "due_at": _iso(start), "recurrence": "every_n_days"}
    )
    assert bad.status_code == 422

    await container.application.planning_service().run_due_reminders()
    reminders = {r["title"]: r for r in (await client.get(f"{P}/reminders", headers=h)).json()}
    next_due = datetime.fromisoformat(reminders["Fertilizar"]["due_at"])
    assert abs(next_due - (datetime.fromisoformat(weekly["due_at"]) + timedelta(days=7))) < timedelta(seconds=1)
    assert reminders["Fertilizar"]["status"] == "pendiente"
    assert reminders["Revisar plagas"]["status"] == "hecho"  # next one (3 days) would be past `until`

    # Ticking a recurring one early skips to the occurrence after.
    ticked = (await client.post(f"{P}/reminders/{weekly['id']}/complete", headers=h)).json()
    assert datetime.fromisoformat(ticked["due_at"]) - next_due == timedelta(days=7)
    assert ticked["status"] == "pendiente"
    assert short["recurrence"] == "every_n_days"


async def test_crop_cycle_stage_plan_from_template(client, signup):
    owner = await signup("stageplan")
    h = owner["headers"]
    field, zone = await _field_zone(client, h)
    sown = date.today()
    cycle = (
        await client.post(
            f"{FARM}/crop-cycles", headers=h,
            json={"field_id": field["id"], "zone_id": zone["id"], "crop_master_id": await _crop_id(client, h, "tomate"),
                  "status": "planted", "planting_date": sown.isoformat(),
                  "expected_harvest_date": (sown + timedelta(days=100)).isoformat()},
        )
    ).json()

    preview = (await client.get(f"{P}/crop-cycles/{cycle['id']}/stage-plan", headers=h)).json()
    stages = [s["stage"] for s in preview["stages"]]
    assert stages[0] == "germinacion" and "plantin" in stages and stages[-1] == "cosecha"
    titles = [r["title"] for r in preview["reminders"]]
    assert any(t.startswith("Revisar germinación") for t in titles)
    assert any(t.startswith("Traspasar") for t in titles)
    assert any("Posible cosecha" in t for t in titles) and any("Cosecha estimada" in t for t in titles)
    transplant = next(r for r in preview["reminders"] if r["title"].startswith("Traspasar"))
    assert _local(transplant["due_at"]).startswith((sown + timedelta(days=35)).isoformat() + "T09:00")
    assert (await client.get(f"{P}/plans", headers=h)).json() == []  # preview saves nothing

    applied = (await client.post(f"{P}/crop-cycles/{cycle['id']}/stage-plan", headers=h)).json()
    plan = (await client.get(f"{P}/plans/{applied['plan_id']}", headers=h)).json()
    assert plan["kind"] == "ciclo" and plan["crop_cycle_id"] == cycle["id"] and "Cantero 1" in plan["name"]
    assert len(plan["stages"]) == len(preview["stages"])
    assert len(plan["reminders"]) == len(preview["reminders"])
    assert all(r["zone_id"] == zone["id"] and r["crop_cycle_id"] == cycle["id"] for r in plan["reminders"])

    # Regenerating replaces, without duplicating; a reminder already done is kept.
    await client.post(f"{P}/reminders/{plan['reminders'][0]['id']}/complete", headers=h)
    await client.post(f"{P}/crop-cycles/{cycle['id']}/stage-plan", headers=h)
    again = (await client.get(f"{P}/plans/{applied['plan_id']}", headers=h)).json()
    assert len(again["stages"]) == len(preview["stages"])
    assert len(again["reminders"]) == len(preview["reminders"]) + 1
    assert len((await client.get(f"{P}/plans", headers=h)).json()) == 1


async def test_long_plan_with_staggered_sowings_and_seed_lot(client, signup):
    owner = await signup("longplan")
    h = owner["headers"]
    field, zone = await _field_zone(client, h)
    lettuce = await _crop_id(client, h, "lechuga")
    lot = (
        await client.post("/api/v1/inventory/seed-lots", headers=h, json={"crop_master_id": lettuce, "quantity": 500})
    ).json()

    plan = await client.post(
        f"{P}/plans", headers=h,
        json={"name": "Huerta perpetua 2027", "kind": "largo", "field_id": field["id"],
              "start_date": "2026-10-01", "end_date": "2027-09-30",
              "stages": [{"name": "Poda invernal de frutales", "stage": "poda", "start_date": "2027-07-01",
                          "end_date": "2027-07-31", "remind": True}]},
    )
    assert plan.status_code == 201, plan.text
    plan = plan.json()
    assert len(plan["stages"]) == 1 and plan["reminders"][0]["title"].endswith("Poda invernal de frutales")

    start = date.today() + timedelta(days=1)
    sowings = await client.post(
        f"{P}/plans/{plan['id']}/sowings/staggered", headers=h,
        json={"crop_master_id": lettuce, "zone_id": zone["id"], "start_date": start.isoformat(), "count": 3,
              "every_days": 15, "total_quantity": 300, "unit": "semillas", "seed_lot_id": lot["id"]},
    )
    assert sowings.status_code == 201, sowings.text
    sowings = sowings.json()
    assert [s["sow_date"] for s in sowings] == [(start + timedelta(days=15 * i)).isoformat() for i in range(3)]
    assert all(s["quantity"] == 100 for s in sowings)
    detail = (await client.get(f"{P}/plans/{plan['id']}", headers=h)).json()
    sow_reminders = [r for r in detail["reminders"] if r["sowing_id"]]
    assert len(sow_reminders) == 3
    assert "Sembrar Lechuga" in sow_reminders[0]["title"] and "Cantero 1" in sow_reminders[0]["title"]

    # The first sowing happens: crop cycle in the zone, seed discounted, its reminder done, stage reminders.
    done = (await client.post(f"{P}/sowings/{sowings[0]['id']}/sow", headers=h, json={})).json()
    assert done["status"] == "sembrado" and done["crop_cycle_id"]
    cycle = (await client.get(f"{FARM}/crop-cycles/{done['crop_cycle_id']}", headers=h)).json()
    assert cycle["zone_id"] == zone["id"] and cycle["status"] == "planted"
    lots = (await client.get("/api/v1/inventory/seed-lots", headers=h)).json()
    assert lots[0]["quantity"] == 400
    reminders = (await client.get(f"{P}/reminders?plan_id={plan['id']}", headers=h)).json()
    assert next(r for r in reminders if r["sowing_id"] == sowings[0]["id"])["status"] == "hecho"
    cycle_plans = [p for p in (await client.get(f"{P}/plans", headers=h)).json() if p["crop_cycle_id"] == cycle["id"]]
    assert len(cycle_plans) == 1
    assert (await client.post(f"{P}/sowings/{sowings[0]['id']}/sow", headers=h, json={})).status_code == 400

    # Archiving the long plan cancels what's still pending.
    await client.put(f"{P}/plans/{plan['id']}", headers=h, json={"status": "archivado"})
    left = (await client.get(f"{P}/reminders?plan_id={plan['id']}&status=pendiente", headers=h)).json()
    assert left == []


async def test_permissions_and_account_isolation(client, signup, add_member):
    owner = await signup("plan-perm")
    staff = await add_member(owner, "staff")
    other = await signup("plan-other")
    field, _ = await _field_zone(client, owner["headers"])
    lettuce = await _crop_id(client, other["headers"], "lechuga")
    foreign_lot = (
        await client.post(
            "/api/v1/inventory/seed-lots", headers=other["headers"], json={"crop_master_id": lettuce, "quantity": 5}
        )
    ).json()

    mine = await client.post(
        f"{P}/reminders", headers=staff["headers"],
        json={"title": "Regar", "due_at": _iso(datetime.now(timezone.utc)), "field_id": field["id"]},
    )
    assert mine.status_code == 201
    assert (await client.post(f"{P}/plans", headers=staff["headers"], json={"name": "x"})).status_code == 403
    plan = (await client.post(f"{P}/plans", headers=owner["headers"], json={"name": "Plan"})).json()
    stolen = await client.post(
        f"{P}/plans/{plan['id']}/sowings", headers=owner["headers"],
        json={"crop_master_id": lettuce, "sow_date": "2026-11-01", "seed_lot_id": foreign_lot["id"]},
    )
    assert stolen.status_code == 404
    other_field = await client.post(
        f"{P}/reminders", headers=other["headers"],
        json={"title": "x", "due_at": _iso(datetime.now(timezone.utc)), "field_id": field["id"]},
    )
    assert other_field.status_code == 404
    assert (await client.get(f"{P}/reminders", headers=other["headers"])).json() == []


async def test_agent_schedules_reminder_and_staggered_sowing(client, signup, with_key, scripted_model):  # noqa: F811
    owner = await signup("plan-agent")
    await with_key(owner)
    h = owner["headers"]
    field, zone = await _field_zone(client, h)
    plan = (
        await client.post(f"{P}/plans", headers=h, json={"name": "Lechugas todo el año", "field_id": field["id"]})
    ).json()

    scripted_model.script = [
        ("call", "add_reminder", {"title": "Regar cantero 1", "when": "2026-12-01", "recurrence": "every_n_days",
                                  "every_days": 2, "assignee": "yo", "zone": "cantero 1"}),
        ("call", "plan_staggered_sowing", {"plan_id": plan["id"], "crop": "lechuga", "start_date": "2026-12-01",
                                           "count": 4, "every_days": 14, "zone": "cantero 1", "total_quantity": 200,
                                           "unit": "semillas"}),
        ("text", "Listo."),
    ]
    r = await client.post("/api/v1/chat", headers=h, json={"message": "recordame regar y planificá lechugas"})
    assert r.status_code == 200, r.text
    assert all(t["ok"] for t in r.json()["metadata"]["tool_calls"]), r.json()["metadata"]["tool_calls"]

    reminders = (await client.get(f"{P}/reminders", headers=h)).json()
    water = next(r for r in reminders if r["title"] == "Regar cantero 1")
    assert _local(water["due_at"]).startswith("2026-12-01T09:00") and water["interval_days"] == 2
    assert water["assigned_to"] == owner["user"]["id"] and water["zone_id"] == zone["id"] and water["source"] == "agent"
    detail = (await client.get(f"{P}/plans/{plan['id']}", headers=h)).json()
    assert [s["quantity"] for s in detail["sowings"]] == [50, 50, 50, 50]
