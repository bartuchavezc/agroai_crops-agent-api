"""Gestión: field + assignee on items, edit, cancel, soft delete, filters, per-field balance."""
import uuid

MG = "/api/v1/management"


async def _field(client, owner, name):
    response = await client.post("/api/v1/farm-management/fields", headers=owner["headers"], json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_shopping_items_field_assignee_edit_cancel_delete(client, signup, add_member):
    owner = await signup("mg-shop")
    staff = await add_member(owner, "staff")
    h = owner["headers"]
    huerta = await _field(client, owner, "Huerta")

    item = await client.post(
        f"{MG}/shopping-list", headers=h,
        json={"name": "Semillas de lechuga", "category": "Semillas", "field_id": huerta,
              "assigned_to": staff["user"]["id"]},
    )
    assert item.status_code == 201, item.text
    item = item.json()
    assert item["field_id"] == huerta and item["assigned_to"] == staff["user"]["id"]
    general = (await client.post(f"{MG}/shopping-list", headers=h, json={"name": "Guantes"})).json()

    by_field = (await client.get(f"{MG}/shopping-list?field_id={huerta}", headers=h)).json()
    assert [i["id"] for i in by_field] == [item["id"]]
    no_field = (await client.get(f"{MG}/shopping-list?field_id=none", headers=h)).json()
    assert [i["id"] for i in no_field] == [general["id"]]
    mine = (await client.get(f"{MG}/shopping-list?assigned_to={staff['user']['id']}", headers=h)).json()
    assert [i["id"] for i in mine] == [item["id"]]
    unassigned = (await client.get(f"{MG}/shopping-list?assigned_to=none", headers=h)).json()
    assert [i["id"] for i in unassigned] == [general["id"]]

    # edit (staff can), clear the field, cancel
    edited = await client.put(
        f"{MG}/shopping-list/{item['id']}", headers=staff["headers"],
        json={"name": "Semillas de rúcula", "field_id": None, "status": "cancelado"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "Semillas de rúcula"
    assert edited.json()["field_id"] is None and edited.json()["status"] == "cancelado"
    null_status = await client.put(f"{MG}/shopping-list/{item['id']}", headers=h, json={"status": None})
    assert null_status.status_code == 422
    cancelled = (await client.get(f"{MG}/shopping-list?status_filter=cancelado", headers=h)).json()
    assert [i["id"] for i in cancelled] == [item["id"]]

    # assignee must be an active member of the same account
    other = await signup("mg-shop-other")
    foreign = await client.put(
        f"{MG}/shopping-list/{item['id']}", headers=h, json={"assigned_to": other["user"]["id"]}
    )
    assert foreign.status_code == 400

    # delete: manager only, soft
    assert (await client.delete(f"{MG}/shopping-list/{item['id']}", headers=staff["headers"])).status_code == 403
    assert (await client.delete(f"{MG}/shopping-list/{item['id']}", headers=h)).status_code == 204
    remaining = (await client.get(f"{MG}/shopping-list", headers=h)).json()
    assert [i["id"] for i in remaining] == [general["id"]]


async def test_budget_edit_delete_and_balance_by_field(client, signup, add_member):
    owner = await signup("mg-budget")
    staff = await add_member(owner, "staff")
    h = owner["headers"]
    a = await _field(client, owner, "Campo A")
    b = await _field(client, owner, "Campo B")

    async def entry(**body):
        response = await client.post(f"{MG}/budget", headers=h, json={"date": "2026-10-01", **body})
        assert response.status_code == 201, response.text
        return response.json()

    await entry(description="Semillas", amount=100, type="gasto", field_id=a)
    venta = await entry(description="Venta", amount=300, type="ingreso", field_id=a)
    await entry(description="Riego", amount=50, type="gasto", field_id=b)
    await entry(description="Herramientas", amount=20, type="gasto")

    summary_a = (await client.get(f"{MG}/budget/summary?field_id={a}", headers=h)).json()
    assert summary_a["balance"] == 200 and summary_a["field_id"] == a
    assert (await client.get(f"{MG}/budget/summary?field_id=none", headers=h)).json()["balance"] == -20
    assert (await client.get(f"{MG}/budget/summary", headers=h)).json()["balance"] == 130
    gastos = (await client.get(f"{MG}/budget?type=gasto", headers=h)).json()
    assert len(gastos) == 3

    denied = await client.put(f"{MG}/budget/{venta['id']}", headers=staff["headers"], json={"amount": 1})
    assert denied.status_code == 403
    edited = await client.put(f"{MG}/budget/{venta['id']}", headers=h, json={"amount": 250, "field_id": b})
    assert edited.status_code == 200, edited.text
    assert (await client.get(f"{MG}/budget/summary?field_id={a}", headers=h)).json()["balance"] == -100
    assert (await client.get(f"{MG}/budget/summary?field_id={b}", headers=h)).json()["balance"] == 200

    assert (await client.delete(f"{MG}/budget/{venta['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{MG}/budget/summary?field_id={b}", headers=h)).json()["balance"] == -50


async def test_roadmap_assignee_cancel_and_filters(client, signup, add_member):
    owner = await signup("mg-roadmap")
    tecnico = await add_member(owner, "tecnico")
    h = owner["headers"]
    field = await _field(client, owner, "Invernadero")

    task = (
        await client.post(
            f"{MG}/roadmap", headers=h,
            json={"title": "Armar túnel", "field_id": field, "assigned_to": tecnico["user"]["id"]},
        )
    ).json()
    other = (await client.post(f"{MG}/roadmap", headers=h, json={"title": "Comprar media sombra"})).json()

    assigned = (await client.get(f"{MG}/roadmap?assigned_to={tecnico['user']['id']}", headers=h)).json()
    assert [i["id"] for i in assigned] == [task["id"]]

    # a partial update leaves the other values alone (status isn't reset to null)
    moved = await client.put(f"{MG}/roadmap/{task['id']}", headers=h, json={"target_date": "2026-11-01"})
    assert moved.status_code == 200 and moved.json()["status"] == "pendiente"
    assert moved.json()["assigned_to"] == tecnico["user"]["id"]

    cancelled = await client.put(
        f"{MG}/roadmap/{other['id']}", headers=h, json={"status": "cancelado", "assigned_to": None}
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelado"
    listed = (await client.get(f"{MG}/roadmap?status_filter=cancelado", headers=h)).json()
    assert [i["id"] for i in listed] == [other["id"]]
    assert (await client.get(f"{MG}/roadmap?status_filter=borrado", headers=h)).status_code == 422

    assert (await client.delete(f"{MG}/roadmap/{task['id']}", headers=tecnico["headers"])).status_code == 204
    assert [i["id"] for i in (await client.get(f"{MG}/roadmap", headers=h)).json()] == [other["id"]]


async def test_budget_categories_currency_and_cycle_economics(client, signup):
    owner = await signup("mg-econ")
    h = owner["headers"]
    field = await _field(client, owner, "Huerta")
    tomato = [c for c in (await client.get("/api/v1/farm-management/crop-masters?q=tomate", headers=h)).json()
              if c["name"] == "Tomate"][0]
    cycle = await client.post(
        "/api/v1/farm-management/crop-cycles", headers=h,
        json={"field_id": field, "crop_master_id": tomato["id"], "plant_count": 20, "expected_yield_kg": 60,
              "expected_price": 2.5},
    )
    assert cycle.status_code == 201, cycle.text
    created = cycle.json()
    assert (created["plant_count"], created["expected_yield_kg"], created["expected_price"]) == (20, 60, 2.5)
    cycle_id = created["id"]

    # categories: stable keys, labels in the user's locale; a typed label is stored as the key
    cats = (await client.get(f"{MG}/budget/categories", headers=h)).json()
    assert {"key": "mano_de_obra", "label": "Mano de obra", "type": "gasto"} in cats

    async def entry(**body):
        response = await client.post(f"{MG}/budget", headers=h, json={"date": "2026-10-01", **body})
        assert response.status_code == 201, response.text
        return response.json()

    seeds = await entry(description="Plantines", amount=40, type="gasto", category="Semillas", crop_cycle_id=cycle_id)
    assert seeds["category"] == "semillas"
    await entry(description="Abono", amount=20, type="gasto", category="mi categoría", crop_cycle_id=cycle_id)
    await entry(description="Venta", amount=100, type="ingreso", crop_cycle_id=cycle_id)
    await entry(description="Algo en pesos mexicanos", amount=999, type="gasto", currency="MXN")  # another money
    await entry(description="Gasto suelto", amount=7, type="gasto")

    summary = (await client.get(f"{MG}/budget/summary?cycle_id={cycle_id}", headers=h)).json()
    assert summary["currency"] == "ARS" and summary["total_gastos"] == 60 and summary["balance"] == 40
    assert summary["by_category"]["semillas"] == -40 and summary["by_category"]["mi categoría"] == -20
    assert summary["cost_per_plant"] == 3.0 and summary["break_even_kg"] == 24.0
    assert summary["expected_revenue"] == 150.0 and summary["margin"] == 90.0

    whole = (await client.get(f"{MG}/budget/summary", headers=h)).json()
    assert whole["total_gastos"] == 67 and whole["other_currencies"] == {"MXN": -999.0}  # never mixed in
    assert whole["cost_per_plant"] is None and whole["break_even_kg"] is None  # only a single cycle has them
    by_crop = (await client.get(f"{MG}/budget/summary?crop_master_id={tomato['id']}", headers=h)).json()
    assert by_crop["total_gastos"] == 60

    bare = await client.post(
        "/api/v1/farm-management/crop-cycles", headers=h, json={"field_id": field, "crop_master_id": tomato["id"]}
    )
    nothing = (await client.get(f"{MG}/budget/summary?cycle_id={bare.json()['id']}", headers=h)).json()
    assert nothing["break_even_kg"] is None and nothing["margin"] is None and nothing["cost_per_plant"] is None


async def test_accounts_keep_their_books_in_the_owners_currency(client, container):
    async def signed(country):
        email = f"cur-{country.lower()}-{uuid.uuid4().hex[:6]}@example.com"
        response = await client.post(
            "/api/v1/auth/signup", json={"email": email, "password": "secret-pass-1", "country": country}
        )
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        field = await client.post("/api/v1/farm-management/fields", headers=headers, json={"name": "H"})
        await client.post(f"{MG}/budget", headers=headers,
                          json={"date": "2026-10-01", "description": "x", "amount": 5, "type": "gasto"})
        return (await client.get(f"{MG}/budget/summary", headers=headers)).json()["currency"], field.status_code

    assert (await signed("CO"))[0] == "COP" and (await signed("MX"))[0] == "MXN" and (await signed("AR"))[0] == "ARS"
