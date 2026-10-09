import uuid


async def _signup(client, **extra):
    email = f"loc-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "secret-pass-1", "first_name": "Ana", **extra}
    )
    return response, email


async def _me(client, response):
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    return headers, me["user"]


async def test_signup_defaults_to_argentina(client):
    response, _ = await _signup(client)
    assert response.status_code == 200, response.text
    _, user = await _me(client, response)
    assert (user["country"], user["timezone"], user["locale"]) == ("AR", "America/Argentina/Buenos_Aires", "es-AR")


async def test_signup_in_mexico_gets_mexican_defaults_and_keeps_an_explicit_timezone(client):
    response, _ = await _signup(client, country="MX")
    _, user = await _me(client, response)
    assert (user["country"], user["timezone"], user["locale"]) == ("MX", "America/Mexico_City", "es-MX")

    response, _ = await _signup(client, country="MX", timezone="America/Tijuana")
    _, user = await _me(client, response)
    assert (user["timezone"], user["locale"]) == ("America/Tijuana", "es-MX")


async def test_signup_rejects_unknown_country_timezone_and_locale(client):
    for extra in ({"country": "ZZ"}, {"timezone": "Mars/Olympus"}, {"locale": "spanish"}):
        response, _ = await _signup(client, **extra)
        assert response.status_code == 422, (extra, response.text)


async def test_patch_me_moves_country_with_its_defaults_and_validates(client):
    response, _ = await _signup(client)
    headers, user = await _me(client, response)

    moved = await client.patch("/api/v1/auth/me", headers=headers, json={"country": "MX"})
    assert moved.status_code == 200, moved.text
    assert (moved.json()["country"], moved.json()["timezone"], moved.json()["locale"]) == (
        "MX", "America/Mexico_City", "es-MX",
    )

    tz_only = await client.patch("/api/v1/auth/me", headers=headers, json={"timezone": "America/Monterrey"})
    assert tz_only.json()["timezone"] == "America/Monterrey" and tz_only.json()["country"] == "MX"

    assert (await client.patch("/api/v1/auth/me", headers=headers, json={"timezone": "nope"})).status_code == 422
    assert (await client.patch("/api/v1/auth/me", json={"country": "AR"})).status_code in (401, 403)
    again = await client.get("/api/v1/auth/me", headers=headers)
    assert again.json()["user"]["timezone"] == "America/Monterrey"


async def test_members_share_the_owners_place_unless_they_say_otherwise(client):
    response, _ = await _signup(client, country="MX", timezone="America/Monterrey")
    headers, owner = await _me(client, response)

    def member(**extra):
        return {"email": f"m-{uuid.uuid4().hex[:8]}@example.com", "password": "secret-pass-1", **extra}

    inherited = await client.post("/api/v1/auth/users", headers=headers, json=member())
    assert inherited.status_code == 201, inherited.text
    assert (inherited.json()["country"], inherited.json()["timezone"], inherited.json()["locale"]) == (
        "MX", "America/Monterrey", "es-MX",
    )

    other = await client.post("/api/v1/auth/users", headers=headers, json=member(country="AR"))
    assert (other.json()["country"], other.json()["timezone"]) == ("AR", "America/Argentina/Buenos_Aires")


async def test_colombia_is_a_served_country_with_its_own_defaults(client):
    response, _ = await _signup(client, country="CO")
    assert response.status_code == 200, response.text
    headers, user = await _me(client, response)
    assert (user["country"], user["timezone"], user["locale"]) == ("CO", "America/Bogota", "es-CO")

    other, _ = await _signup(client)
    other_headers, _ = await _me(client, other)
    moved = await client.patch("/api/v1/auth/me", headers=other_headers, json={"country": "CO"})
    assert moved.status_code == 200, moved.text
    assert (moved.json()["timezone"], moved.json()["locale"]) == ("America/Bogota", "es-CO")
