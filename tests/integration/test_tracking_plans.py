"""The agent's tracking plan of a lot: written as stages with windows and key checks (never chores for the person),
corrected with a readable reason by each observation, and readable from the web while its design is worked out."""
import uuid
from datetime import date, timedelta

import pytest

from src.application.tracking.schemas import ItemChange, PlanRevise, StageChange, TrackingPlanContent
from src.shared.domain.actor import Actor
from src.shared.utils.errors import InvalidInputError

from .test_agent_chat import scripted_model, with_key  # noqa: F401,E402 - fixtures

FARM = "/api/v1/farm-management"


async def _lot_in_two_zones(client, h):
    field = (await client.post(f"{FARM}/fields", headers=h, json={
        "name": "Huerta", "latitude": -34.6, "longitude": -58.4,
        "irrigation": {"system": "manguera", "timer": False},
    })).json()
    first = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "maceta"})).json()
    second = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={
        "type": "tierra_directa", "irrigation": {"system": "goteo", "timer": True},
    })).json()
    crop = (await client.get(f"{FARM}/crop-masters?q=tomate", headers=h)).json()[0]["id"]
    lot = (await client.post(f"{FARM}/lots", headers=h, json={
        "field_id": field["id"], "crop_master_id": crop, "zone_ids": [first["id"], second["id"]],
        "status": "planted", "planting_date": date.today().isoformat(), "sowing_method": "plantin_comprado",
    }))
    assert lot.status_code == 201, lot.text
    return field, first, second, lot.json()


def _plan(today: date) -> TrackingPlanContent:
    return TrackingPlanContent.model_validate({
        "summary": "Tomate de plantín en maceta y tierra directa, riego con manguera.",
        "current_stage": "vegetativo",
        "stages": [
            {"key": "vegetativo", "name": "Crecimiento vegetativo", "status": "actual",
             "window_start": today.isoformat(), "window_end": (today + timedelta(days=20)).isoformat()},
            {"key": "floracion", "name": "Floración", "window_start": (today + timedelta(days=21)).isoformat(),
             "window_end": (today + timedelta(days=30)).isoformat(), "risks": ["caída de flores con calor"]},
        ],
        "key_moments": [{"key": "cuajado", "name": "Cuajado del primer racimo",
                         "window_start": (today + timedelta(days=30)).isoformat()}],
        "items": [
            {"section": "revision", "title": "Humedad a 20 cm", "why": "Sube la radiación",
             "how": "Test táctil a 20 cm antes de regar", "method": "medicion", "measurement": "humedad_suelo",
             "window_start": today.isoformat(), "window_end": (today + timedelta(days=4)).isoformat()},
            {"section": "sanidad", "title": "Envés de hojas basales", "why": "Humedad alta prevista",
             "how": "Foto del envés de 2 hojas de abajo", "window_start": (today + timedelta(days=10)).isoformat()},
            {"section": "proteccion", "title": "Riesgo por modelo", "why": "TOM-CAST", "how": "Lo calculo yo",
             "ask_user": False, "window_start": today.isoformat()},
        ],
    })


async def test_the_production_context_is_kept(client, signup):
    user = await signup("context")
    h = user["headers"]
    field, maceta, tierra, lot = await _lot_in_two_zones(client, h)
    assert field["irrigation"] == {"system": "manguera", "timer": False, "notes": None}
    assert maceta["label"] == "Maceta 1" and tierra["label"] == "Tierra directa 1"
    assert tierra["irrigation"]["system"] == "goteo"
    assert lot["sowing_method"] == "plantin_comprado"
    bad = await client.post(f"{FARM}/lots", headers=h, json={
        "field_id": field["id"], "crop_master_id": lot["crop_master_id"], "sowing_method": "al voleo"})
    assert bad.status_code == 422


