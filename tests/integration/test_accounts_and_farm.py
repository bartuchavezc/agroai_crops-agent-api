"""Accounts with roles, farm CRUD, account isolation and role permissions."""
from uuid import UUID

from src.shared.domain.actor import Actor


async def test_signup_disabled_returns_403(client, container):
    auth_service = container.auth.auth_service()
    original = auth_service.allow_public_signup
    auth_service.allow_public_signup = False
    try:
        response = await client.post(
            "/api/v1/auth/signup",
            json={"email": "blocked@example.com", "password": "secret-pass-1", "first_name": "X"},
        )
        assert response.status_code == 403
    finally:
        auth_service.allow_public_signup = original


async def test_signup_makes_owner_and_owner_adds_members(client, signup, add_member):
    owner = await signup("owner")
    assert owner["user"]["role"] == "owner"

    staff = await add_member(owner, role="staff")
    tecnico = await add_member(owner, role="tecnico")
    assert staff["account"]["id"] == owner["account"]["id"] == tecnico["account"]["id"]

    members = (await client.get("/api/v1/auth/users", headers=owner["headers"])).json()
    assert {m["role"] for m in members} == {"owner", "staff", "tecnico"}

    forbidden = await client.post(
        "/api/v1/auth/users",
        headers=staff["headers"],
        json={"email": "x-staff@example.com", "password": "secret-pass-1", "role": "staff"},
    )
    assert forbidden.status_code == 403


async def test_users_of_other_accounts_are_invisible(client, signup):
    a = await signup("a")
    b = await signup("b")
    response = await client.get(f"/api/v1/auth/users/{b['user']['id']}", headers=a["headers"])
    assert response.status_code == 404


async def test_farm_flow_and_trailing_slashes(client, signup):
    owner = await signup("farm")
    h = owner["headers"]

    field = await client.post(
        "/api/v1/farm-management/fields/",
        headers=h,
        json={"name": "Cantero 1", "city": "La Plata", "latitude": -34.92, "longitude": -57.95, "area_m2": 12},
    )
    assert field.status_code == 201, field.text
    field_id = field.json()["id"]

    duplicate = await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Cantero 1"})
    assert duplicate.status_code == 400

    crops = (await client.get("/api/v1/farm-management/crop-masters?q=tomate", headers=h)).json()
    cherry = next(c for c in crops if c["variety"] == "Cherry")
    assert cherry["account_id"] is None  # global catalog seeded by the migration

    cycle = await client.post(
        "/api/v1/farm-management/crop-cycles",
        headers=h,
        json={"field_id": field_id, "crop_master_id": cherry["id"], "status": "planted", "planting_date": "2026-09-20"},
    )
    assert cycle.status_code == 201, cycle.text

    event = await client.post(
        "/api/v1/farm-management/events",
        headers=h,
        json={"field_id": field_id, "type": "irrigation", "quantity": 10, "unit": "litros"},
    )
    assert event.status_code == 201, event.text
    assert event.json()["source"] == "user"

    overview = (await client.get("/api/v1/farm-management/overview", headers=h)).json()
    assert overview[0]["active_cycles"][0]["crop_name"] == "Tomate"
    assert overview[0]["last_event_at"] is not None


async def test_account_isolation(client, signup):
    a = await signup("iso-a")
    b = await signup("iso-b")
    field = (await client.post("/api/v1/farm-management/fields", headers=a["headers"], json={"name": "Huerta"})).json()

    assert (await client.get(f"/api/v1/farm-management/fields/{field['id']}", headers=b["headers"])).status_code == 404
    assert (await client.get("/api/v1/farm-management/fields", headers=b["headers"])).json() == []
    event = await client.post(
        "/api/v1/farm-management/events",
        headers=b["headers"],
        json={"field_id": field["id"], "type": "observation"},
    )
    assert event.status_code == 404


