"""
Seed inventory: lots counted in seeds or weighed in grams, converted with the thousand-seed weight;
adjust (add / subtract / set), edit, duplicates merged on entry or later, tags, search, filters and sort.
"""
FARM = "/api/v1/farm-management"
INV = "/api/v1/inventory/seed-lots"


async def _crop(client, h, q, variety=None):
    crops = (await client.get(f"{FARM}/crop-masters?q={q}", headers=h)).json()
    return next(c for c in crops if variety is None or c["variety"] == variety)


async def _lot(client, h, **body):
    r = await client.post(INV, headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_adjust_in_both_units(client, signup):
    owner = await signup("seeds-adjust")
    h = owner["headers"]
    tomato = await _crop(client, h, "tomate", "Cherry")
    assert tomato["thousand_seed_weight_g"] == 2.0
    lot = await _lot(client, h, crop_master_id=tomato["id"], quantity=10, unit="gr")
    assert lot["unit"] == "gramos" and lot["crop_name"] == "Tomate"
    assert lot["equivalent_unit"] == "semillas" and lot["equivalent_quantity"] == 5000

    # 16 more seeds of a lot weighed in grams: the crop's weight converts them.
    r = (await client.post(f"{INV}/{lot['id']}/adjust", headers=h,
                           json={"op": "add", "amount": 16, "unit": "semillas"})).json()
    assert r["quantity"] == 10.032 and r["applied_amount"] == 0.032

    r = (await client.post(f"{INV}/{lot['id']}/adjust", headers=h,
                           json={"op": "subtract", "amount": 50, "unit": "gramos"})).json()
    assert r["quantity"] == 0 and r["clamped"] is True

    r = (await client.post(f"{INV}/{lot['id']}/adjust", headers=h,
                           json={"op": "set", "amount": 3000, "unit": "semillas",
                                 "thousand_seed_weight_g": 2.5})).json()
    assert r["quantity"] == 7.5 and r["thousand_seed_weight_g"] == 2.5

    # Garlic has no reference weight: crossing units needs one.
    garlic = await _crop(client, h, "ajo")
    lot2 = await _lot(client, h, crop_master_id=garlic["id"], quantity=40)
    r = await client.post(f"{INV}/{lot2['id']}/adjust", headers=h, json={"op": "add", "amount": 5, "unit": "gramos"})
    assert r.status_code == 422 and r.json()["error_code"] == "seed_weight_required"
    r = (await client.post(f"{INV}/{lot2['id']}/consume", headers=h, json={"quantity": 4})).json()
    assert r["quantity"] == 36


async def test_edit_and_change_unit(client, signup):
    owner = await signup("seeds-edit")
    h = owner["headers"]
    lettuce = await _crop(client, h, "lechuga", "Mantecosa")
    lot = await _lot(client, h, crop_master_id=lettuce["id"], quantity=2000, tags=["Prueba"])
    r = (await client.patch(f"{INV}/{lot['id']}", headers=h,
                            json={"unit": "gramos", "source": "INTA", "tags": ["producción", "Hoja"]})).json()
    assert r["unit"] == "gramos" and r["quantity"] == 2.0
    assert r["source"] == "INTA" and r["tags"] == ["producción", "hoja"]

    crespa = await _crop(client, h, "lechuga", "Crespa")
    r = (await client.patch(f"{INV}/{lot['id']}", headers=h, json={"crop_master_id": crespa["id"]})).json()
    assert r["crop_variety"] == "Crespa"


async def test_duplicates_merge_on_entry_and_later(client, signup):
    owner = await signup("seeds-dup")
    h = owner["headers"]
    basil = await _crop(client, h, "albahaca")
    first = await _lot(client, h, crop_master_id=basil["id"], quantity=100, variety_note="Genovesa")

    match = (await client.get(f"{INV}/match?crop_master_id={basil['id']}&variety_note=%20genovesa",
                              headers=h)).json()
    assert match["id"] == first["id"]
    assert (await client.get(f"{INV}/match?crop_master_id={basil['id']}&variety_note=Thai", headers=h)).json() is None

    merged = await _lot(client, h, crop_master_id=basil["id"], quantity=1.5, unit="gramos",
                        variety_note="GENOVESA", tags=["aromáticas"], merge_into_existing=True)
    assert merged["id"] == first["id"] and merged["merged"] is True
    assert merged["quantity"] == 1100 and merged["tags"] == ["aromáticas"]

    apart = await _lot(client, h, crop_master_id=basil["id"], quantity=20, variety_note="Genovesa",
                       expiry_date="2027-01-01", tags=["prueba"])
    assert apart["duplicate_of"] == first["id"] and apart["merged"] is False

    r = await client.post(f"{INV}/merge", headers=h, json={"target_id": first["id"], "source_ids": [apart["id"]]})
    assert r.status_code == 200, r.text
    r = r.json()
    assert r["quantity"] == 1120 and r["expiry_date"] == "2027-01-01"
    assert sorted(r["tags"]) == ["aromáticas", "prueba"]
    lots = (await client.get(INV, headers=h)).json()
    assert [lot["id"] for lot in lots] == [first["id"]]


async def test_tags_search_filters_and_sort(client, signup):
    owner = await signup("seeds-list")
    h = owner["headers"]
    tomato = await _crop(client, h, "tomate", "Redondo")
    carrot = await _crop(client, h, "zanahoria")
    pumpkin = await _crop(client, h, "zapallo")
    a = await _lot(client, h, crop_master_id=tomato["id"], quantity=50, variety_note="Platense", source="Vivero Sur")
    b = await _lot(client, h, crop_master_id=carrot["id"], quantity=1, unit="gramos")  # ≈ 833 seeds
    c = await _lot(client, h, crop_master_id=pumpkin["id"], quantity=10)
    await client.post(f"{INV}/{c['id']}/adjust", headers=h, json={"op": "set", "amount": 0})

    r = (await client.post(f"{INV}/tags", headers=h,
                           json={"lot_ids": [a["id"], b["id"]], "add": ["Huerta", "producción"]})).json()
    assert all("huerta" in lot["tags"] for lot in r)
    await client.post(f"{INV}/tags", headers=h, json={"lot_ids": [b["id"]], "remove": ["producción"]})
    tags = (await client.get(f"{INV}/tags", headers=h)).json()
    assert tags == [{"tag": "huerta", "count": 2}, {"tag": "producción", "count": 1}]

    ids = lambda r: [lot["id"] for lot in r.json()]  # noqa: E731
    assert ids(await client.get(f"{INV}?q=platense", headers=h)) == [a["id"]]
    assert ids(await client.get(f"{INV}?q=vivero", headers=h)) == [a["id"]]
    assert ids(await client.get(f"{INV}?q=apiaceae", headers=h)) == [b["id"]]
    assert ids(await client.get(f"{INV}?q=producc", headers=h)) == [a["id"]]
    assert ids(await client.get(f"{INV}?tags=huerta&tags=producción", headers=h)) == [a["id"]]
    assert ids(await client.get(f"{INV}?in_stock=false", headers=h)) == [c["id"]]
    assert set(ids(await client.get(f"{INV}?in_stock=true", headers=h))) == {a["id"], b["id"]}
    assert ids(await client.get(f"{INV}?sort=quantity", headers=h)) == [b["id"], a["id"], c["id"]]
    assert ids(await client.get(f"{INV}?sort=recent", headers=h))[0] == c["id"]
    assert ids(await client.get(f"{INV}?sort=name", headers=h)) == [a["id"], b["id"], c["id"]]


async def test_permissions_and_isolation(client, signup, add_member):
    owner = await signup("seeds-perm")
    staff = await add_member(owner, "staff")
    other = await signup("seeds-other")
    crop = await _crop(client, owner["headers"], "rabanito")
    lot = await _lot(client, owner["headers"], crop_master_id=crop["id"], quantity=100)

    sh = staff["headers"]
    assert (await client.post(f"{INV}/{lot['id']}/adjust", headers=sh,
                              json={"op": "subtract", "amount": 10})).status_code == 200
    assert (await client.post(f"{INV}/{lot['id']}/adjust", headers=sh,
                              json={"op": "add", "amount": 10})).status_code == 403
    assert (await client.patch(f"{INV}/{lot['id']}", headers=sh, json={"notes": "x"})).status_code == 403

    oh = other["headers"]
    assert (await client.get(f"{INV}/{lot['id']}", headers=oh)).status_code == 404
    assert (await client.post(f"{INV}/{lot['id']}/adjust", headers=oh,
                              json={"op": "subtract", "amount": 1})).status_code == 404
    assert (await client.post(f"{INV}/tags", headers=oh,
                              json={"lot_ids": [lot["id"]], "add": ["mío"]})).status_code == 404
    mine = await _lot(client, oh, crop_master_id=crop["id"], quantity=5)
    assert (await client.post(f"{INV}/merge", headers=oh,
                              json={"target_id": mine["id"], "source_ids": [lot["id"]]})).status_code == 404
