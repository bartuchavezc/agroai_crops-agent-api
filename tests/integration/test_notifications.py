"""In-app notifications: fan-out to every account member except the one who triggered it."""


async def test_event_notifies_other_members_not_the_actor(client, signup, add_member):
    owner = await signup("notif-owner")
    staff = await add_member(owner, role="staff")
    h = owner["headers"]
    field = (await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Cantero"})).json()

    await client.post(
        "/api/v1/farm-management/events",
        headers=h,
        json={"field_id": field["id"], "type": "irrigation", "quantity": 5, "unit": "litros"},
    )

    owner_unread = (await client.get("/api/v1/notifications/unread-count", headers=h)).json()
    assert owner_unread["count"] == 0

    staff_unread = (await client.get("/api/v1/notifications/unread-count", headers=staff["headers"])).json()
    assert staff_unread["count"] == 1

    notifications = (await client.get("/api/v1/notifications", headers=staff["headers"])).json()
    assert len(notifications) == 1
    assert notifications[0]["type"] == "event"
    assert notifications[0]["entity_type"] == "event"
    assert notifications[0]["read"] is False


async def test_mark_read_and_mark_all_read(client, signup, add_member):
    owner = await signup("notif-read-owner")
    staff = await add_member(owner, role="staff")
    h = owner["headers"]
    field = (await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Cantero"})).json()
    for _ in range(2):
        await client.post(
            "/api/v1/farm-management/events", headers=h, json={"field_id": field["id"], "type": "observation"}
        )

    notifications = (await client.get("/api/v1/notifications", headers=staff["headers"])).json()
    assert len(notifications) == 2

    await client.put(f"/api/v1/notifications/{notifications[0]['id']}/read", headers=staff["headers"])
    unread = (await client.get("/api/v1/notifications/unread-count", headers=staff["headers"])).json()
    assert unread["count"] == 1

    await client.put("/api/v1/notifications/read-all", headers=staff["headers"])
    unread = (await client.get("/api/v1/notifications/unread-count", headers=staff["headers"])).json()
    assert unread["count"] == 0


async def test_mark_read_unknown_notification_is_404(client, signup):
    import uuid

    user = await signup("notif-404")
    response = await client.put(f"/api/v1/notifications/{uuid.uuid4()}/read", headers=user["headers"])
    assert response.status_code == 404


async def test_notifications_are_scoped_to_own_account(client, signup):
    a = await signup("notif-a")
    b = await signup("notif-b")
    field = (
        await client.post("/api/v1/farm-management/fields", headers=a["headers"], json={"name": "Cantero"})
    ).json()
    await client.post(
        "/api/v1/farm-management/events", headers=a["headers"], json={"field_id": field["id"], "type": "observation"}
    )
    assert (await client.get("/api/v1/notifications", headers=b["headers"])).json() == []


async def test_solo_account_gets_no_self_notification(client, signup):
    user = await signup("notif-solo")
    h = user["headers"]
    field = (await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Cantero"})).json()
    await client.post(
        "/api/v1/farm-management/events", headers=h, json={"field_id": field["id"], "type": "observation"}
    )
    unread = (await client.get("/api/v1/notifications/unread-count", headers=h)).json()
    assert unread["count"] == 0
