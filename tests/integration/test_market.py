"""
Red Km 0: a producer publishes a lot on purpose, a buyer with no account orders it, the producer accepts, packs
and leaves it ready, the network delivers it and it counts as a sale. The listing follows its lot.
"""
from datetime import date, timedelta

FARM = "/api/v1/farm-management"
M = "/api/v1/market"
ADMIN_EMAIL = "platform-admin@example.com"  # configured as "Platform-Admin@example.com" in conftest
NEAR = {"lat": -34.8712, "lng": -58.0455}  # the buyer: City Bell


async def _admin_headers(client):
    login = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "secret-pass-1"})
    if login.status_code != 200:
        signup = await client.post("/api/v1/auth/signup", json={"email": ADMIN_EMAIL, "password": "secret-pass-1"})
        assert signup.status_code == 200, signup.text
        return {"Authorization": f"Bearer {signup.json()['access_token']}"}
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _producer(client, owner, name="Los Aromos"):
    h = owner["headers"]
    nowhere = (await client.post(f"{FARM}/fields", headers=h, json={"name": "Sin ubicar"})).json()
    field = (await client.post(f"{FARM}/fields", headers=h, json={
        "name": "Huerta", "city": "Villa Elisa", "latitude": -34.8530, "longitude": -58.0790,
    })).json()
    assert (await client.get(f"{M}/me", headers=h)).json() is None
    no_place = await client.put(f"{M}/me", headers=h, json={"field_id": nowhere["id"], "display_name": name})
    assert no_place.status_code == 400  # buyers see the distance: the field needs its location
    me = await client.put(f"{M}/me", headers=h, json={"field_id": field["id"], "display_name": name})
    assert me.status_code == 200, me.text
    assert me.json()["plan"] == "free" and me.json()["barrio"] == "Villa Elisa"
    crop = (await client.get(f"{FARM}/crop-masters?q=lechuga", headers=h)).json()[0]["id"]
    return field, crop, me.json()


async def _lot(client, h, field, crop, status="growing", **extra):
    lot = await client.post(f"{FARM}/lots", headers=h, json={
        "field_id": field["id"], "crop_master_id": crop, "status": status, "planting_date": "2026-09-01", **extra,
    })
    assert lot.status_code == 201, lot.text
    return lot.json()


def _buyer(email="cocina@bodegon.com"):
    return {"name": "Bodegón La Esquina", "email": email, "kind": "restaurante", "address": "Cantilo 123, City Bell"}


