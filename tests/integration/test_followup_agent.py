"""
The chat agent can do with follow-ups everything the app does: list and read them, open, edit, add entries, link
treatments (application records included) and close them.
"""
import json

from .test_agent_chat import scripted_model, with_key  # noqa: F401 - fixtures
from .test_applications import APPS, FARM, _setup


def _tool_result(llm, name: str) -> dict:
    """The last result the model got back from a tool, as the next request carried it."""
    for request in reversed(llm.requests):
        for content in reversed(request.contents):
            for part in content.parts or []:
                if part.function_response and part.function_response.name == name:
                    return part.function_response.response
    raise AssertionError(f"no result for {name}")


async def _turn(client, h, llm, script, message="ok", conversation_id=None):
    llm.script = script
    r = await client.post("/api/v1/chat", headers=h, json={
        "message": message, **({"conversation_id": conversation_id} if conversation_id else {}),
    })
    assert r.status_code == 200, r.text
    calls = r.json()["metadata"]["tool_calls"]
    assert all(c["ok"] for c in calls), json.dumps(calls)
    return r.json()["metadata"]["conversation_id"]


async def test_the_agent_follows_a_problem_from_the_chat(client, signup, with_key, scripted_model):  # noqa: F811
    user = await signup("followup-agent")
    await with_key(user)
    h = user["headers"]
    field, zone, lot = await _setup(client, h)

    # "tengo pulgón en los tomates del cantero 1"
    conv = await _turn(client, h, scripted_model, [
        ("call", "list_followups", {"field": "Quinta", "zone": "cantero 1"}),
        ("call", "open_followup", {
            "title": "Pulgón en tomate", "field": "Quinta", "zone": "cantero 1", "lots": [lot["id"]],
            "severity": "high", "photo_hint": "envés de las hojas", "notes": "colonias en los brotes",
        }),
        ("text", "Abrí el seguimiento del pulgón."),
    ], "tengo pulgón en los tomates del cantero 1")
    assert _tool_result(scripted_model, "list_followups")["followups"] == []
    followup_id = _tool_result(scripted_model, "open_followup")["opened"]["followup_id"]
    followup = (await client.get(f"{FARM}/followups/{followup_id}", headers=h)).json()
    assert followup["zone_id"] == zone["id"] and followup["severity"] == "high" and followup["source"] == "agent"

    # An application recorded without saying what for: the agent is shown the open follow-ups there, links it,
    # and on the yes the confirmed record's bitácora entry joins the follow-up.
    await _turn(client, h, scripted_model, [
        ("call", "record_application", {
            "field": "Quinta", "zone": "cantero 1", "target": "pulgón", "kind": "biological", "operator": "yo",
            "products": [{"name": "Jabón potásico", "kind": "biological", "dose": 10, "dose_unit": "ml/L"}],
        }),
        ("text", "¿Es para el pulgón en tomate?"),
    ], "apliqué jabón potásico en el cantero 1", conv)
    result = _tool_result(scripted_model, "record_application")
    assert [f["followup_id"] for f in result["open_followups_here"]] == [followup_id]
    draft_id = result["draft"]["id"]
    await _turn(client, h, scripted_model, [
        ("call", "update_application_draft", {"application_id": draft_id, "followup_id": followup_id}),
        ("call", "confirm_application", {"application_id": draft_id}),
        ("text", "Confirmado y sumado al seguimiento."),
    ], "sí, es para eso, confirmalo", conv)
    app = (await client.get(f"{APPS}/{draft_id}", headers=h)).json()
    assert app["followup_id"] == followup_id and app["status"] == "confirmed"
    history = (await client.get(f"{FARM}/followups/{followup_id}", headers=h)).json()["events"]
    assert history[0]["id"] == app["field_event_id"] and history[0]["type"] == "pest_control"

    # A watering logged on the side, then linked; a check-up with how it's going; its story; an edit; closing it.
    await _turn(client, h, scripted_model, [
        ("call", "log_events", {"field": "Quinta", "entries": [
            {"type": "observation", "zone": "cantero 1", "notes": "saqué hojas con pulgón", "followup_id": followup_id},
            {"type": "irrigation", "zone": "cantero 1", "notes": "purín de ortiga"},
        ]}),
        ("text", "Anotado."),
    ], "saqué hojas con pulgón y regué con purín de ortiga", conv)
    logged = _tool_result(scripted_model, "log_events")["logged"]
    await _turn(client, h, scripted_model, [
        ("call", "link_to_followup", {"followup_id": followup_id, "event_ids": [logged[1]["id"]]}),
        ("call", "add_followup_entry", {"followup_id": followup_id, "notes": "casi no hay colonias",
                                        "evolution": "mejor"}),
        ("call", "get_followup", {"followup_id": followup_id}),
        ("call", "update_followup", {"followup_id": followup_id, "severity": "low"}),
        ("text", "Viene mejor."),
    ], "el purín era por el pulgón; hoy casi no hay colonias", conv)
    story = _tool_result(scripted_model, "get_followup")
    assert [e["type"] for e in story["history"]] == [
        "inspection", "pest_control", "observation", "irrigation", "inspection",
    ]
    assert story["history"][-1]["evolution"] == "mejor" and story["last_evolution"] == "mejor"
    assert _tool_result(scripted_model, "update_followup")["followup"]["severity"] == "low"

    await _turn(client, h, scripted_model, [
        ("call", "close_followup", {"followup_id": followup_id, "notes": "no se ve más"}),
        ("text", "Cerrado."),
    ], "ya está, se fue el pulgón", conv)
    closed = (await client.get(f"{FARM}/followups/{followup_id}", headers=h)).json()
    assert closed["status"] == "resuelto" and closed["events"][0]["notes"] == "Resuelto: Pulgón en tomate. no se ve más"


