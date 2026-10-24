"""
Follow-ups (seguimientos): a problem being watched, whose history is the bitácora entries about it — opened
("Se detectó"), treated, evaluated, closed — each with its evidence.
"""
from .test_zones import FARM, _cycle, _field


async def _zone(client, h, field_id, type_="cantero"):
    return (await client.post(f"{FARM}/fields/{field_id}/zones", headers=h, json={"type": type_})).json()


async def test_a_followup_lives_in_the_bitacora_from_detection_to_resolution(client, signup):
    user = await signup("followups")
    h = user["headers"]
    field = await _field(client, h)
    zone = await _zone(client, h, field["id"])
    tomato = await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])
    other_tomato = await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])

    opened = await client.post(f"{FARM}/followups", headers=h, json={
        "field_id": field["id"], "lot_ids": [tomato["id"], other_tomato["id"]], "title": "Pulgón en tomate",
        "kind": "pest", "severity": "medium", "photo_hint": "envés de las hojas de arriba",
        "notes": "colonias en el envés", "evidence": [{"kind": "photo", "identifier": "a1.jpg"}],
    })
    assert opened.status_code == 201, opened.text
    followup = opened.json()
    assert followup["zone_id"] == zone["id"]  # taken from its lots
    assert followup["status"] == "abierto" and followup["source"] == "user"
    assert followup["last_photo"] == "a1.jpg" and followup["entries"] == 1
    detected = followup["events"][0]
    assert detected["type"] == "inspection"
    assert detected["notes"] == "Se detectó: Pulgón en tomate. colonias en el envés"
    assert set(detected["lot_ids"]) == {tomato["id"], other_tomato["id"]}
    assert detected["data"]["followup_action"] == "opened"

    # A treatment logged as usual, linked to it; then an evaluation with a before/after.
    treatment = await client.post(f"{FARM}/events", headers=h, json={
        "field_id": field["id"], "zone_id": zone["id"], "type": "pest_control", "notes": "Jabón potásico 1%",
        "followup_id": followup["id"],
    })
    assert treatment.status_code == 201, treatment.text
    better = await client.post(f"{FARM}/events", headers=h, json={
        "field_id": field["id"], "zone_id": zone["id"], "type": "inspection", "notes": "Se observa mejoría",
        "followup_id": followup["id"], "data": {"evolution": "mejor"},
        "evidence": [
            {"kind": "photo", "identifier": "b3.jpg"}, {"kind": "photo", "identifier": "a1.jpg", "note": "antes"},
        ],
    })
    assert better.status_code == 201, better.text

    # It shows in the zone's bitácora like any other entry, and the follow-up's timeline gathers them.
    in_zone = (await client.get(f"{FARM}/events?zone_id={zone['id']}", headers=h)).json()
    assert {e["id"] for e in in_zone} >= {detected["id"], treatment.json()["id"], better.json()["id"]}
    timeline = (await client.get(f"{FARM}/events?followup_id={followup['id']}", headers=h)).json()
    assert [e["notes"] for e in timeline][-1].startswith("Se detectó")
    detail = (await client.get(f"{FARM}/followups/{followup['id']}", headers=h)).json()
    assert detail["entries"] == 3 and detail["last_evolution"] == "mejor" and detail["last_photo"] == "b3.jpg"

    open_now = (await client.get(f"{FARM}/followups?field_id={field['id']}&status=abierto", headers=h)).json()
    assert [f["id"] for f in open_now] == [followup["id"]]

    closed = await client.post(f"{FARM}/followups/{followup['id']}/close", headers=h, json={"notes": "sin colonias"})
    assert closed.status_code == 200, closed.text
    closed = closed.json()
    assert closed["status"] == "resuelto" and closed["closed_at"] and closed["entries"] == 4
    assert closed["events"][0]["notes"] == "Resuelto: Pulgón en tomate. sin colonias"
    assert (await client.post(f"{FARM}/followups/{followup['id']}/close", headers=h, json={})).status_code == 400
    assert (await client.get(f"{FARM}/followups?field_id={field['id']}&status=abierto", headers=h)).json() == []


async def test_followups_stay_in_their_field_and_account(client, signup, add_member):
    owner = await signup("followups-scope")
    h = owner["headers"]
    field = await _field(client, h)
    other_field = await _field(client, h, "Otro")
    other_zone = await _zone(client, h, other_field["id"])
    zone = await _zone(client, h, field["id"])

    wrong_zone = await client.post(f"{FARM}/followups", headers=h, json={
        "field_id": field["id"], "zone_id": other_zone["id"], "title": "Oídio"})
    assert wrong_zone.status_code == 400
    followup = (await client.post(f"{FARM}/followups", headers=h, json={
        "field_id": field["id"], "zone_id": zone["id"], "title": "Oídio", "kind": "disease"})).json()

    # An entry of another field can't point at it.
    stray = await client.post(f"{FARM}/events", headers=h, json={
        "field_id": other_field["id"], "type": "observation", "followup_id": followup["id"]})
    assert stray.status_code == 400

    # Another account doesn't see it.
    stranger = await signup("followups-stranger")
    assert (await client.get(f"{FARM}/followups/{followup['id']}", headers=stranger["headers"])).status_code == 404

    # Staff can close it (a check-up) but not edit someone else's.
    staff = await add_member(owner, "staff")
    edit = await client.patch(f"{FARM}/followups/{followup['id']}", headers=staff["headers"], json={"title": "x"})
    assert edit.status_code == 403
    edited = await client.patch(f"{FARM}/followups/{followup['id']}", headers=h, json={"severity": "high"})
    assert edited.json()["severity"] == "high"
    dismissed = await client.post(
        f"{FARM}/followups/{followup['id']}/close", headers=staff["headers"], json={"status": "descartado"})
    assert dismissed.json()["status"] == "descartado"
    assert dismissed.json()["events"][0]["notes"] == "Descartado: Oídio"
