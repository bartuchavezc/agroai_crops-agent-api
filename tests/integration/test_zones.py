"""
Zones (cajón / cantero / invernadero / hidroponía): numbered per field, crops/events belong to them, and the
daily tracking report is taken per zone from 1-3 photos and assesses every active crop of the zone.
"""
import base64
from unittest.mock import AsyncMock, patch

from src.agent.reasoning.periodic_report import (
    ZoneCropAssessment,
    ZoneGroupAssessment,
    ZoneOverviewResult,
    ZoneSynthesisResult,
)

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
        f"{FARM}/lots",
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
        f"{FARM}/lots",
        headers=h,
        json={"field_id": other_field["id"], "crop_master_id": cycle["crop_master_id"], "zone_id": zone["id"]},
    )
    assert wrong.status_code == 400

    in_zone = (await client.get(f"{FARM}/lots?zone_id={zone['id']}", headers=h)).json()
    assert [c["id"] for c in in_zone] == [cycle["id"]]

    event = await client.post(
        f"{FARM}/events", headers=h, json={"field_id": field["id"], "lot_id": cycle["id"], "type": "irrigation"}
    )
    assert event.json()["zone_id"] == zone["id"]  # taken from the cycle

    overview = (await client.get(f"{FARM}/overview", headers=h)).json()
    mine = next(o for o in overview if o["field"]["id"] == field["id"])
    assert mine["zones"][0]["label"] == "Cantero 1"
    assert mine["active_lots"][0]["zone_label"] == "Cantero 1"

    # Deleting the zone keeps the crop in the field, without a zone.
    assert (await client.delete(f"{FARM}/zones/{zone['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{FARM}/lots/{cycle['id']}", headers=h)).json()["zone_id"] is None


def _overview_result(unlisted_plants: list[str] | None = None) -> ZoneOverviewResult:
    return ZoneOverviewResult(zone_observations="Zona prolija, buena cobertura.", unlisted_plants=unlisted_plants or [])