async def test_a_plan_is_written_corrected_with_its_reason_and_read(client, signup, container):
    user = await signup("plan")
    h = user["headers"]
    _, maceta, tierra, lot = await _lot_in_two_zones(client, h)
    actor = Actor(user_id=uuid.UUID(user["user"]["id"]), account_id=uuid.UUID(user["account"]["id"]), role="owner")
    service = container.application.tracking_plan_service()
    lot_id = uuid.UUID(lot["id"])
    assert (await client.get(f"{FARM}/lots/{lot['id']}/tracking-plan", headers=h)).status_code == 404

    today = date.today()
    saved = await service.save(actor, lot_id, _plan(today), "Plan inicial con la ficha del tomate")
    assert saved.version == 1 and len({i.id for i in saved.content.items}) == 3
    # only what asks the person, already open, in order
    due = await service.due_items(actor, today)
    assert [item.title for _, item in due] == ["Humedad a 20 cm"]

    # an observation moves the flowering earlier and answers the moisture check, with a readable reason
    moisture = next(i for i in saved.content.items if i.title == "Humedad a 20 cm")
    revised = await service.revise(actor, lot_id, PlanRevise(
        reason="Adelanto la floración 5 días: +14 % de GDD acumulado y botones florales en la foto",
        observation="Análisis de zona de la Maceta 1",
        current_stage="floracion",
        stages=[StageChange(key="floracion", window_start=today + timedelta(days=16),
                            window_end=today + timedelta(days=25))],
        items=[ItemChange(id=moisture.id, status="hecho", result="Húmedo a 20 cm")],
    ))
    assert revised.version == 2 and revised.last_observation_at is not None
    assert revised.content.current_stage == "floracion"
    assert [s.status for s in revised.content.stages] == ["cumplida", "actual"]
    last = revised.revisions[-1]
    assert "+14 % de GDD" in last.reason and any("Floración" in c for c in last.changes)
    assert await service.due_items(actor, today) == []

    # rewriting keeps the results already gathered
    rewritten = await service.save(actor, lot_id, TrackingPlanContent.model_validate({
        **revised.content.model_dump(mode="json"), "summary": "Rehecho"}), "Replanificación")
    assert next(i for i in rewritten.content.items if i.id == moisture.id).result == "Húmedo a 20 cm"

    with pytest.raises(InvalidInputError):
        await service.revise(actor, lot_id, PlanRevise(reason="x" * 5, items=[ItemChange(id="nope")]))

    read = (await client.get(f"{FARM}/lots/{lot['id']}/tracking-plan", headers=h)).json()
    assert read["version"] == 3 and read["content"]["summary"] == "Rehecho"
    assert [r["reason"] for r in read["revisions"]][0] == "Plan inicial con la ficha del tomate"
    listed = (await client.get(f"{FARM}/tracking-plans", headers=h)).json()
    assert [p["lot_id"] for p in listed] == [lot["id"]]

    other = await signup("other")
    assert (await client.get(f"{FARM}/lots/{lot['id']}/tracking-plan",
                             headers=other["headers"])).status_code == 404


async def test_the_chat_agent_corrects_the_plan_with_a_tool(
    client, signup, with_key, scripted_model, container  # noqa: F811
):
    user = await signup("chatplan")
    await with_key(user)
    h = user["headers"]
    _, _, _, lot = await _lot_in_two_zones(client, h)
    actor = Actor(user_id=uuid.UUID(user["user"]["id"]), account_id=uuid.UUID(user["account"]["id"]), role="owner")
    await container.application.tracking_plan_service().save(actor, uuid.UUID(lot["id"]), _plan(date.today()), "x")
    scripted_model.script = [
        ("call", "revise_tracking_plan", {"lot_id": lot["id"], "reason": "Floreció antes de lo previsto",
                                          "observation": "Lo contó en el chat", "current_stage": "floracion"}),
        ("text", "Anotado: adelanto la floración."),
    ]
    r = await client.post("/api/v1/chat", headers=h, json={"message": "ya tiene flores el tomate"})
    assert r.status_code == 200, r.text
    plan = (await client.get(f"{FARM}/lots/{lot['id']}/tracking-plan", headers=h)).json()
    assert plan["content"]["current_stage"] == "floracion"
    assert plan["revisions"][-1]["reason"] == "Floreció antes de lo previsto"