async def test_staff_can_log_events_but_not_manage(client, signup, add_member):
    owner = await signup("perm")
    staff = await add_member(owner, "staff")
    field = (
        await client.post("/api/v1/farm-management/fields", headers=owner["headers"], json={"name": "Maceta"})
    ).json()

    denied = await client.post("/api/v1/farm-management/fields", headers=staff["headers"], json={"name": "Otra"})
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "permission_denied"

    event = await client.post(
        "/api/v1/farm-management/events",
        headers=staff["headers"],
        json={"field_id": field["id"], "type": "pest_sighting", "notes": "pulgón en hojas"},
    )
    assert event.status_code == 201

    owner_event = await client.post(
        "/api/v1/farm-management/events",
        headers=owner["headers"],
        json={"field_id": field["id"], "type": "irrigation"},
    )
    edit = await client.put(
        f"/api/v1/farm-management/events/{owner_event.json()['id']}",
        headers=staff["headers"],
        json={"notes": "edit"},
    )
    assert edit.status_code == 403


async def test_endpoints_require_auth(client):
    for path in ("/api/v1/farm-management/fields", "/api/v1/reports", "/api/v1/alerts", "/api/v1/chat/conversations"):
        assert (await client.get(path)).status_code == 401


async def test_uploaded_images_are_account_scoped(client, signup):
    import base64

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    a = await signup("img-a")
    b = await signup("img-b")
    up = await client.post(
        "/api/v1/upload/image", headers=a["headers"], files={"image_file": ("hoja.png", png, "image/png")}
    )
    assert up.status_code == 200, up.text
    identifier = up.json()["image_identifier"]
    own = await client.get(f"/api/v1/upload/image/{identifier}", headers=a["headers"])
    # stored normalized: JPEG, same pixels size (see application/storage/images.py)
    assert own.status_code == 200 and own.headers["content-type"] == "image/jpeg"
    assert own.content.startswith(b"\xff\xd8\xff")
    assert (await client.get(f"/api/v1/upload/image/{identifier}", headers=b["headers"])).status_code == 404
    traversal = await client.get("/api/v1/upload/image/..%2F..%2Fetc%2Fpasswd", headers=a["headers"])
    assert traversal.status_code in (400, 404)