def _group_result(cycles: list[tuple[dict, str]], risk="low", confidence=0.8) -> ZoneGroupAssessment:
    return ZoneGroupAssessment(
        crops=[
            ZoneCropAssessment(
                lot_id=c["id"],
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
        group_risk_severity=risk,
        group_recommendations=["Atar los tomates"] if any(n == "Tomate" for _, n in cycles) else [],
        group_notes="Sin novedades" if risk == "low" else "Revisar de cerca",
        confidence=confidence,
        needs_human_expert=False,
    )


def _synthesis_result() -> ZoneSynthesisResult:
    return ZoneSynthesisResult(
        zone_summary="El cantero viene parejo; el tomate algo atrasado.",
        past_actions_assessment="Riego adecuado",
        objectives_assessment="Sin objetivos explícitos",
        recommendations=["Atar los tomates"],
    )


def _zone_analysis(group: ZoneGroupAssessment) -> AsyncMock:
    """A fanned-out zone analysis with a single crop group: overview, that group, synthesis."""
    def _respond(_user_id, *, schema, **_kwargs):
        if schema is ZoneOverviewResult:
            return _overview_result()
        if schema is ZoneSynthesisResult:
            return _synthesis_result()
        return group

    return AsyncMock(side_effect=_respond)


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

    # Fanned out: one whole-photo overview, one call per crop group (tomate and lechuga are different
    # fichas -> different groups), one text-only synthesis. No notes, no recheck (both groups are low-risk).
    # The scheduler doesn't guarantee which group runs first, so the mock answers by looking at which
    # cycle's id is actually in the prompt, rather than assuming a call order.
    def _respond(_user_id, *, contents, schema, **_kwargs):
        if schema is ZoneOverviewResult:
            return _overview_result()
        if schema is ZoneSynthesisResult:
            return _synthesis_result()
        prompt = contents[-1]
        return _group_result([(tomato, "Tomate")] if tomato["id"] in prompt else [(lettuce, "Lechuga")])

    fake = AsyncMock(side_effect=_respond)
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
    assert set(report["lot_ids"]) == {tomato["id"], lettuce["id"]}
    assert report["title"] == "Cantero 1 · seguimiento"
    crops = report["raw_analysis_data"]["llm_structured_zone"]["crops"]
    assert {c["crop_name"] for c in crops} == {"Tomate", "Lechuga"}

    assert fake.await_count == 4  # overview + 2 groups + synthesis; no deep pass in a fanned-out zone analysis
    calls = fake.call_args_list
    def _group_call(cycle):
        return next(
            c for c in calls if c.kwargs["schema"] is ZoneGroupAssessment and cycle["id"] in c.kwargs["contents"][-1]
        )

    overview_call = next(c for c in calls if c.kwargs["schema"] is ZoneOverviewResult)
    synthesis_call = next(c for c in calls if c.kwargs["schema"] is ZoneSynthesisResult)
    tomato_call, lettuce_call = _group_call(tomato), _group_call(lettuce)

    # Both photos went to the overview and to each group's call; synthesis is text-only (no photos).
    assert len(overview_call.kwargs["contents"]) == 3
    assert len(tomato_call.kwargs["contents"]) == 3 and len(lettuce_call.kwargs["contents"]) == 3
    assert len(synthesis_call.kwargs["contents"]) == 1

    # Each group only sees its own cycle in the prompt and its own ficha in the system — not the other's.
    tomato_prompt, lettuce_prompt = tomato_call.kwargs["contents"][-1], lettuce_call.kwargs["contents"][-1]
    assert tomato["id"] in tomato_prompt and lettuce["id"] not in tomato_prompt and "Cantero 1" in tomato_prompt
    assert lettuce["id"] in lettuce_prompt and tomato["id"] not in lettuce_prompt
    tomato_system, lettuce_system = tomato_call.kwargs["system_instruction"], lettuce_call.kwargs["system_instruction"]
    assert "ficha-tomate" in tomato_system and "ficha-lechuga" not in tomato_system
    assert "ficha-lechuga" in lettuce_system and "ficha-tomate" not in lettuce_system

    # The report shows up in each covered cycle's history, and feeds its harvest verdict.
    by_cycle = (await client.get(f"/api/v1/reports?lot_id={lettuce['id']}", headers=h)).json()
    assert [r["id"] for r in by_cycle] == [report["id"]]
    from uuid import UUID

    from src.shared.domain.actor import Actor

    actor = Actor(UUID(user["user"]["id"]), UUID(user["account"]["id"]), "owner")
    verdict = await container.agent.diagnosis_service().harvest_verdict(actor, UUID(field["id"]), UUID(lettuce["id"]))
    assert verdict["ready"] is True and "comercial" in verdict["verdict"]


async def test_zone_retry_via_analyze_endpoint_is_backgrounded(client, signup, container):
    """Unlike a single-crop diagnosis/periodic retry (still synchronous — see test_accounts_and_farm.py), a
    zone's retry can be several sequential calls now, so POST /analyze backgrounds it instead of awaiting
    inline: the endpoint responds "queued" immediately, and the report's own status carries the outcome."""
    user = await signup("zone-retry")
    h = user["headers"]
    field = await _field(client, h)
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    tomato = await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])

    gateway = container.agent.gemini()
    with patch.object(gateway, "generate_structured", AsyncMock(side_effect=RuntimeError("boom"))):
        up = await client.post(
            "/api/v1/upload/zone-tracking", headers=h, data={"zone_id": zone["id"]},
            files=[("image_files", ("a.png", _TINY_PNG, "image/png"))],
        )
    assert up.status_code == 200, up.text
    report_id = up.json()["report_id"]
    assert (await client.get(f"/api/v1/reports/{report_id}", headers=h)).json()["status"] == "ANALYSIS_FAILED"

    def _respond(_user_id, *, schema, **_kwargs):
        if schema is ZoneOverviewResult:
            return _overview_result()
        if schema is ZoneSynthesisResult:
            return _synthesis_result()
        return _group_result([(tomato, "Tomate")])

    with patch.object(gateway, "generate_structured", AsyncMock(side_effect=_respond)):
        retry = await client.post("/api/v1/analyze", headers=h, json={"report_id": report_id})
    assert retry.status_code == 200, retry.text
    assert retry.json() == {"status": "queued", "report_id": report_id}
    report = (await client.get(f"/api/v1/reports/{report_id}", headers=h)).json()
    assert report["status"] == "ANALYSIS_COMPLETED"


async def test_zone_tracking_needs_active_crops_and_1_to_3_photos(client, signup):
    user = await signup("zone-tracking-bad")
    h = user["headers"]
    field = await _field(client, h)
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cajon"})).json()
    photo = ("image_files", ("a.png", _TINY_PNG, "image/png"))

    empty = await client.post("/api/v1/upload/zone-tracking", headers=h, data={"zone_id": zone["id"]}, files=[photo])
    assert empty.status_code == 400 and "Cajón 1" in empty.json()["detail"]

    await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])
    too_many = await client.post(
        "/api/v1/upload/zone-tracking", headers=h, data={"zone_id": zone["id"]}, files=[photo] * 4
    )
    assert too_many.status_code == 400


