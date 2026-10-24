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


async def test_the_zone_analysis_opens_evaluates_and_proposes_closing_followups(client, signup, container):
    import json
    from unittest.mock import AsyncMock, patch

    from src.agent.reasoning.periodic_report import (
        FollowUpEvaluation,
        FollowUpPassResult,
        ZoneIssue,
        ZoneOverviewResult,
        ZoneSynthesisResult,
    )

    from .test_zones import _TINY_PNG, _group_result, _overview_result, _synthesis_result

    user = await signup("followups-analysis")
    h = user["headers"]
    field = await _field(client, h)
    zone = await _zone(client, h, field["id"])
    tomato = await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])
    gateway = container.agent.gemini()
    calls: list = []

    def _analysis(issues=(), evolution=None):
        def _respond(_user_id, *, contents, schema, **_kwargs):
            calls.append((schema, contents))
            if schema is ZoneOverviewResult:
                return _overview_result()
            if schema is ZoneSynthesisResult:
                return _synthesis_result()
            if schema is FollowUpPassResult:
                ids = [c.split("id=")[1].split(":")[0] for c in contents if isinstance(c, str) and "id=" in c]
                return FollowUpPassResult(evaluations=[
                    FollowUpEvaluation(followup_id=i, evolution=evolution, evidence="sin colonias", confidence=0.9)
                    for i in ids
                ])
            group = _group_result([(tomato, "Tomate")])
            return group.model_copy(update={"issues": list(issues)})
        return AsyncMock(side_effect=_respond)

    async def _upload(fake, files=1, roles=None):
        calls.clear()
        data = {"zone_id": zone["id"], **({"photo_roles": json.dumps(roles)} if roles else {})}
        with patch.object(gateway, "generate_structured", fake):
            up = await client.post("/api/v1/upload/zone-tracking", headers=h, data=data, files=[
                ("image_files", (f"{i}.png", _TINY_PNG, "image/png")) for i in range(files)
            ])
        assert up.status_code == 200, up.text
        report = (await client.get(f"/api/v1/reports/{up.json()['report_id']}", headers=h)).json()
        assert report["status"] == "ANALYSIS_COMPLETED"
        return report

    # 1. The analysis sees aphids (medium): it opens the follow-up itself, with the photo and the report as
    # evidence. A mild chlorosis (low) is only proposed.
    aphids = ZoneIssue(
        title="Pulgón en tomate", kind="pest", severity="medium", lot_ids=[tomato["id"], "not-a-lot"],
        what_was_seen="colonias verdes en el envés", photo_number=1, photo_hint="envés de las hojas de arriba",
    )
    chlorosis = ZoneIssue(title="Clorosis leve", kind="deficiency", severity="low", what_was_seen="hojas pálidas",
                          photo_hint="hojas de abajo")
    first = await _upload(_analysis([aphids, chlorosis]))
    found = first["raw_analysis_data"]["followups"]
    assert [o["title"] for o in found["opened"]] == ["Pulgón en tomate"]
    assert [(a["type"], a["title"]) for a in found["suggested_actions"]] == [("open_followup", "Clorosis leve")]
    followup = (await client.get(f"{FARM}/followups/{found['opened'][0]['followup_id']}", headers=h)).json()
    assert followup["source"] == "agent" and followup["origin_report_id"] == first["id"]
    assert followup["lot_ids"] == [tomato["id"]] and followup["photo_hint"] == "envés de las hojas de arriba"
    detected = followup["events"][0]
    assert detected["source"] == "agent" and detected["data"]["followup_action"] == "opened"
    assert {(e["kind"], e["identifier"]) for e in detected["evidence"]} == {
        ("photo", first["image_identifiers"][0]), ("report", first["id"]),
    }

    # 2. The next walk photographs it: the follow-up pass gets ANTES (the detection photo) and AHORA, the crop
    # groups don't get that photo, and the group mentioning the same aphids doesn't open a second one.
    roles = [{"role": "general"}, {"role": "seguimiento", "lot_id": tomato["id"], "followup_id": followup["id"]}]
    same_aphids = aphids.model_copy(update={"followup_id": followup["id"]})
    second = await _upload(_analysis([same_aphids], evolution="no_visible"), files=2, roles=roles)
    followup_call = next(c for schema, c in calls if schema is FollowUpPassResult)
    labels = [c for c in followup_call if isinstance(c, str)]
    assert any(f"id={followup['id']}: Pulgón en tomate" in c for c in labels)
    assert any(c.startswith("ANTES (") for c in labels) and "AHORA:" in labels
    assert sum(1 for c in followup_call if not isinstance(c, str)) == 2  # ANTES + AHORA
    group_call = next(c for schema, c in calls if schema not in (ZoneOverviewResult, ZoneSynthesisResult,
                                                                  FollowUpPassResult))
    assert sum(1 for c in group_call if not isinstance(c, str)) == 1  # only the general shot
    synthesis_call = next(c for schema, c in calls if schema is ZoneSynthesisResult)
    assert f"Seguimiento id={followup['id']}: no se ve" in synthesis_call[0]

    found = second["raw_analysis_data"]["followups"]
    assert found["opened"] == [] and found["suggested_actions"] == []  # once isn't enough to propose closing
    [evaluation] = found["evaluations"]
    assert evaluation["evolution"] == "no_visible" and evaluation["photo"] == second["image_identifiers"][1]
    assert evaluation["previous_photo"] == first["image_identifiers"][0]
    timeline = (await client.get(f"{FARM}/followups/{followup['id']}", headers=h)).json()
    assert timeline["entries"] == 2 and timeline["last_evolution"] == "no_visible"
    evaluated = timeline["events"][0]
    assert evaluated["notes"] == "Seguimiento de Pulgón en tomate: no se ve. sin colonias"
    assert [(e["identifier"], e["note"]) for e in evaluated["evidence"] if e["kind"] == "photo"] == [
        (second["image_identifiers"][1], None), (first["image_identifiers"][0], evaluated["evidence"][1]["note"]),
    ]
    assert evaluated["evidence"][1]["note"].startswith("antes (")

    # 3. Not seen twice in a row: the analysis proposes closing it (it never closes it itself).
    third = await _upload(_analysis(evolution="no_visible"), files=2, roles=roles)
    assert [a["type"] for a in third["raw_analysis_data"]["followups"]["suggested_actions"]] == ["close_followup"]
    assert (await client.get(f"{FARM}/followups/{followup['id']}", headers=h)).json()["status"] == "abierto"

    # 4. Re-running the same report doesn't log anything twice.
    with patch.object(gateway, "generate_structured", _analysis(evolution="no_visible")):
        retry = await client.post("/api/v1/analyze", headers=h, json={"report_id": third["id"]})
    assert retry.status_code == 200, retry.text
    assert (await client.get(f"{FARM}/followups/{followup['id']}", headers=h)).json()["entries"] == 3


