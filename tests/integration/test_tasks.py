"""
Tasks: work with someone in charge and a state, on a field, zone, lot and/or plan. Finishing one can log its
result in the bitácora (and move the lot forward); done tasks show in the bitácora too.
"""
FARM = "/api/v1/farm-management"
T = "/api/v1/tasks"


async def _setup(client, h):
    field = (await client.post(f"{FARM}/fields", headers=h, json={"name": "Huerta"})).json()
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    crop = (await client.get(f"{FARM}/crop-masters?q=tomate", headers=h)).json()[0]["id"]
    seedbed = (await client.post(f"{FARM}/lots", headers=h, json={
        "field_id": field["id"], "crop_master_id": crop, "zone_id": zone["id"], "status": "seedbed",
        "planting_date": "2026-09-01",
    })).json()
    return field, zone, seedbed


async def test_tasks_by_place_status_and_result_in_the_bitacora(client, signup, add_member):
    owner = await signup("tasks")
    staff = await add_member(owner, "staff")
    h = owner["headers"]
    field, zone, seedbed = await _setup(client, h)

    prep = await client.post(T, headers=h, json={
        "title": "Preparar sustrato", "zone_id": zone["id"], "assigned_to": staff["user"]["id"],
        "result_event_type": "soil_prep", "due_date": "2026-10-25",
    })
    assert prep.status_code == 201, prep.text
    assert prep.json()["field_id"] == field["id"]  # taken from the zone
    transplant = (await client.post(T, headers=h, json={
        "title": "Trasplantar tomates", "lot_id": seedbed["id"], "result_event_type": "transplant",
    })).json()
    general = (await client.post(T, headers=h, json={"title": "Comprar media sombra"})).json()

    # a zone's tasks include those of its lots
    in_zone = {t["id"] for t in (await client.get(f"{T}?zone_id={zone['id']}", headers=h)).json()}
    assert in_zone == {prep.json()["id"], transplant["id"]}
    mine = (await client.get(f"{T}?assigned_to={staff['user']['id']}", headers=h)).json()
    assert [t["id"] for t in mine] == [prep.json()["id"]]
    no_field = (await client.get(f"{T}?field_id=none", headers=h)).json()
    assert [t["id"] for t in no_field] == [general["id"]]

    # staff works on their tasks: in progress, blocked, done
    sh = staff["headers"]
    assert (await client.put(f"{T}/{prep.json()['id']}", headers=sh, json={"status": "bloqueada"})).json()["status"] \
        == "bloqueada"
    done = (await client.put(f"{T}/{prep.json()['id']}", headers=sh, json={"status": "hecha"})).json()
    assert done["status"] == "hecha" and done["completed_at"]

    # finishing the transplant logs it on the lot and plants it out
    moved = (await client.put(f"{T}/{transplant['id']}", headers=h, json={"status": "hecha"})).json()
    assert moved["status"] == "hecha"
    lot = (await client.get(f"{FARM}/lots/{seedbed['id']}", headers=h)).json()
    assert lot["status"] == "planted" and lot["transplant_date"]

    log = (await client.get(f"{FARM}/log?lot_id={seedbed['id']}", headers=h)).json()
    items = [i for d in log["days"] for i in d["items"]]
    assert {(i["kind"], i["type"]) for i in items} >= {("task", "transplant"), ("event", "transplant"),
                                                      ("event", "soil_prep")}
    assert next(i for i in items if i["kind"] == "task")["title"] == "Trasplantar tomates"

    open_ones = (await client.get(f"{T}?open_only=true", headers=h)).json()
    assert [t["id"] for t in open_ones] == [general["id"]]

    # only managers delete; a zone of another account is refused
    assert (await client.delete(f"{T}/{general['id']}", headers=sh)).status_code == 403
    assert (await client.delete(f"{T}/{general['id']}", headers=h)).status_code == 204
    stranger = await signup("tasks-stranger")
    bad = await client.post(T, headers=stranger["headers"], json={"title": "x", "zone_id": zone["id"]})
    assert bad.status_code == 404