async def test_field_soft_delete_frees_the_name_and_hides_history(client, signup):
    owner = await signup("softdel")
    h = owner["headers"]
    field = (await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Cantero X"})).json()
    await client.post(
        "/api/v1/farm-management/events", headers=h, json={"field_id": field["id"], "type": "irrigation"}
    )

    deleted = await client.delete(f"/api/v1/farm-management/fields/{field['id']}", headers=h)
    assert deleted.status_code == 204

    assert (await client.get(f"/api/v1/farm-management/fields/{field['id']}", headers=h)).status_code == 404
    assert (await client.get("/api/v1/farm-management/fields", headers=h)).json() == []
    # deleting an already-deleted field is a 404, not a silent no-op
    assert (await client.delete(f"/api/v1/farm-management/fields/{field['id']}", headers=h)).status_code == 404

    # the name is free again for a brand new field
    recreated = await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Cantero X"})
    assert recreated.status_code == 201
    assert recreated.json()["id"] != field["id"]


async def test_crop_cycle_soft_delete(client, signup):
    owner = await signup("softdel-cycle")
    h = owner["headers"]
    field = (await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Cantero Y"})).json()
    crops = (await client.get("/api/v1/farm-management/crop-masters?q=tomate", headers=h)).json()
    cycle = await client.post(
        "/api/v1/farm-management/crop-cycles",
        headers=h,
        json={"field_id": field["id"], "crop_master_id": crops[0]["id"], "status": "planted"},
    )
    cycle_id = cycle.json()["id"]

    assert (await client.delete(f"/api/v1/farm-management/crop-cycles/{cycle_id}", headers=h)).status_code == 204
    assert (await client.get("/api/v1/farm-management/crop-cycles", headers=h)).json() == []
    overview = (await client.get("/api/v1/farm-management/overview", headers=h)).json()
    assert overview[0]["active_cycles"] == []


async def test_webp_upload_is_accepted(client, signup):
    from PIL import Image
    import io

    user = await signup("webp")
    img = Image.new("RGB", (10, 10), color="green")
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    up = await client.post(
        "/api/v1/upload/image",
        headers=user["headers"],
        files={"image_file": ("hoja.webp", buf.getvalue(), "image/webp")},
    )
    assert up.status_code == 200, up.text
    identifier = up.json()["image_identifier"]
    got = await client.get(f"/api/v1/upload/image/{identifier}", headers=user["headers"])
    assert got.status_code == 200 and Image.open(io.BytesIO(got.content)).size == (10, 10)


_TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def test_periodic_upload_requires_crop_cycle_id(client, signup):
    import base64

    user = await signup("periodic-missing-cycle")
    field = (
        await client.post("/api/v1/farm-management/fields", headers=user["headers"], json={"name": "Cantero"})
    ).json()
    up = await client.post(
        "/api/v1/upload/image",
        headers=user["headers"],
        data={"field_id": field["id"], "report_type": "periodic"},
        files={"image_file": ("hoja.png", base64.b64decode(_TINY_PNG), "image/png")},
    )
    assert up.status_code == 422


async def test_periodic_upload_rejects_unknown_report_type(client, signup):
    import base64

    user = await signup("periodic-bad-type")
    up = await client.post(
        "/api/v1/upload/image",
        headers=user["headers"],
        data={"report_type": "something-else"},
        files={"image_file": ("hoja.png", base64.b64decode(_TINY_PNG), "image/png")},
    )
    assert up.status_code == 400


async def test_periodic_upload_responds_immediately_and_creates_the_report(client, signup):
    import base64

    user = await signup("periodic-ok")
    h = user["headers"]
    field = (await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Cantero"})).json()
    crops = (await client.get("/api/v1/farm-management/crop-masters?q=tomate", headers=h)).json()
    cycle = (
        await client.post(
            "/api/v1/farm-management/crop-cycles",
            headers=h,
            json={"field_id": field["id"], "crop_master_id": crops[0]["id"], "status": "planted"},
        )
    ).json()

    up = await client.post(
        "/api/v1/upload/image",
        headers=h,
        data={"field_id": field["id"], "crop_cycle_id": cycle["id"], "report_type": "periodic"},
        files={"image_file": ("hoja.png", base64.b64decode(_TINY_PNG), "image/png")},
    )
    # The upload itself must respond immediately with a well-formed report, whatever the background
    # analysis ends up doing (it isn't awaited before responding).
    assert up.status_code == 200, up.text
    report = (await client.get(f"/api/v1/reports/{up.json()['report_id']}", headers=h)).json()
    assert report["report_type"] == "periodic"
    assert report["crop_cycle_id"] == cycle["id"]
    assert report["status"] in ("PENDING_ANALYSIS", "ANALYSIS_FAILED", "ANALYSIS_COMPLETED")


async def test_periodic_upload_marks_failed_when_background_analysis_errors(client, signup):
    """No Gemini key configured for this user: the background analysis fails, and instead of leaving
    the report stuck at PENDING_ANALYSIS forever, it's marked ANALYSIS_FAILED so the UI can offer a
    "Reintentar" button (plain POST /analyze — no batch/cron job involved)."""
    import base64

    user = await signup("periodic-fails")
    h = user["headers"]
    field = (await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Cantero"})).json()
    crops = (await client.get("/api/v1/farm-management/crop-masters?q=tomate", headers=h)).json()
    cycle = (
        await client.post(
            "/api/v1/farm-management/crop-cycles",
            headers=h,
            json={"field_id": field["id"], "crop_master_id": crops[0]["id"], "status": "planted"},
        )
    ).json()

    up = await client.post(
        "/api/v1/upload/image",
        headers=h,
        data={"field_id": field["id"], "crop_cycle_id": cycle["id"], "report_type": "periodic"},
        files={"image_file": ("hoja.png", base64.b64decode(_TINY_PNG), "image/png")},
    )
    report_id = up.json()["report_id"]
    report = (await client.get(f"/api/v1/reports/{report_id}", headers=h)).json()
    assert report["status"] == "ANALYSIS_FAILED"

    # The manual retry path (same endpoint the "Reintentar" button calls) is reachable regardless of
    # the report's current status; it fails again for the same reason (no key), not because it's blocked.
    retry = await client.post("/api/v1/analyze", headers=h, json={"report_id": report_id})
    assert retry.status_code == 409
    assert retry.json()["error_code"] == "PROVIDER_KEY_MISSING"


async def test_manual_diagnosis_failure_is_also_persisted(client, signup):
    """The same failure-marking applies to the manual "Analizar con el agente" flow (diagnosis reports,
    uploaded without a crop_cycle_id): a failed attempt must not leave the report silently PENDING_ANALYSIS
    forever if the user misses the error toast — it becomes ANALYSIS_FAILED, visible and retryable."""
    import base64

    user = await signup("diagnosis-fails")
    h = user["headers"]
    up = await client.post(
        "/api/v1/upload/image",
        headers=h,
        files={"image_file": ("hoja.png", base64.b64decode(_TINY_PNG), "image/png")},
    )
    report_id = up.json()["report_id"]

    analyze = await client.post("/api/v1/analyze", headers=h, json={"report_id": report_id})
    assert analyze.status_code == 409
    assert analyze.json()["error_code"] == "PROVIDER_KEY_MISSING"

    report = (await client.get(f"/api/v1/reports/{report_id}", headers=h)).json()
    assert report["status"] == "ANALYSIS_FAILED"


async def test_reports_filter_by_crop_cycle_and_type(client, signup):
    user = await signup("reports-filter")
    h = user["headers"]
    field = (await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Cantero"})).json()
    crops = (await client.get("/api/v1/farm-management/crop-masters?q=tomate", headers=h)).json()
    cycle_a = (
        await client.post(
            "/api/v1/farm-management/crop-cycles",
            headers=h,
            json={"field_id": field["id"], "crop_master_id": crops[0]["id"], "status": "planted"},
        )
    ).json()
    cycle_b = (
        await client.post(
            "/api/v1/farm-management/crop-cycles",
            headers=h,
            json={"field_id": field["id"], "crop_master_id": crops[0]["id"], "status": "planted"},
        )
    ).json()

    r1 = (
        await client.post(
            "/api/v1/reports",
            headers=h,
            json={"field_id": field["id"], "crop_cycle_id": cycle_a["id"], "report_type": "periodic"},
        )
    ).json()
    await client.post(
        "/api/v1/reports",
        headers=h,
        json={"field_id": field["id"], "crop_cycle_id": cycle_b["id"], "report_type": "diagnosis"},
    )

    only_a = (await client.get(f"/api/v1/reports?crop_cycle_id={cycle_a['id']}", headers=h)).json()
    assert [r["id"] for r in only_a] == [r1["id"]]

    only_periodic = (await client.get("/api/v1/reports?report_type=periodic", headers=h)).json()
    assert [r["id"] for r in only_periodic] == [r1["id"]]


async def test_get_event_endpoint(client, signup):
    user = await signup("event-detail")
    h = user["headers"]
    field = (await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Cantero"})).json()
    event = (
        await client.post(
            "/api/v1/farm-management/events",
            headers=h,
            json={"field_id": field["id"], "type": "irrigation", "quantity": 5, "unit": "litros"},
        )
    ).json()

    got = await client.get(f"/api/v1/farm-management/events/{event['id']}", headers=h)
    assert got.status_code == 200 and got.json()["id"] == event["id"]

    other = await signup("event-detail-other")
    assert (
        await client.get(f"/api/v1/farm-management/events/{event['id']}", headers=other["headers"])
    ).status_code == 404


async def test_catalog_names_by_locale_find_the_crop_by_either_name(client, signup, container):
    owner = await signup("catalogo-i18n")
    h = owner["headers"]
    CROPS = "/api/v1/farm-management/crop-masters"
    listed = (await client.get(f"{CROPS}?q=tomate", headers=h)).json()
    tomato = [c for c in listed if c["name"] == "Tomate"]
    assert tomato and tomato[0]["i18n"]["es-MX"] == "Jitomate"  # seeded for the global catalog

    by_alias = await client.get(f"{CROPS}?q=jitomate", headers=h)
    assert {c["name"] for c in by_alias.json()} == {"Tomate"}
    by_ahuyama = await client.get(f"{CROPS}?q=ahuyama", headers=h)
    assert {c["name"] for c in by_ahuyama.json()} == {"Zapallo"}

    # exact lookup (what the agent uses to start a cycle): "jitomate" is the global Tomate, not a new crop
    actor = Actor(UUID(owner["user"]["id"]), UUID(owner["account"]["id"]), "owner")
    found = await container.application.farm_service().find_crop_masters(actor, "jitomate")
    assert found and found[0].name == "Tomate"

    created = await client.post(
        CROPS, headers=h, json={"name": "Quinoa", "i18n": {"es-CO": "Quinua"}}
    )
    assert created.status_code == 201, created.text
    assert created.json()["i18n"] == {"es-CO": "Quinua"} and created.json()["variety_i18n"] == {}
    by_quinua = await client.get(f"{CROPS}?q=quinua", headers=h)
    assert {c["name"] for c in by_quinua.json()} == {"Quinoa"}
