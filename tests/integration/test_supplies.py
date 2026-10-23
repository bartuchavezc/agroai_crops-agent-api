"""Inputs in stock: written as on the label, moved only through an append-only ledger."""
SUPPLIES = "/api/v1/supplies"


async def test_receipts_and_adjustments_move_the_stock_through_the_ledger(client, signup, add_member):
    owner = await signup("supplies")
    h = owner["headers"]
    item = (await client.post(f"{SUPPLIES}/items", headers=h, json={
        "kind": "fertilizer", "name": "Humus de lombriz", "unit": "kg", "quantity": 10, "expiry_date": "2026-11-01",
    })).json()
    assert (item["quantity"], item["registry_verified"]) == (10, False)

    staff = await add_member(owner, "staff")
    got = await client.post(f"{SUPPLIES}/items/{item['id']}/movements", headers=staff["headers"],
                            json={"kind": "receipt", "quantity": 500, "unit": "g"})
    assert got.status_code == 201 and got.json()["quantity"] == 10.5
    # an adjustment is the owner's/tecnico's, with its reason
    assert (await client.post(f"{SUPPLIES}/items/{item['id']}/movements", headers=staff["headers"],
                              json={"kind": "adjustment", "quantity": -1, "reason": "x"})).status_code == 403
    assert (await client.post(f"{SUPPLIES}/items/{item['id']}/movements", headers=h,
                              json={"kind": "adjustment", "quantity": -1})).status_code == 400
    fixed = await client.post(f"{SUPPLIES}/items/{item['id']}/movements", headers=h,
                              json={"kind": "adjustment", "quantity": -2.5, "reason": "conteo"})
    assert fixed.json()["quantity"] == 8
    ledger = (await client.get(f"{SUPPLIES}/items/{item['id']}/movements", headers=h)).json()
    assert sorted(m["quantity"] for m in ledger) == [-2.5, 0.5, 10]
    assert (await client.post(f"{SUPPLIES}/items/{item['id']}/movements", headers=h,
                              json={"kind": "receipt", "quantity": 1, "unit": "l"})).status_code == 400

    expiring = (await client.get(f"{SUPPLIES}/items?expiring_within_days=3650", headers=h)).json()
    assert [i["id"] for i in expiring] == [item["id"]]
