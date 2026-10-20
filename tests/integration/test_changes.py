"""
Change sets and proposals: several writes previewed, then applied in order through the usual services; "$N" links
an operation to what an earlier one created; a failure removes what the set created. A proposal is a change set the
agent prepared, applied or rejected by the user from the chat.
"""
from .test_agent_chat import scripted_model, with_key  # noqa: F401 - fixtures

FARM = "/api/v1/farm-management"


async def _setup(client, h):
    field = (await client.post(f"{FARM}/fields", headers=h, json={"name": "Huerta"})).json()
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    crop = (await client.get(f"{FARM}/crop-masters?q=lechuga", headers=h)).json()[0]["id"]
    return field, zone, crop


async def test_preview_then_apply_with_references_and_undo_on_failure(client, signup):
    h = (await signup("changes"))["headers"]
    field, zone, crop = await _setup(client, h)
    ops = [
        {"op": "create", "entity": "lot", "data": {"field_id": field["id"], "crop_master_id": crop,
                                                   "zone_ids": [zone["id"]], "season": "26/27", "number": 1}},
        {"op": "create", "entity": "task", "data": {"title": "Trasplantar lechuga", "lot_id": "$0",
                                                    "result_event_type": "transplant"}},
        {"op": "update", "entity": "zone", "id": zone["id"], "data": {"name": "aromáticas"}},
    ]
    preview = (await client.post("/api/v1/changes/preview", headers=h, json={"operations": ops})).json()
    assert preview["ok"] is True
    assert preview["items"][2]["before"]["label"] == "Cantero 1"
    assert preview["items"][1]["title"] == "Crear tarea: Trasplantar lechuga"
    assert (await client.get(f"{FARM}/lots", headers=h)).json() == []  # a preview writes nothing

    bad = (await client.post("/api/v1/changes/preview", headers=h, json={"operations": [
        {"op": "create", "entity": "lot", "data": {"field_id": field["id"]}},
        {"op": "delete", "entity": "zone"},
    ]})).json()
    assert bad["ok"] is False and all(i["error"] for i in bad["items"])

    result = (await client.post("/api/v1/changes", headers=h, json={"operations": ops})).json()
    assert (result["applied"], result["failed"], result["undone"]) == (3, 0, False)
    lot_id = result["items"][0]["id"]
    task = (await client.get(f"/api/v1/tasks?lot_id={lot_id}", headers=h)).json()
    assert [t["title"] for t in task] == ["Trasplantar lechuga"]
    assert (await client.get(f"{FARM}/zones/{zone['id']}", headers=h)).json()["name"] == "aromáticas"

    # the third operation fails: the lot the set created is removed again, the rest skipped
    failing = [
        ops[0],
        {"op": "update", "entity": "lot", "id": "00000000-0000-0000-0000-000000000001", "data": {"number": 2}},
        {"op": "create", "entity": "task", "data": {"title": "Nunca"}},
    ]
    result = (await client.post("/api/v1/changes", headers=h, json={"operations": failing})).json()
    assert result["undone"] is True and result["failed"] == 1 and result["items"][2]["skipped"] is True
    assert len((await client.get(f"{FARM}/lots", headers=h)).json()) == 1  # only the first set's lot


async def test_agent_proposes_and_the_user_applies_without_the_unticked(client, signup, with_key, scripted_model):  # noqa: F811
    user = await signup("proposals")
    await with_key(user)
    h = user["headers"]
    field, zone, crop = await _setup(client, h)
    lot = lambda n: {"op": "create", "entity": "lot", "data": {  # noqa: E731
        "field_id": field["id"], "crop_master_id": crop, "zone_ids": [zone["id"]], "season": "26/27", "number": n,
    }}
    scripted_model.script = [
        ("call", "propose_changes", {"title": "Tres lotes de lechuga", "operations": [lot(1), lot(2), lot(3)]}),
        ("text", "Te dejé la propuesta en el panel: tres lotes de lechuga en el Cantero 1."),
    ]
    r = await client.post("/api/v1/chat", headers=h, json={"message": "cargá tres lotes de lechuga"})
    assert r.status_code == 200, r.text
    body = r.json()
    proposal_ref = next(a for a in body["attachments"] if a["type"] == "proposal")
    assert (await client.get(f"{FARM}/lots", headers=h)).json() == []  # nothing until the user confirms

    proposal = (await client.get(f"/api/v1/chat/proposals/{proposal_ref['proposal_id']}", headers=h)).json()
    assert proposal["status"] == "pending" and len(proposal["preview"]) == 3

    applied = await client.post(
        f"/api/v1/chat/proposals/{proposal['id']}/apply", headers=h, json={"excluded": [1]}
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    numbers = sorted(lot["number"] for lot in (await client.get(f"{FARM}/lots", headers=h)).json())
    assert numbers == [1, 3]
    again = await client.post(f"/api/v1/chat/proposals/{proposal['id']}/apply", headers=h, json={})
    assert again.status_code == 400

    # the conversation keeps a line about it, for the next turn
    conversation_id = body["metadata"]["conversation_id"]
    messages = (await client.get(f"/api/v1/chat/conversations/{conversation_id}/messages", headers=h)).json()
    assert messages[-1]["content"].startswith("✅ Propuesta «Tres lotes de lechuga» aplicada: 2 cambios")

    stranger = await signup("proposals-stranger")
    assert (await client.get(f"/api/v1/chat/proposals/{proposal['id']}", headers=stranger["headers"])).status_code \
        == 404