async def test_publish_order_prepare_and_deliver(client, signup, add_member):
    owner = await signup("market")
    staff = await add_member(owner, "staff")
    h = owner["headers"]
    field, crop, producer = await _producer(client, owner)

    # nothing sown goes on sale by itself, and a planned lot can't be published
    planned = await _lot(client, h, field, crop, status="planned")
    candidates = {c["lot_id"]: c for c in (await client.get(f"{M}/lots", headers=h)).json()}
    assert candidates[planned["id"]]["publishable"] is False
    refused = await client.post(f"{M}/listings", headers=h, json={"lot_id": planned["id"], "weekly_capacity_kg": 10})
    assert refused.status_code == 400

    lot = await _lot(client, h, field, crop, expected_price=4.2)
    staff_try = await client.post(f"{M}/listings", headers=staff["headers"],
                                  json={"lot_id": lot["id"], "weekly_capacity_kg": 60})
    assert staff_try.status_code == 403
    listing = await client.post(f"{M}/listings", headers=h, json={
        "lot_id": lot["id"], "category": "hojas", "weekly_capacity_kg": 60, "weeks": 16, "stock_kg": 40,
    })
    assert listing.status_code == 201, listing.text
    listing = listing.json()
    assert listing["price_per_kg"] == 4.2  # from the lot
    assert listing["on_sale"] and listing["availability"]["kind"] == "now"
    again = await client.post(f"{M}/listings", headers=h, json={"lot_id": lot["id"], "weekly_capacity_kg": 5})
    assert again.status_code == 400  # one listing per lot

    # the public catalog: no token, approximate place, distance from the buyer
    catalog = (await client.get(f"{M}/public/catalog", params=NEAR)).json()
    mine = next(p for p in catalog["producers"] if p["id"] == producer["id"])
    assert (mine["lat"], mine["lng"]) == (-34.855, -58.08)
    assert 3 < mine["distance_km"] < 4.5 and mine["listing_count"] == 1 and mine["sealed"] is False
    assert any(item["id"] == listing["id"] and item["stock_kg"] == 40 for item in catalog["listings"])
    far = (await client.get(f"{M}/public/catalog", params={**NEAR, "radius_km": 1})).json()
    assert producer["id"] not in {p["id"] for p in far["producers"]}

    # a buyer with no account orders; asking for more than is free fails as a whole
    too_much = await client.post(f"{M}/public/orders", json={
        "buyer": _buyer(), "items": [{"listing_id": listing["id"], "kg": 45}],
    })
    assert too_much.status_code == 400
    placed = await client.post(f"{M}/public/orders", json={
        "buyer": _buyer(), "items": [{"listing_id": listing["id"], "kg": 15}], "recurring": True,
    })
    assert placed.status_code == 201, placed.text
    order = placed.json()
    assert order["code"] >= 2001 and len(order["token"]) > 20
    assert order["subtotal"] == 63.0 and order["logistics_fee"] == 9 and order["total"] == 72.0
    assert order["status"] == "recibido" and order["delivery_date"] > date.today().isoformat()
    stock = (await client.get(f"{M}/listings", headers=h)).json()[0]["stock_kg"]
    assert stock == 25

    wrong = await client.get(f"{M}/public/orders/{order['code']}", params={"token": "x" * 20})
    assert wrong.status_code == 404
    follow = (await client.get(f"{M}/public/orders/{order['code']}", params={"token": order["token"]})).json()
    assert follow["parts"][0]["producer_name"] == "Los Aromos"

    # the producer hears about it
    notes = (await client.get("/api/v1/notifications", headers=h)).json()
    assert any(n["type"] == "market_order" for n in notes)

    # accept, pack box by box, ready
    active = (await client.get(f"{M}/orders", headers=h)).json()
    part = next(p for p in active if p["code"] == order["code"])
    assert part["status"] == "nuevo" and part["fee_rate"] == 0.2 and part["net"] == 50.4
    assert [b["code"] for b in part["boxes"]] == [f"{order['code']}-LE1", f"{order['code']}-LE2",
                                                  f"{order['code']}-LE3"]
    assert (await client.post(f"{M}/orders/{part['id']}/accept", headers=staff["headers"])).status_code == 403
    assert (await client.post(f"{M}/orders/{part['id']}/accept", headers=h)).json()["status"] == "prep"
    codes = [b["code"] for b in part["boxes"]]
    packing = await client.put(f"{M}/orders/{part['id']}/packed", headers=staff["headers"], json={"packed": codes[:2]})
    assert [b["packed"] for b in packing.json()["boxes"]] == [True, True, False]
    assert (await client.post(f"{M}/orders/{part['id']}/ready", headers=h)).status_code == 400
    await client.put(f"{M}/orders/{part['id']}/packed", headers=staff["headers"], json={"packed": codes})
    ready = await client.post(f"{M}/orders/{part['id']}/ready", headers=staff["headers"])
    assert ready.json()["status"] == "listo"
    follow = (await client.get(f"{M}/public/orders/{order['code']}", params={"token": order["token"]})).json()
    assert follow["status"] == "en_camino"

    # the network's route passes by today; delivering counts the sale
    admin = await _admin_headers(client)
    assert (await client.post(f"{M}/admin/routes", headers=h, json={})).status_code in (404, 422)
    route = await client.post(f"{M}/admin/routes", headers=admin, json={
        "route_date": part["pickup_date"], "name": "Ruta norte", "driver_name": "Lucas", "hub_name": "Hub Villa Elisa",
        "stops": [{"producer_id": producer["id"], "eta": "10:15"}],
    })
    assert route.status_code == 201, route.text
    assert (await client.post(f"{M}/admin/order-parts/{part['id']}/deliver", headers=admin)).status_code == 204

    panel = (await client.get(f"{M}/dashboard", headers=h)).json()
    assert panel["month_sales"] == 63.0 and panel["month_orders"] == 1
    assert panel["sales"][0]["net"] == 50.4
    assert panel["plan_month"]["fee"] == 12.6 and panel["plan_month"]["plan"] == "free"
    assert panel["route"]["driver_name"] == "Lucas" and panel["route"]["my_eta"] == "10:15:00"
    assert panel["route"]["stops"][0]["picked_up"] is True
    done = (await client.get(f"{M}/orders?scope=done", headers=h)).json()
    assert done[0]["status"] == "entregado"


