"""
Zones (cajón / cantero / invernadero / hidroponía): numbered per field, crops/events belong to them, and the
daily tracking report is taken per zone from 1-4 photos and assesses every active crop of the zone.
"""
import base64
from unittest.mock import AsyncMock, patch

from src.agent.reasoning.periodic_report import ZoneCropAssessment, ZonePeriodicReportResult

from .test_agent_chat import scripted_model, with_key  # noqa: F401 - fixtures

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
FARM = "/api/v1/farm-management"


async def _field(client, h, name="Huerta"):
    r = await client.post(f"{FARM}/fields", headers=h, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


async def _crop_id(client, h, name):
    return (await client.get(f"{FARM}/crop-masters?q={name}", headers=h)).json()[0]["id"]


async def _cycle(client, h, field_id, crop, zone_id=None, status="growing"):
    r = await client.post(
        f"{FARM}/crop-cycles",
        headers=h,
        json={
            "field_id": field_id,
            "crop_master_id": await _crop_id(client, h, crop),
            "zone_id": zone_id,
            "status": status,
            "planting_date": "2026-09-01",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_zones_are_numbered_per_field_and_type(client, signup, add_member):
    owner = await signup("zones")
    h = owner["headers"]
    field = await _field(client, h)

    first = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    second = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    green = await client.post(
        f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "invernadero", "name": "el grande"}
    )
    assert (first["number"], first["label"]) == (1, "Cantero 1")
    assert second["number"] == 2
    assert green.json()["label"] == "Invernadero 1 (el grande)"

    duplicate = await client.post(
        f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero", "number": 2}
    )
    assert duplicate.status_code == 400

    staff = await add_member(owner, "staff")
    denied = await client.post(f"{FARM}/fields/{field['id']}/zones", headers=staff["headers"], json={"type": "cajon"})
    assert denied.status_code == 403
    listed = (await client.get(f"{FARM}/fields/{field['id']}/zones", headers=staff["headers"])).json()
    assert [z["label"] for z in listed] == ["Cantero 1", "Cantero 2", "Invernadero 1 (el grande)"]

    # Renumbering onto a taken number is refused; deleting frees the number again.
    clash = await client.put(f"{FARM}/zones/{second['id']}", headers=h, json={"number": 1})
    assert clash.status_code == 400
    assert (await client.delete(f"{FARM}/zones/{first['id']}", headers=h)).status_code == 204
    again = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero", "number": 1}))
    assert again.status_code == 201


async def test_crops_and_events_belong_to_a_zone_of_their_own_field(client, signup):
    user = await signup("zone-cycles")
    h = user["headers"]
    field = await _field(client, h)
    other_field = await _field(client, h, "Otro")
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()

    cycle = await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])
    assert cycle["zone_id"] == zone["id"]
    wrong = await client.post(
        f"{FARM}/crop-cycles",
        headers=h,
        json={"field_id": other_field["id"], "crop_master_id": cycle["crop_master_id"], "zone_id": zone["id"]},
    )
    assert wrong.status_code == 400

    in_zone = (await client.get(f"{FARM}/crop-cycles?zone_id={zone['id']}", headers=h)).json()
    assert [c["id"] for c in in_zone] == [cycle["id"]]

    event = await client.post(
        f"{FARM}/events", headers=h, json={"field_id": field["id"], "crop_cycle_id": cycle["id"], "type": "irrigation"}
    )
    assert event.json()["zone_id"] == zone["id"]  # taken from the cycle

    overview = (await client.get(f"{FARM}/overview", headers=h)).json()
    mine = next(o for o in overview if o["field"]["id"] == field["id"])
    assert mine["zones"][0]["label"] == "Cantero 1"
    assert mine["active_cycles"][0]["zone_label"] == "Cantero 1"

    # Deleting the zone keeps the crop in the field, without a zone.
    assert (await client.delete(f"{FARM}/zones/{zone['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{FARM}/crop-cycles/{cycle['id']}", headers=h)).json()["zone_id"] is None


def _zone_result(cycles: list[dict]) -> ZonePeriodicReportResult:
    return ZonePeriodicReportResult(
        zone_summary="El cantero viene parejo; el tomate algo atrasado.",
        overall_health="good",
        crops=[
            ZoneCropAssessment(
                crop_cycle_id=c["id"],
                crop_name=name,
                visible_in_photos=True,
                growth_stage="vegetativo",
                health_status="good",
                health_summary=f"{name} con hojas verdes y turgentes",
                expected_vs_actual="Acorde",
                harvest_ready=name == "Lechuga",
                harvest_verdict="Hojas de tamaño comercial" if name == "Lechuga" else "Sin frutos",
            )
            for c, name in cycles
        ],
        past_actions_assessment="Riego adecuado",
        objectives_assessment="Sin objetivos explícitos",
        risk_severity="low",
        recommendations=["Atar los tomates"],
        confidence=0.8,
        needs_human_expert=False,
    )


