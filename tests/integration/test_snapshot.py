"""A field's current state in one read: zones with their active lots and last bitácora entry, lots by status, the
next tasks. The same read backs the agent's get_farm_snapshot."""
from .test_agent_chat import scripted_model, with_key  # noqa: F401 - fixtures

FARM = "/api/v1/farm-management"


async def test_snapshot_of_a_field(client, signup):
    h = (await signup("snapshot"))["headers"]
    field = (await client.post(f"{FARM}/fields", headers=h, json={"name": "Huerta"})).json()
    zone1 = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    zone2 = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    await client.put(f"{FARM}/zones/{zone2['id']}", headers=h, json={"soil": {"ph": 6.4}})
    crop = (await client.get(f"{FARM}/crop-masters?q=lechuga", headers=h)).json()[0]["id"]

    async def lot(status, number, season="26/27"):
        r = await client.post(f"{FARM}/lots", headers=h, json={
            "field_id": field["id"], "crop_master_id": crop, "zone_ids": [zone1["id"]], "status": status,
            "season": season, "number": number,
        })
        assert r.status_code == 201, r.text
        return r.json()

    growing = await lot("growing", 1)
    await lot("planned", 2)
    await lot("harvested", 1, season="25/26")
    await client.post(f"{FARM}/events", headers=h, json={
        "field_id": field["id"], "zone_id": zone1["id"], "type": "irrigation", "quantity": 20, "unit": "l",
    })
    for title, due in (("Trasplantar", "2026-12-01"), ("Preparar sustrato", "2026-11-01"), ("Sin fecha", None)):
        await client.post("/api/v1/tasks", headers=h, json={"title": title, "field_id": field["id"], "due_date": due})

    snap = (await client.get(f"{FARM}/fields/{field['id']}/snapshot", headers=h)).json()
    assert snap["lots_by_status"] == {"growing": 1, "planned": 1, "harvested": 1}
    z1, z2 = snap["zones"]
    assert sorted(lot["status"] for lot in z1["lots"]) == ["growing", "planned"]
    assert z1["last_entry"]["type"] == "irrigation" and growing["id"] in z1["last_entry"]["lot_ids"]
    assert z2["lots"] == [] and z2["ph"] == 6.4 and z2["last_entry"] is None
    assert [t["title"] for t in snap["next_tasks"]] == ["Preparar sustrato", "Trasplantar", "Sin fecha"]
    assert snap["recent_log"][0]["type"] == "irrigation"

    older = (await client.get(f"{FARM}/fields/{field['id']}/snapshot?season=25/26", headers=h)).json()
    assert older["lots_by_status"] == {"harvested": 1} and older["zones"][0]["lots"] == []

    stranger = await signup("snapshot-stranger")
    assert (await client.get(f"{FARM}/fields/{field['id']}/snapshot", headers=stranger["headers"])).status_code == 404


async def test_agent_reads_the_snapshot_in_one_call(client, signup, with_key, scripted_model):  # noqa: F811
    user = await signup("snapshot-agent")
    await with_key(user)
    h = user["headers"]
    await client.post(f"{FARM}/fields", headers=h, json={"name": "Huerta"})
    scripted_model.script = [
        ("call", "get_farm_snapshot", {"field": "Huerta", "include": ["lots", "tasks"]}),
        ("text", "Tu huerta todavía no tiene lotes."),
    ]
    body = (await client.post("/api/v1/chat", headers=h, json={"message": "¿cómo está la huerta?"})).json()
    call = body["metadata"]["tool_calls"][0]
    assert call["name"] == "get_farm_snapshot" and call["ok"] is True