async def test_an_application_can_be_linked_after_it_was_confirmed(client, signup):
    user = await signup("followup-app-link")
    h = user["headers"]
    field, zone, lot = await _setup(client, h)
    followup = (await client.post(f"{FARM}/followups", headers=h, json={
        "field_id": field["id"], "zone_id": zone["id"], "title": "Oídio"})).json()
    draft = (await client.post(APPS, headers=h, json={
        "field_id": field["id"], "zone_id": zone["id"], "applied_at": "2026-10-20T10:00:00Z", "kind": "biological",
        "operator_name": "Juan",
        "products": [{"name": "Azufre", "kind": "biological", "dose": 2, "dose_unit": "g/L"}],
    })).json()
    confirmed = (await client.post(f"{APPS}/{draft['id']}/confirm", headers=h)).json()
    linked = await client.put(f"{APPS}/{draft['id']}/followup", headers=h, json={"followup_id": followup["id"]})
    assert linked.status_code == 200, linked.text
    assert linked.json()["version"] == confirmed["version"]  # context, not a correction
    event = (await client.get(f"{FARM}/events/{confirmed['field_event_id']}", headers=h)).json()
    assert event["followup_id"] == followup["id"]

    # A correction keeps the link.
    corrected = (await client.post(f"{APPS}/{draft['id']}/corrections", headers=h, json={
        "reason": "la dosis era otra",
        "products": [{"name": "Azufre", "kind": "biological", "dose": 3, "dose_unit": "g/L"}],
    })).json()
    assert corrected["followup_id"] == followup["id"]

    other_field = (await client.post(f"{FARM}/fields", headers=h, json={"name": "Otra"})).json()
    stray = (await client.post(
        f"{FARM}/followups", headers=h, json={"field_id": other_field["id"], "title": "x"})).json()
    bad = await client.put(f"{APPS}/{draft['id']}/followup", headers=h, json={"followup_id": stray["id"]})
    assert bad.status_code == 400