async def test_zone_tracking_analyzes_every_active_crop_of_the_zone(client, signup, container):
    user = await signup("zone-tracking")
    h = user["headers"]
    field = await _field(client, h)
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    tomato = await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])
    lettuce = await _cycle(client, h, field["id"], "lechuga", zone_id=zone["id"])
    await _cycle(client, h, field["id"], "acelga", zone_id=zone["id"], status="harvested")  # not active
    await _cycle(client, h, field["id"], "acelga")  # same field, no zone

    gateway = container.agent.gemini()
    fake = AsyncMock(return_value=_zone_result([(tomato, "Tomate"), (lettuce, "Lechuga")]))
    with patch.object(gateway, "generate_structured", fake):
        up = await client.post(
            "/api/v1/upload/zone-tracking",
            headers=h,
            data={"zone_id": zone["id"]},
            files=[
                ("image_files", ("a.png", _TINY_PNG, "image/png")),
                ("image_files", ("b.png", _TINY_PNG, "image/png")),
            ],
        )
    assert up.status_code == 200, up.text
    report = (await client.get(f"/api/v1/reports/{up.json()['report_id']}", headers=h)).json()
    assert report["status"] == "ANALYSIS_COMPLETED"
    assert report["zone_id"] == zone["id"] and report["field_id"] == field["id"]
    assert len(report["image_identifiers"]) == 2
    assert set(report["crop_cycle_ids"]) == {tomato["id"], lettuce["id"]}
    assert report["title"] == "Cantero 1 · seguimiento"
    crops = report["raw_analysis_data"]["llm_structured_zone"]["crops"]
    assert [c["crop_name"] for c in crops] == ["Tomate", "Lechuga"]

    # Both photos went to the model, with every active cycle of the zone (and only those) in the prompt.
    contents = fake.call_args.kwargs["contents"]
    assert len(contents) == 3
    prompt = contents[-1]
    assert tomato["id"] in prompt and lettuce["id"] in prompt and "Cantero 1" in prompt
    assert prompt.count("crop_cycle_id=") == 2

    # The report shows up in each covered cycle's history, and feeds its harvest verdict.
    by_cycle = (await client.get(f"/api/v1/reports?crop_cycle_id={lettuce['id']}", headers=h)).json()
    assert [r["id"] for r in by_cycle] == [report["id"]]
    from uuid import UUID

    from src.shared.domain.actor import Actor

    actor = Actor(UUID(user["user"]["id"]), UUID(user["account"]["id"]), "owner")
    verdict = await container.agent.diagnosis_service().harvest_verdict(actor, UUID(field["id"]), UUID(lettuce["id"]))
    assert verdict["ready"] is True and "comercial" in verdict["verdict"]


async def test_zone_tracking_needs_active_crops_and_1_to_4_photos(client, signup):
    user = await signup("zone-tracking-bad")
    h = user["headers"]
    field = await _field(client, h)
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cajon"})).json()
    photo = ("image_files", ("a.png", _TINY_PNG, "image/png"))

    empty = await client.post("/api/v1/upload/zone-tracking", headers=h, data={"zone_id": zone["id"]}, files=[photo])
    assert empty.status_code == 400 and "Cajón 1" in empty.json()["detail"]

    await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])
    too_many = await client.post(
        "/api/v1/upload/zone-tracking", headers=h, data={"zone_id": zone["id"]}, files=[photo] * 5
    )
    assert too_many.status_code == 400


async def test_agent_creates_zone_and_plants_in_it(client, signup, with_key, scripted_model):  # noqa: F811
    user = await signup("zone-agent")
    await with_key(user)
    h = user["headers"]
    field = await _field(client, h, "Huerta del fondo")

    scripted_model.script = [
        ("call", "create_zone", {"zone": "cantero 3", "field": "huerta"}),
        ("call", "create_crop_cycle", {"crop_name": "Lechuga", "field": "huerta", "zone": "Cantero 3"}),
        ("call", "log_event", {"event_type": "irrigation", "field": "huerta", "zone": "cantero 3"}),
        ("text", "Listo: creé el Cantero 3, planté lechuga y registré el riego."),
    ]
    r = await client.post("/api/v1/chat", headers=h, json={"message": "armé el cantero 3 con lechuga y lo regué"})
    assert r.status_code == 200, r.text
    assert all(t["ok"] for t in r.json()["metadata"]["tool_calls"]), r.json()["metadata"]["tool_calls"]

    zones = (await client.get(f"{FARM}/fields/{field['id']}/zones", headers=h)).json()
    assert [z["label"] for z in zones] == ["Cantero 3"]
    cycles = (await client.get(f"{FARM}/crop-cycles?zone_id={zones[0]['id']}", headers=h)).json()
    assert len(cycles) == 1
    events = (await client.get(f"{FARM}/events", headers=h)).json()
    assert events[0]["zone_id"] == zones[0]["id"]

    # Next turn: the per-turn account snapshot lists the zone and which crop grows there.
    scripted_model.script = [("text", "ok")]
    scripted_model.requests.clear()
    conversation_id = r.json()["metadata"]["conversation_id"]
    await client.post("/api/v1/chat", headers=h, json={"message": "¿qué hay?", "conversation_id": conversation_id})
    snapshot = str(scripted_model.requests[0].contents[-1].parts)
    assert "Zonas: Cantero 3" in snapshot and "Cantero 3)" in snapshot
