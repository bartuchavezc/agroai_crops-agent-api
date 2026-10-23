"""
The application record (cuaderno de aplicaciones): a draft until confirmed; once confirmed it is never edited nor
deleted — corrections are new versions with their reason, a void is a last version. Products are kept as text, the
stock they came from is discounted, and the treated lots can't be harvested inside the withholding period.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.application.products.models import PhytoProduct, PhytoProductIngredient

from .test_agent_chat import scripted_model, with_key  # noqa: F401 - fixtures

FARM = "/api/v1/farm-management"
APPS = "/api/v1/applications"
SUPPLIES = "/api/v1/supplies"
WEATHER = {"time": "2026-10-20T08:00", "temperature_c": 18.0, "humidity_pct": 70.0, "wind_speed_ms": 2.5,
           "source": "open_meteo"}


@pytest.fixture(autouse=True)
def no_weather_calls(container):
    weather = container.data_providers.weather_service()
    with patch.object(weather, "conditions_at", AsyncMock(return_value=WEATHER)):
        yield


async def _registered(container, brand: str) -> str:
    """A product in the registry (the test database has none loaded)."""
    number = str(uuid.uuid4().int)[:8]
    async with container.db_session_factory()() as session:
        product = PhytoProduct(country="AR", registry_number=number, brand=brand, brand_norm=brand.upper(),
                               company="ACME S.A.", toxicity_band="III", source="test")
        session.add(product)
        await session.flush()
        session.add(PhytoProductIngredient(product_id=product.id, raw_name="PIRIMETANIL", raw_name_norm="PIRIMETANIL",
                                           concentration=40, concentration_unit="p/v"))
        await session.commit()
    return number


async def _setup(client, h):
    field = (await client.post(f"{FARM}/fields", headers=h, json={"name": "Quinta", "latitude": -34.6,
                                                                   "longitude": -58.4})).json()
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    crop = (await client.get(f"{FARM}/crop-masters?q=tomate", headers=h)).json()[0]["id"]
    lot = (await client.post(f"{FARM}/lots", headers=h, json={
        "field_id": field["id"], "crop_master_id": crop, "zone_ids": [zone["id"]], "status": "planted",
        "season": "26/27", "number": 1,
    })).json()
    return field, zone, lot


async def test_a_confirmed_application_is_versioned_discounts_stock_and_blocks_the_harvest(client, signup, container):
    user = await signup("apps")
    h = user["headers"]
    field, zone, lot = await _setup(client, h)
    number = await _registered(container, f"FUNGI {uuid.uuid4().hex[:5]}")
    brand = (await client.get(f"{SUPPLIES}/registry?q={number}", headers=h)).json()[0]
    assert (brand["registry_number"], brand["active_ingredients"]) == (number, "PIRIMETANIL 40% p/v")

    item = (await client.post(f"{SUPPLIES}/items", headers=h, json={
        "kind": "phyto", "name": brand["name"], "registry_number": number, "unit": "litros", "quantity": 1,
    })).json()
    assert (item["unit"], item["quantity"], item["registry_verified"]) == ("l", 1, True)

    draft = await client.post(APPS, headers=h, json={
        "field_id": field["id"], "zone_id": zone["id"], "kind": "phyto", "target": "tizón",
        "products": [
            {"name": brand["name"], "dose": 2, "dose_unit": "cc/L", "total_quantity": 200, "total_unit": "ml",
             "supply_item_id": item["id"], "preharvest_interval_days": 7, "interval_source": "label"},
            {"kind": "biological", "name": "Purín de ortiga casero", "dose": 1, "dose_unit": "L/10 L"},
        ],
    })
    assert draft.status_code == 201, draft.text
    draft = draft.json()
    assert draft["status"] == "draft" and draft["lot_ids"] == [lot["id"]]
    assert draft["products"][0]["registry_verified"] and draft["products"][0]["active_ingredients"]
    assert not draft["products"][1]["registry_verified"]

    # incomplete: no date, no operator
    r = await client.post(f"{APPS}/{draft['id']}/confirm", headers=h)
    assert r.status_code == 400 and "fecha" in r.json()["detail"]
    r = await client.put(f"{APPS}/{draft['id']}", headers=h, json={
        "applied_at": "2026-10-20T08:00:00-03:00", "operator_name": "Marta",
    })
    assert r.status_code == 200, r.text
    confirmed = (await client.post(f"{APPS}/{draft['id']}/confirm", headers=h)).json()
    assert confirmed["status"] == "confirmed" and confirmed["weather"]["wind_speed_ms"] == 2.5
    assert confirmed["harvest_release_date"] == "2026-10-27"
    assert any("Purín" in w and "carencia" in w for w in confirmed["warnings"])

    # the bitácora, the stock, the lot
    events = (await client.get(f"{FARM}/events?type=pest_control", headers=h)).json()
    assert events[0]["data"]["application_record_id"] == confirmed["record_id"]
    assert (await client.get(f"{SUPPLIES}/items/{item['id']}", headers=h)).json()["quantity"] == 0.8
    assert (await client.get(f"{FARM}/lots/{lot['id']}", headers=h)).json()["harvest_blocked_until"] == "2026-10-27"
    own = (await client.get(f"{APPS}/products", headers=h)).json()
    assert [p["name"] for p in own] == ["Purín de ortiga casero"]
    saved = (await client.get(f"{APPS}/intervals", headers=h)).json()
    assert [(i["crop_name"], i["preharvest_interval_days"]) for i in saved] == [("Tomate", 7)]

    # harvest inside the withholding period: refused, unless acknowledged with a reason
    harvest = {"field_id": field["id"], "lot_id": lot["id"], "type": "harvest",
               "occurred_at": "2026-10-24T10:00:00-03:00"}
    assert (await client.post(f"{FARM}/events", headers=h, json=harvest)).status_code == 400
    ok = await client.post(f"{FARM}/events", headers=h, json={**harvest, "data": {"withholding_ack": "etiqueta: 3 d"}})
    assert ok.status_code == 201 and ok.json()["data"]["withholding_until"] == "2026-10-27"

    # confirmed: not edited nor deleted
    assert (await client.put(f"{APPS}/{draft['id']}", headers=h, json={"notes": "x"})).status_code == 400
    assert (await client.delete(f"{APPS}/{draft['id']}", headers=h)).status_code == 400

    # a correction is a new version; the stock follows
    fixed = await client.post(f"{APPS}/{draft['id']}/corrections", headers=h, json={
        "reason": "Eran 300 ml", "products": [
            {"name": brand["name"], "dose": 3, "dose_unit": "cc/L", "total_quantity": 300, "total_unit": "ml",
             "supply_item_id": item["id"], "preharvest_interval_days": 7, "interval_source": "label"},
        ],
    })
    assert fixed.status_code == 201, fixed.text
    fixed = fixed.json()
    assert (fixed["version"], fixed["record_id"], fixed["correction_reason"]) == (2, draft["record_id"], "Eran 300 ml")
    assert (await client.get(f"{SUPPLIES}/items/{item['id']}", headers=h)).json()["quantity"] == 0.7
    history = (await client.get(f"{APPS}/{draft['id']}/history", headers=h)).json()
    assert [(v["version"], v["is_current"]) for v in history] == [(1, False), (2, True)]
    ledger = (await client.get(f"{SUPPLIES}/items/{item['id']}/movements", headers=h)).json()
    assert sorted(m["quantity"] for m in ledger) == [-0.3, -0.2, 0.2, 1.0]

    # the cuaderno
    csv = await client.get(f"{APPS}/export?format=csv&field_id={field['id']}", headers=h)
    assert csv.status_code == 200 and number in csv.text and "Marta" in csv.text and "Eran 300 ml" in csv.text
    pdf = await client.get(f"{APPS}/export?format=pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # a void: last version, stock back, entry out of the bitácora, harvest free
    voided = (await client.post(f"{APPS}/{draft['id']}/void", headers=h, json={"reason": "Cargada dos veces"})).json()
    assert (voided["status"], voided["version"]) == ("voided", 3)
    assert (await client.get(f"{SUPPLIES}/items/{item['id']}", headers=h)).json()["quantity"] == 1.0
    assert (await client.get(f"{FARM}/lots/{lot['id']}", headers=h)).json()["harvest_blocked_until"] is None
    entry = next(e for e in (await client.get(f"{FARM}/events?type=pest_control", headers=h)).json()
                 if e["data"].get("application_record_id") == draft["record_id"])
    assert (entry["outcome"], entry["reason"]) == ("skipped", "Aplicación anulada: Cargada dos veces")


async def test_saved_intervals_are_reused_and_staff_cannot_void(client, signup, add_member):
    owner = await signup("apps-reuse")
    h = owner["headers"]
    field, zone, lot = await _setup(client, h)
    product = {"name": "Caldo bordelés", "dose": 20, "dose_unit": "g/L", "preharvest_interval_days": 15,
               "interval_source": "label"}
    first = (await client.post(APPS, headers=h, json={
        "field_id": field["id"], "lot_ids": [lot["id"]], "applied_at": "2026-10-01T09:00:00Z",
        "operator_name": "Ana", "products": [product],
    })).json()
    await client.post(f"{APPS}/{first['id']}/confirm", headers=h)

    staff = await add_member(owner, "staff")
    second = (await client.post(APPS, headers=staff["headers"], json={
        "field_id": field["id"], "lot_ids": [lot["id"]], "applied_at": "2026-10-10T09:00:00Z",
        "operator_user_id": staff["user"]["id"],
        "products": [{"name": "caldo BORDELES", "dose": 20, "dose_unit": "g/L"}],
    })).json()
    reused = second["products"][0]
    assert (reused["preharvest_interval_days"], reused["interval_source"]) == (15, "saved")
    done = await client.post(f"{APPS}/{second['id']}/confirm", headers=staff["headers"])
    assert done.status_code == 200, done.text
    assert (await client.post(f"{APPS}/{second['id']}/void", headers=staff["headers"],
                              json={"reason": "error"})).status_code == 403
    # the longest release date of the records in force
    assert (await client.get(f"{FARM}/lots/{lot['id']}", headers=h)).json()["harvest_blocked_until"] == "2026-10-25"


async def test_the_agent_drafts_from_what_was_told_and_confirms_only_after_the_yes(
    client, signup, with_key, scripted_model  # noqa: F811
):
    user = await signup("apps-agent")
    await with_key(user)
    h = user["headers"]
    field, zone, lot = await _setup(client, h)
    scripted_model.script = [
        ("call", "record_application", {
            "field": "Quinta", "zone": "cantero 1", "target": "pulgón", "operator": "yo",
            "transcript": "apliqué jabón potásico al 2% en los tomates del cantero 1",
            "products": [{"name": "Jabón potásico", "kind": "biological", "dose": 20, "dose_unit": "ml/L"}],
        }),
        ("text", "Armé el registro: jabón potásico 20 ml/L en el Cantero 1. Falta la carencia. ¿Lo confirmo?"),
    ]
    r = await client.post("/api/v1/chat", headers=h, json={"message": "apliqué jabón potásico al 2% en los tomates"})
    assert r.status_code == 200, r.text
    drafts = (await client.get(f"{APPS}?status=draft", headers=h)).json()
    assert len(drafts) == 1 and drafts[0]["source"] == "agent" and drafts[0]["operator_user_id"] == user["user"]["id"]
    assert drafts[0]["transcript"].startswith("apliqué")

    scripted_model.script = [
        ("call", "confirm_application", {"application_id": drafts[0]["id"]}),
        ("text", "Confirmado."),
    ]
    r = await client.post("/api/v1/chat", headers=h, json={
        "message": "sí, confirmalo", "conversation_id": r.json()["metadata"]["conversation_id"],
    })
    assert r.status_code == 200 and all(t["ok"] for t in r.json()["metadata"]["tool_calls"])
    assert (await client.get(f"{APPS}/{drafts[0]['id']}", headers=h)).json()["status"] == "confirmed"