async def test_rejecting_gives_stock_back_and_pro_lowers_the_fee(client, signup):
    owner = await signup("market-pro")
    h = owner["headers"]
    field, crop, _ = await _producer(client, owner, "El Ceibo")
    lot = await _lot(client, h, field, crop)
    listing = (await client.post(f"{M}/listings", headers=h, json={
        "lot_id": lot["id"], "price_per_kg": 8, "weekly_capacity_kg": 30, "stock_kg": 20,
    })).json()

    order = (await client.post(f"{M}/public/orders", json={
        "buyer": _buyer("hotel@gonnet.com"), "items": [{"listing_id": listing["id"], "kg": 10}],
    })).json()
    part = (await client.get(f"{M}/orders", headers=h)).json()[0]
    rejected = await client.post(f"{M}/orders/{part['id']}/reject", headers=h, json={"reason": "Granizo"})
    assert rejected.json()["status"] == "rechazado"
    assert (await client.get(f"{M}/listings", headers=h)).json()[0]["stock_kg"] == 20
    follow = (await client.get(f"{M}/public/orders/{order['code']}", params={"token": order["token"]})).json()
    assert follow["status"] == "cancelado" and follow["total"] == 0

    assert (await client.put(f"{M}/me/plan", headers=h, json={"plan": "pro"})).json()["plan"] == "pro"
    await client.post(f"{M}/public/orders", json={
        "buyer": _buyer("hotel@gonnet.com"), "items": [{"listing_id": listing["id"], "kg": 10}],
    })
    newest = (await client.get(f"{M}/orders", headers=h)).json()[0]
    assert newest["fee_rate"] == 0.08 and newest["net"] == 73.6


async def test_listing_follows_its_lot(client, signup):
    owner = await signup("market-sync")
    h = owner["headers"]
    field, crop, producer = await _producer(client, owner, "Patio Ñandú")
    later = (date.today() + timedelta(days=20)).isoformat()
    lot = await _lot(client, h, field, crop, expected_harvest_date=later, expected_price=12)
    listing = (await client.post(f"{M}/listings", headers=h, json={
        "lot_id": lot["id"], "weekly_capacity_kg": 5,
    })).json()
    assert listing["available_from"] == later  # from the lot's expected harvest
    assert listing["availability"] == {"kind": "presale", "from": later}

    # a presale reserves against the weekly capacity, not this week's stock
    ok = await client.post(f"{M}/public/orders", json={
        "buyer": _buyer(), "items": [{"listing_id": listing["id"], "kg": 5}],
    })
    assert ok.status_code == 201, ok.text
    assert ok.json()["delivery_date"] >= later
    full = await client.post(f"{M}/public/orders", json={  # the 5 kg/week are reserved now
        "buyer": _buyer("otro@local.com"), "items": [{"listing_id": listing["id"], "kg": 1}],
    })
    assert full.status_code == 400

    # the lot failed: off sale everywhere, and the producer sees why
    await client.put(f"{FARM}/lots/{lot['id']}", headers=h, json={"status": "failed"})
    mine = (await client.get(f"{M}/listings", headers=h)).json()[0]
    assert mine["on_sale"] is False and mine["hidden_reason"] == "lot_failed"
    catalog = (await client.get(f"{M}/public/catalog")).json()
    assert listing["id"] not in {item["id"] for item in catalog["listings"]}
    assert producer["id"] not in {p["id"] for p in catalog["producers"]}
    gone = await client.post(f"{M}/public/orders", json={
        "buyer": _buyer(), "items": [{"listing_id": listing["id"], "kg": 5}],
    })
    assert gone.status_code == 400

    # paused by hand, then closed
    lot2 = await _lot(client, h, field, crop)
    second = (await client.post(f"{M}/listings", headers=h, json={
        "lot_id": lot2["id"], "weekly_capacity_kg": 5, "price_per_kg": 3,
    })).json()
    paused = (await client.put(f"{M}/listings/{second['id']}", headers=h, json={"status": "paused"})).json()
    assert paused["hidden_reason"] == "paused"
    assert (await client.delete(f"{M}/listings/{second['id']}", headers=h)).status_code == 204
    assert second["id"] not in {item["id"] for item in (await client.get(f"{M}/listings", headers=h)).json()}