async def test_a_followup_photo_must_name_an_open_followup_of_the_zone(client, signup):
    import json

    from .test_zones import _TINY_PNG

    user = await signup("followups-photo")
    h = user["headers"]
    field = await _field(client, h)
    zone, other = await _zone(client, h, field["id"]), await _zone(client, h, field["id"])
    await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])
    elsewhere = (await client.post(f"{FARM}/followups", headers=h, json={
        "field_id": field["id"], "zone_id": other["id"], "title": "Oídio"})).json()
    for role in ({"role": "seguimiento", "followup_id": elsewhere["id"]},
                 {"role": "detalle", "followup_id": elsewhere["id"]}):
        bad = await client.post(
            "/api/v1/upload/zone-tracking", headers=h,
            data={"zone_id": zone["id"], "photo_roles": json.dumps([role])},
            files=[("image_files", ("a.png", _TINY_PNG, "image/png"))],
        )
        assert bad.status_code == 400


async def test_capture_plan_of_a_field(client, signup):
    user = await signup("capture-plan")
    h = user["headers"]
    field = await _field(client, h)
    first, empty = await _zone(client, h, field["id"], "cajon"), await _zone(client, h, field["id"], "cajon")
    tomato = await _cycle(client, h, field["id"], "tomate", zone_id=first["id"])
    aphids = (await client.post(f"{FARM}/followups", headers=h, json={
        "field_id": field["id"], "lot_ids": [tomato["id"]], "title": "Pulgón en tomate", "severity": "high",
        "photo_hint": "envés de las hojas", "evidence": [{"kind": "photo", "identifier": "a1.jpg"}],
    })).json()

    plan = await client.get(f"{FARM}/fields/{field['id']}/capture-plan", headers=h)
    assert plan.status_code == 200, plan.text
    plan = plan.json()
    assert plan["max_photos"] == 3 and [z["label"] for z in plan["zones"]] == ["Cajón 1"]  # Cajón 2 has no crops
    assert empty["id"] not in {z["zone_id"] for z in plan["zones"]}
    general, followup, detail = plan["zones"][0]["steps"]
    assert general["role"] == "general" and detail["role"] == "detalle"
    assert followup["followup_id"] == aphids["id"] and followup["previous_photo"] == "a1.jpg"
    assert followup["hint"] == "envés de las hojas" and followup["lot_id"] == tomato["id"]

    stranger = await signup("capture-plan-stranger")
    assert (await client.get(f"{FARM}/fields/{field['id']}/capture-plan", headers=stranger["headers"])).status_code \
        in (403, 404)
