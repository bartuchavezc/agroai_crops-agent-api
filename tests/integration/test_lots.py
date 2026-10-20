"""
Lots (lotes): a batch of one crop, labelled by the user's own season and number, that can span several zones;
zones keep free, user-chosen numbers that can be swapped in one go.
"""
FARM = "/api/v1/farm-management"


async def _field(client, h, name="Huerta"):
    r = await client.post(f"{FARM}/fields", headers=h, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


async def _zone(client, h, field_id, number=None, **extra):
    body = {"type": "cantero", **({"number": number} if number else {}), **extra}
    r = await client.post(f"{FARM}/fields/{field_id}/zones", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _crop_id(client, h, name):
    return (await client.get(f"{FARM}/crop-masters?q={name}", headers=h)).json()[0]["id"]


async def test_a_lot_spans_several_zones_and_is_labelled_by_season_zone_and_number(client, signup):
    h = (await signup("lots-multi"))["headers"]
    field = await _field(client, h)
    z2 = await _zone(client, h, field["id"], 2)
    z3 = await _zone(client, h, field["id"], 3)

    r = await client.post(
        f"{FARM}/lots", headers=h,
        json={
            "field_id": field["id"], "crop_master_id": await _crop_id(client, h, "lechuga"),
            "zone_ids": [z2["id"], z3["id"]], "season": "26/27", "number": 2, "quantity": 40, "unit": "plantas",
            "status": "planted", "planting_date": "2026-10-01",
        },
    )
    assert r.status_code == 201, r.text
    lot = r.json()
    assert lot["zone_ids"] == [z2["id"], z3["id"]]
    assert lot["zone_id"] == z2["id"]  # the first zone names it
    assert lot["label"] == "T26/27 · Cantero 2 + Cantero 3 · L2"

    # listed under both zones
    for zone in (z2, z3):
        listed = (await client.get(f"{FARM}/lots?zone_id={zone['id']}", headers=h)).json()
        assert [x["id"] for x in listed] == [lot["id"]]

    # moving it to a single zone; the shortcut zone_id still works
    moved = (await client.put(f"{FARM}/lots/{lot['id']}", headers=h, json={"zone_id": z3["id"]})).json()
    assert (moved["zone_ids"], moved["label"]) == ([z3["id"]], "T26/27 · Cantero 3 · L2")
    assert (await client.get(f"{FARM}/lots?zone_id={z2['id']}", headers=h)).json() == []

    # a zone of another field is refused
    other = await _zone(client, h, (await _field(client, h, "Otro"))["id"])
    bad = await client.put(f"{FARM}/lots/{lot['id']}", headers=h, json={"zone_ids": [other["id"]]})
    assert bad.status_code == 400

    # deleting a zone frees its lots, which stay in the field
    assert (await client.delete(f"{FARM}/zones/{z3['id']}", headers=h)).status_code == 204
    after = (await client.get(f"{FARM}/lots/{lot['id']}", headers=h)).json()
    assert (after["zone_ids"], after["label"]) == ([], "T26/27 · L2")

    overview = (await client.get(f"{FARM}/overview", headers=h)).json()
    summary = next(f for f in overview if f["field"]["id"] == field["id"])["active_lots"][0]
    assert (summary["season"], summary["number"], summary["label"]) == ("26/27", 2, "T26/27 · L2")


async def test_zones_keep_free_numbers_and_can_be_renumbered_together(client, signup):
    h = (await signup("lots-renumber"))["headers"]
    field = await _field(client, h)
    one = await _zone(client, h, field["id"], 1, length_m=4, width_m=1.2, soil={"ph": 6.5, "notes": "compost"})
    four = await _zone(client, h, field["id"], 4)
    assert (one["area_m2"], one["soil"]["ph"], one["soil"]["notes"]) == (4.8, 6.5, "compost")

    # a single change can't collide with another zone
    clash = await client.put(f"{FARM}/zones/{four['id']}", headers=h, json={"number": 1})
    assert clash.status_code == 400

    # "the 4 should be the 1": swap both at once
    r = await client.post(
        f"{FARM}/fields/{field['id']}/zones/renumber", headers=h,
        json={"numbers": {four["id"]: 1, one["id"]: 4}},
    )
    assert r.status_code == 200, r.text
    assert {z["id"]: z["label"] for z in r.json()} == {four["id"]: "Cantero 1", one["id"]: "Cantero 4"}

    # but never into a duplicate
    dup = await client.post(
        f"{FARM}/fields/{field['id']}/zones/renumber", headers=h, json={"numbers": {four["id"]: 4}}
    )
    assert dup.status_code == 400

    soil = await client.put(f"{FARM}/zones/{one['id']}", headers=h, json={"soil": {"ph": 7.1}})
    assert soil.json()["soil"]["ph"] == 7.1