async def test_zone_tracking_photo_roles_route_each_photo_to_the_passes_that_need_it(client, signup, container):
    import json

    user = await signup("zone-photo-roles")
    h = user["headers"]
    field = await _field(client, h)
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cajon"})).json()
    tomato = await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])
    lettuce = await _cycle(client, h, field["id"], "lechuga", zone_id=zone["id"])
    other = await _cycle(client, h, field["id"], "acelga")  # same field, not in the zone
    photos = [("image_files", (f"{n}.png", _TINY_PNG, "image/png")) for n in "abc"]
    roles = [
        {"role": "general"},
        {"role": "detalle", "lot_id": tomato["id"], "hint": "brotes nuevos"},
        {"role": "seguimiento", "lot_id": lettuce["id"]},
    ]

    async def _upload(photo_roles, files=photos):
        return await client.post(
            "/api/v1/upload/zone-tracking", headers=h, data={"zone_id": zone["id"], "photo_roles": photo_roles},
            files=files,
        )

    assert (await _upload(json.dumps(roles[:2]))).status_code == 400  # one role per photo
    assert (await _upload(json.dumps([*roles[:2], {"role": "otra"}]))).status_code == 400
    assert (await _upload(json.dumps([*roles[:2], {"role": "detalle", "lot_id": other["id"]}]))).status_code == 400

    gateway = container.agent.gemini()

    def _respond(_user_id, *, contents, schema, **_kwargs):
        if schema is ZoneOverviewResult:
            return _overview_result()
        if schema is ZoneSynthesisResult:
            return _synthesis_result()
        return _group_result([(tomato, "Tomate")] if tomato["id"] in contents[-1] else [(lettuce, "Lechuga")])

    fake = AsyncMock(side_effect=_respond)
    with patch.object(gateway, "generate_structured", fake):
        up = await _upload(json.dumps(roles))
    assert up.status_code == 200, up.text
    report = (await client.get(f"/api/v1/reports/{up.json()['report_id']}", headers=h)).json()
    assert report["status"] == "ANALYSIS_COMPLETED"
    assert [r["role"] for r in report["photo_roles"]] == ["general", "detalle", "seguimiento"]
    assert report["photo_roles"][1] == {
        "role": "detalle", "lot_id": tomato["id"], "hint": "brotes nuevos", "followup_id": None,
    }

    def _images(call):
        return [p for p in call.kwargs["contents"] if not isinstance(p, str)]

    def _labels(call):
        return [p for p in call.kwargs["contents"][:-1] if isinstance(p, str)]

    calls = fake.call_args_list
    overview = next(c for c in calls if c.kwargs["schema"] is ZoneOverviewResult)
    groups = [c for c in calls if c.kwargs["schema"] is ZoneGroupAssessment]
    tomato_call = next(c for c in groups if tomato["id"] in c.kwargs["contents"][-1])
    lettuce_call = next(c for c in groups if lettuce["id"] in c.kwargs["contents"][-1])

    # 5 images in all instead of 9 (3 photos x 3 calls): the overview only the general shot, each group
    # the general shot and its own close-up, each labeled.
    assert len(_images(overview)) == 1 and _labels(overview) == ["Foto 1: vista general de la zona."]
    assert len(_images(tomato_call)) == 2 and len(_images(lettuce_call)) == 2
    assert any("Foto 2: primer plano de Tomate" in label and "brotes nuevos" in label for label in _labels(tomato_call))
    assert not any("Foto 3" in label for label in _labels(tomato_call))
    assert any("Foto 3: foto de seguimiento" in label for label in _labels(lettuce_call))


async def test_agent_creates_zone_and_plants_in_it(client, signup, with_key, scripted_model):  # noqa: F811
    user = await signup("zone-agent")
    await with_key(user)
    h = user["headers"]
    field = await _field(client, h, "Huerta del fondo")

    scripted_model.script = [
        ("call", "create_zone", {"zone": "cantero 3", "field": "huerta"}),
        ("call", "create_lot", {"crop_name": "Lechuga", "field": "huerta", "zone": "Cantero 3"}),
        ("call", "log_events", {"field": "huerta", "entries": [{"type": "irrigation", "zone": "cantero 3"}]}),
        ("text", "Listo: creé el Cantero 3, planté lechuga y registré el riego."),
    ]
    r = await client.post("/api/v1/chat", headers=h, json={"message": "armé el cantero 3 con lechuga y lo regué"})
    assert r.status_code == 200, r.text
    assert all(t["ok"] for t in r.json()["metadata"]["tool_calls"]), r.json()["metadata"]["tool_calls"]

    zones = (await client.get(f"{FARM}/fields/{field['id']}/zones", headers=h)).json()
    assert [z["label"] for z in zones] == ["Cantero 3"]
    cycles = (await client.get(f"{FARM}/lots?zone_id={zones[0]['id']}", headers=h)).json()
    assert len(cycles) == 1
    events = (await client.get(f"{FARM}/events", headers=h)).json()
    assert events[0]["zone_id"] == zones[0]["id"]
    assert events[0]["lot_ids"] == [cycles[0]["id"]]  # watering the zone reached the lettuce growing there

    # Next turn: the account structure (system instruction) lists the zone and which crop grows there.
    scripted_model.script = [("text", "ok")]
    scripted_model.requests.clear()
    conversation_id = r.json()["metadata"]["conversation_id"]
    await client.post("/api/v1/chat", headers=h, json={"message": "¿qué hay?", "conversation_id": conversation_id})
    system = str(scripted_model.requests[0].config.system_instruction)
    assert "Zonas: Cantero 3" in system and "Cantero 3)" in system
