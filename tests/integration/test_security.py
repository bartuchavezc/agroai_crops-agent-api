"""Security hardening: login, token revocation, member removal, cross-account references,
role checks on deletes, BYOK ciphertext binding."""
import io
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
import pytest
from sqlalchemy import text

from src.shared.domain.actor import Actor

LOGIN = "/api/v1/auth/login"


def _actor(user) -> Actor:
    u = user["user"]
    return Actor(UUID(u["id"]), UUID(u["account_id"]), u["role"])


async def _field(client, owner, name="Cantero"):
    response = await client.post(
        "/api/v1/farm-management/fields", headers=owner["headers"], json={"name": f"{name}-{uuid.uuid4().hex[:6]}"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---------- login ----------

async def test_email_is_case_insensitive(client, signup):
    user = await signup("Case")
    login = await client.post(LOGIN, json={"email": user["email"].upper(), "password": "secret-pass-1"})
    assert login.status_code == 200
    duplicate = await client.post(
        "/api/v1/auth/signup", json={"email": user["email"].upper(), "password": "secret-pass-1"}
    )
    assert duplicate.status_code == 400
    assert user["user"]["email"] == user["email"].lower()


async def test_password_longer_than_bcrypt_limit_is_rejected(client):
    response = await client.post(
        "/api/v1/auth/signup", json={"email": f"long-{uuid.uuid4().hex[:6]}@example.com", "password": "ñ" * 40}
    )
    assert response.status_code == 422


# ---------- token revocation ----------

async def test_password_change_revokes_old_tokens_and_returns_a_new_one(client, signup):
    user = await signup("pwd")
    old = user["headers"]
    response = await client.post(
        "/api/v1/auth/password", headers=old, json={"current_password": "secret-pass-1", "new_password": "new-pass-22"}
    )
    assert response.status_code == 200, response.text
    new = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert (await client.get("/api/v1/auth/me", headers=old)).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=new)).status_code == 200
    assert (await client.post(LOGIN, json={"email": user["email"], "password": "new-pass-22"})).status_code == 200


async def test_tokens_issued_before_token_versioning_still_work(client, signup, container):
    user = await signup("legacy-token")
    auth = container.auth.auth_service()
    legacy = jwt.encode(
        {"sub": user["user"]["id"], "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        auth.secret_key,
        algorithm=auth.algorithm,
    )
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {legacy}"})).status_code == 200


async def test_owner_removes_member(client, signup, add_member):
    owner = await signup("remover")
    staff = await add_member(owner, role="staff")
    tecnico = await add_member(owner, role="tecnico")
    staff_id = staff["user"]["id"]

    forbidden = await client.delete(f"/api/v1/auth/users/{staff_id}", headers=tecnico["headers"])
    assert forbidden.status_code == 403
    own = await client.delete(f"/api/v1/auth/users/{owner['user']['id']}", headers=owner["headers"])
    assert own.status_code == 400

    assert (await client.delete(f"/api/v1/auth/users/{staff_id}", headers=owner["headers"])).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=staff["headers"])).status_code == 401
    assert (await client.post(LOGIN, json={"email": staff["email"], "password": "secret-pass-1"})).status_code == 401
    members = (await client.get("/api/v1/auth/users", headers=owner["headers"])).json()
    assert staff_id not in {m["id"] for m in members}
    assert (await client.get(f"/api/v1/auth/users/{staff_id}", headers=owner["headers"])).status_code == 404
    assert (await client.delete(f"/api/v1/auth/users/{staff_id}", headers=owner["headers"])).status_code == 404


async def test_owner_cannot_remove_members_of_other_accounts(client, signup, add_member):
    a = await signup("acc-a")
    b = await signup("acc-b")
    b_staff = await add_member(b, role="staff")
    response = await client.delete(f"/api/v1/auth/users/{b_staff['user']['id']}", headers=a["headers"])
    assert response.status_code == 404
    assert (await client.get("/api/v1/auth/me", headers=b_staff["headers"])).status_code == 200


# ---------- cross-account references ----------

async def test_field_ids_of_other_accounts_are_rejected(client, signup):
    a = await signup("ref-a")
    b = await signup("ref-b")
    foreign = await _field(client, b)
    h = a["headers"]

    requests = [
        ("/api/v1/management/shopping-list", {"name": "Guano", "field_id": foreign}),
        (
            "/api/v1/management/budget",
            {"type": "gasto", "amount": 10, "description": "x", "date": "2026-10-01", "field_id": foreign},
        ),
        ("/api/v1/management/roadmap", {"title": "Podar", "field_id": foreign}),
        ("/api/v1/alerts", {"title": "Helada", "message": "x", "field_id": foreign}),
        ("/api/v1/chat/conversations", {"field_id": foreign}),
    ]
    for path, body in requests:
        response = await client.post(path, headers=h, json=body)
        assert response.status_code == 404, (path, response.status_code, response.text)

    own = await _field(client, a)
    conversation = await client.post("/api/v1/chat/conversations", headers=h, json={"field_id": own})
    assert conversation.status_code == 201
    patched = await client.patch(
        f"/api/v1/chat/conversations/{conversation.json()['id']}", headers=h, json={"field_id": foreign}
    )
    assert patched.status_code == 404
    shopping = await client.post("/api/v1/management/shopping-list", headers=h, json={"name": "x", "field_id": own})
    assert shopping.status_code == 201


