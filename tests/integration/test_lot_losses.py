"""
Losses, counts and resowings: a lot keeps what was sown, its live quantity comes from the losses and confirmed counts
in its bitácora, and a resowing is a new lot that points at the one it replaces. Skipped entries carry their reason.
"""
from .test_agent_chat import scripted_model, with_key  # noqa: F401 - fixtures

FARM = "/api/v1/farm-management"


async def _setup(client, h):
    field = (await client.post(f"{FARM}/fields", headers=h, json={"name": "Quinta"})).json()
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    crop = (await client.get(f"{FARM}/crop-masters?q=lechuga", headers=h)).json()[0]["id"]
    lot = (await client.post(f"{FARM}/lots", headers=h, json={
        "field_id": field["id"], "crop_master_id": crop, "zone_ids": [zone["id"]], "season": "26/27", "number": 1,
        "quantity": 120, "unit": "plantas", "status": "planted", "planting_date": "2026-10-01",
    })).json()
    return field, zone, lot


async def test_partial_loss_lowers_the_live_quantity_and_a_resowing_replaces_it(client, signup):
    h = (await signup("losses"))["headers"]
    field, zone, lot = await _setup(client, h)
    assert (lot["quantity"], lot["alive_quantity"], lot["lost_quantity"]) == (120, 120, None)

    r = await client.post(f"{FARM}/lots/{lot['id']}/losses", headers=h, json={"percent": 25, "cause": "no_germination"})
    assert r.status_code == 201, r.text
    assert (r.json()["type"], r.json()["quantity"], r.json()["unit"]) == ("loss", 30, "plantas")
    after = (await client.get(f"{FARM}/lots/{lot['id']}", headers=h)).json()
    assert (after["quantity"], after["alive_quantity"], after["lost_quantity"], after["status"]) == (
        120, 90, 30, "planted"
    )

    # a count resets what is alive; later losses come off it
    assert (await client.post(f"{FARM}/lots/{lot['id']}/counts", headers=h, json={"count": 80})).status_code == 201
    await client.post(f"{FARM}/lots/{lot['id']}/losses", headers=h, json={"quantity": 5, "cause": "pest"})
    after = (await client.get(f"{FARM}/lots/{lot['id']}", headers=h)).json()
    assert (after["alive_quantity"], after["lost_quantity"]) == (75, 35)
    assert after["counted_at"]

    r = await client.post(f"{FARM}/lots/{lot['id']}/resow", headers=h, json={"quantity": 40, "notes": "plantines"})
    assert r.status_code == 201, r.text
    original, resown = r.json()["original"], r.json()["resown"]
    assert original["status"] == "planted" and original["replaced_by_lot_ids"] == [resown["id"]]
    assert (resown["replaces_lot_id"], resown["zone_ids"], resown["quantity"], resown["unit"]) == (
        lot["id"], [zone["id"]], 40, "plantas"
    )
    log = (await client.get(f"{FARM}/log?lot_id={resown['id']}", headers=h)).json()
    assert [i["type"] for d in log["days"] for i in d["items"]] == ["sowing"]

    # a loss of everything fails the lot
    await client.post(f"{FARM}/lots/{resown['id']}/losses", headers=h, json={"percent": 100, "cause": "frost"})
    assert (await client.get(f"{FARM}/lots/{resown['id']}", headers=h)).json()["status"] == "failed"


async def test_a_loss_needs_one_lot_and_an_amount_and_a_skipped_entry_its_reason(client, signup):
    h = (await signup("losses-rules"))["headers"]
    field, zone, lot = await _setup(client, h)
    crop = (await client.get(f"{FARM}/crop-masters?q=tomate", headers=h)).json()[0]["id"]
    await client.post(f"{FARM}/lots", headers=h, json={
        "field_id": field["id"], "crop_master_id": crop, "zone_ids": [zone["id"]], "status": "planted",
    })
    # two lots grow in the zone: a zone-wide loss is ambiguous
    r = await client.post(f"{FARM}/events", headers=h, json={
        "field_id": field["id"], "zone_id": zone["id"], "type": "loss", "quantity": 3,
    })
    assert r.status_code == 400
    r = await client.post(f"{FARM}/events", headers=h, json={"field_id": field["id"], "lot_id": lot["id"], "type": "loss"})
    assert r.status_code == 400

    skipped = await client.post(f"{FARM}/events", headers=h, json={
        "field_id": field["id"], "zone_id": zone["id"], "type": "irrigation", "outcome": "skipped",
    })
    assert skipped.status_code == 422
    skipped = await client.post(f"{FARM}/events", headers=h, json={
        "field_id": field["id"], "zone_id": zone["id"], "type": "irrigation", "outcome": "skipped",
        "reason": "llovió 18 mm",
    })
    assert skipped.status_code == 201, skipped.text
    assert (skipped.json()["outcome"], skipped.json()["reason"], skipped.json()["source"]) == (
        "skipped", "llovió 18 mm", "user"
    )
    log = (await client.get(f"{FARM}/log?zone_id={zone['id']}", headers=h)).json()
    item = log["days"][0]["items"][0]
    assert (item["outcome"], item["reason"]) == ("skipped", "llovió 18 mm")


async def test_the_agent_resows_a_lot_and_logs_a_skipped_watering(client, signup, with_key, scripted_model):
    user = await signup("losses-agent")
    await with_key(user)
    h = user["headers"]
    field, zone, lot = await _setup(client, h)
    scripted_model.script = [
        ("calls", [
            ("resow_lot", {"lot_id": lot["id"], "quantity": 40, "lost_quantity": 40, "cause": "no_germination"}),
            ("log_events", {"field": "Quinta", "entries": [
                {"type": "irrigation", "zone": "cantero 1", "outcome": "skipped", "reason": "llovió anoche"},
            ]}),
        ]),
        ("text", "Listo: registré la pérdida, la resiembra y que hoy no se regó por la lluvia."),
    ]
    r = await client.post("/api/v1/chat", headers=h, json={"message": "no germinaron 40, resembramos; no regué, llovió"})
    assert r.status_code == 200, r.text
    assert all(t["ok"] for t in r.json()["metadata"]["tool_calls"])
    lots = (await client.get(f"{FARM}/lots?field_id={field['id']}", headers=h)).json()
    original = next(x for x in lots if x["id"] == lot["id"])
    resown = next(x for x in lots if x["id"] != lot["id"])
    assert (original["alive_quantity"], original["lost_quantity"]) == (80, 40)
    assert resown["replaces_lot_id"] == lot["id"]
    events = (await client.get(f"{FARM}/events?type=irrigation", headers=h)).json()
    assert (events[0]["outcome"], events[0]["reason"], events[0]["source"]) == ("skipped", "llovió anoche", "agent")
