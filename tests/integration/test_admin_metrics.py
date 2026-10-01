"""Platform admin metrics: only PLATFORM_ADMIN_EMAILS get in, and the aggregates add up (the test database is
shared by the whole run, so global figures are checked as deltas and per-account rows exactly)."""
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

from PIL import Image
from sqlalchemy import text

ADMIN = "/api/v1/admin"
ADMIN_EMAIL = "platform-admin@example.com"  # configured as "Platform-Admin@example.com" in conftest


async def _admin_headers(client):
    login = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "secret-pass-1"})
    if login.status_code != 200:
        signup = await client.post("/api/v1/auth/signup", json={"email": ADMIN_EMAIL, "password": "secret-pass-1"})
        assert signup.status_code == 200, signup.text
        token = signup.json()["access_token"]
    else:
        token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (30, 120, 30)).save(out, format="JPEG")
    return out.getvalue()


async def _insert_chat(container, user, minutes_apart: list[float], tool_calls: list[dict]):
    """A conversation whose user messages are `minutes_apart` from the previous one (agent reply 1 min later)."""
    conversation_id = uuid.uuid4()
    start = datetime.now(timezone.utc) - timedelta(hours=5)
    async with container.db_session_factory()() as session:
        await session.execute(
            text("INSERT INTO conversations (id, account_id, user_id, created_at, updated_at) "
                 "VALUES (:id, :account, :user, :at, :at)"),
            {"id": conversation_id, "account": uuid.UUID(user["account"]["id"]),
             "user": uuid.UUID(user["user"]["id"]), "at": start},
        )
        at = start
        for offset in minutes_apart:
            at = at + timedelta(minutes=offset)
            for role, delta, calls in (("user", 0, []), ("assistant", 1, tool_calls)):
                await session.execute(
                    text("INSERT INTO conversation_messages (id, conversation_id, role, content, sources, tool_calls, "
                         "attachments, created_at) VALUES (:id, :conv, :role, 'x', '[]', CAST(:calls AS jsonb), "
                         "'[]', :at)"),
                    {"id": uuid.uuid4(), "conv": conversation_id, "role": role,
                     "calls": json.dumps(calls), "at": at + timedelta(minutes=delta)},
                )
        await session.commit()


async def test_admin_endpoints_are_hidden_from_regular_users(client, signup):
    user = await signup("notadmin")
    for path in ("/me", "/overview", "/timeseries", "/users", "/accounts"):
        response = await client.get(ADMIN + path, headers=user["headers"])
        assert response.status_code == 404, path
    assert (await client.get(ADMIN + "/overview")).status_code == 401


async def test_admin_identity_is_case_insensitive(client):
    headers = await _admin_headers(client)
    me = await client.get(ADMIN + "/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == ADMIN_EMAIL


async def test_overview_and_listings_reflect_usage(client, container, signup, add_member):
    headers = await _admin_headers(client)
    before = (await client.get(ADMIN + "/overview", headers=headers)).json()

    owner = await signup("metrics")
    staff = await add_member(owner, "staff")
    await add_member(owner, "tecnico")
    h = owner["headers"]

    field = (await client.post("/api/v1/farm-management/fields", headers=h,
                               json={"name": "Huerta", "area_m2": 120, "latitude": -34.9, "longitude": -57.9})).json()
    await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Maceta", "area_m2": 0.5})
    crops = (await client.get("/api/v1/farm-management/crop-masters?q=tomate", headers=h)).json()
    cycle = await client.post("/api/v1/farm-management/crop-cycles", headers=h,
                              json={"field_id": field["id"], "crop_master_id": crops[0]["id"], "status": "growing"})
    assert cycle.status_code == 201, cycle.text
    event = await client.post("/api/v1/farm-management/events", headers=staff["headers"],
                              json={"field_id": field["id"], "type": "irrigation"})
    assert event.status_code == 201, event.text
    upload = await client.post("/api/v1/upload/image", headers=staff["headers"],
                               files={"image_file": ("hoja.jpg", io.BytesIO(_jpeg()), "image/jpeg")})
    assert upload.status_code == 200, upload.text

    # One session of 3 turns spanning 2 + 10 + 1 (last reply) = 13 minutes, then a second one 2 hours later.
    await _insert_chat(container, owner, [0, 2, 10], [{"name": "web_search", "args": {}, "ok": True}])
    await _insert_chat(container, owner, [120], [{"name": "log_event", "args": {}, "ok": False}])

    after = (await client.get(ADMIN + "/overview?days=7", headers=headers)).json()
    assert after["window_days"] == 7
    users_delta = after["users"]["total"] - before["users"]["total"]
    assert users_delta == 3
    roles = {b["key"]: b["count"] for b in after["users"]["by_role"]}
    roles_before = {b["key"]: b["count"] for b in before["users"]["by_role"]}
    assert roles["staff"] - roles_before.get("staff", 0) == 1
    assert roles["tecnico"] - roles_before.get("tecnico", 0) == 1
    assert after["users"]["dau"] >= 2  # owner chatted, staff uploaded and logged an event
    assert after["photos"]["uploads"] - before["photos"]["uploads"] == 1
    assert after["farm"]["fields_total"] - before["farm"]["fields_total"] == 2
    assert after["farm"]["crop_cycles_active"] - before["farm"]["crop_cycles_active"] == 1
    assert after["conversations"]["total"] - before["conversations"]["total"] == 2
    assert after["conversations"]["user_messages"] - before["conversations"]["user_messages"] == 4
    assert after["sessions"]["total"] - before["sessions"]["total"] == 2
    tools = {t["name"]: t for t in after["agent"]["tools"]}
    assert tools["web_search"]["calls"] >= 3 and tools["log_event"]["failed"] >= 1
    buckets = {b["key"]: b["count"] for b in after["farm"]["area_buckets"]}
    assert buckets["< 10 m²"] >= 1 and buckets["50–200 m²"] >= 1
    assert after["system"]["database"] == "ok"

    accounts = (await client.get(ADMIN + "/accounts", headers=headers)).json()
    row = next(a for a in accounts if a["id"] == owner["account"]["id"])
    assert (row["users"], row["owners"], row["tecnicos"], row["staff"]) == (3, 1, 1, 1)
    assert (row["fields"], row["area_m2"], row["crop_cycles_active"]) == (2, 120.5, 1)
    assert (row["photos"], row["conversations"], row["user_messages"], row["events"]) == (1, 2, 4, 1)
    assert row["last_active_at"] is not None

    users = (await client.get(ADMIN + "/users", headers=headers)).json()
    me = next(u for u in users if u["id"] == owner["user"]["id"])
    assert (me["conversations"], me["user_messages"], me["sessions"]) == (2, 4, 2)
    assert me["chat_minutes"] == 14.0  # 13-minute session + a single turn of 1 minute
    assert "password_hash" not in me and "content" not in me
    worker = next(u for u in users if u["id"] == staff["user"]["id"])
    assert (worker["photos"], worker["events"], worker["role"]) == (1, 1, "staff")

    series = (await client.get(ADMIN + "/timeseries?days=14", headers=headers)).json()
    assert len(series["points"]) == 14
    assert sum(p["user_messages"] for p in series["points"]) >= 4
    assert sum(p["signups"] for p in series["points"]) >= 3