# ---------- role checks on deletes ----------

async def test_staff_can_only_delete_their_own_reports(client, signup, add_member):
    owner = await signup("rep-owner")
    staff = await add_member(owner, role="staff")
    owners_report = (await client.post("/api/v1/reports", headers=owner["headers"], json={})).json()["id"]
    staffs_report = (await client.post("/api/v1/reports", headers=staff["headers"], json={})).json()["id"]

    assert (await client.delete(f"/api/v1/reports/{owners_report}", headers=staff["headers"])).status_code == 403
    assert (await client.delete(f"/api/v1/reports/{staffs_report}", headers=staff["headers"])).status_code == 204
    assert (await client.delete(f"/api/v1/reports/{owners_report}", headers=owner["headers"])).status_code == 204


async def test_staff_acknowledges_but_cannot_delete_alerts(client, signup, add_member):
    owner = await signup("alert-owner")
    staff = await add_member(owner, role="staff")
    alert = (await client.post("/api/v1/alerts", headers=owner["headers"], json={"title": "t", "message": "m"})).json()
    path = f"/api/v1/alerts/{alert['id']}"
    assert (await client.put(f"{path}/acknowledge", headers=staff["headers"])).status_code == 200
    assert (await client.delete(path, headers=staff["headers"])).status_code == 403
    assert (await client.delete(path, headers=owner["headers"])).status_code == 204


async def test_staff_can_only_forget_their_own_memories(client, signup, add_member, container):
    memory = container.agent.memory_service()
    owner = await signup("mem-owner")
    staff = await add_member(owner, role="staff")
    owners = await memory.remember(_actor(owner), "El tomate del fondo se riega a mano")
    staffs = await memory.remember(_actor(staff), "La manguera nueva está en el galpón")

    assert (await client.delete(f"/api/v1/agent/memories/{owners.id}", headers=staff["headers"])).status_code == 403
    assert (await client.delete(f"/api/v1/agent/memories/{staffs.id}", headers=staff["headers"])).status_code == 204
    assert (await client.delete(f"/api/v1/agent/memories/{owners.id}", headers=owner["headers"])).status_code == 204


async def test_staff_layout_photo_is_rejected_before_storing_it(client, signup, add_member, container):
    owner = await signup("layout-owner")
    staff = await add_member(owner, role="staff")
    field_id = await _field(client, owner)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    response = await client.post(
        f"/api/v1/farm-management/fields/{field_id}/layout/photos",
        headers=staff["headers"],
        files={"image_file": ("p.png", io.BytesIO(png), "image/png")},
        data={"camera_bearing_degrees": "90", "entorno_ancho_m": "5", "entorno_largo_m": "5"},
    )
    assert response.status_code == 403
    base = container.application.file_repository().base_path / owner["account"]["id"]
    assert not base.exists() or not any(base.iterdir())


# ---------- BYOK ----------

async def test_byok_ciphertext_is_bound_to_its_user_and_legacy_rows_are_upgraded(signup, container):
    credentials = container.agent.credentials_service()
    box = container.agent.secret_box()
    a = await signup("box-a")
    b = await signup("box-b")
    a_id, b_id = UUID(a["user"]["id"]), UUID(b["user"]["id"])

    # a row written before ciphertexts were bound to their user (plain Fernet under the master key)
    await credentials.repo.upsert(a_id, "gemini", box.encrypt("AIzaLEGACY-key-0123456789abcdef"), "cdef")
    assert await credentials.get_api_key(a_id) == "AIzaLEGACY-key-0123456789abcdef"
    upgraded = (await credentials.repo.get(a_id, "gemini")).api_key_ciphertext
    assert not box.is_legacy(upgraded)

    # copying a's ciphertext onto b's row does not give b a's key
    await credentials.repo.upsert(b_id, "gemini", upgraded, "cdef")
    with pytest.raises(ValueError):
        await credentials.get_api_key(b_id)

    async with container.db_session_factory()() as session:
        await session.execute(
            text("DELETE FROM provider_credentials WHERE user_id IN (:a, :b)"), {"a": a_id, "b": b_id}
        )
        await session.commit()
