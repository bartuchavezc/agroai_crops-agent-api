"""
The assistant comes to the person: a voice message becomes a transcribed turn kept with its audio, rain is logged
by the system, the evening summary tells facts and gaps, and the proactive check decides — with the person's limits
applied after — whether to write first, in a conversation the push opens.
"""
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.digests import DigestWriting
from src.agent.nudges import NudgeDecision, NudgeMessage, Signal
from src.application.proactive.push import in_quiet_hours
from src.shared.domain.actor import Actor

from .test_agent_chat import scripted_model, with_key  # noqa: F401 - fixtures

FARM = "/api/v1/farm-management"
WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 64  # a WebM header is all the upload checks


async def _field_with_lot(client, h, name="Quinta"):
    field = (await client.post(f"{FARM}/fields", headers=h, json={"name": name, "latitude": -34.6,
                                                                   "longitude": -58.4})).json()
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    crop = (await client.get(f"{FARM}/crop-masters?q=lechuga", headers=h)).json()[0]["id"]
    lot = (await client.post(f"{FARM}/lots", headers=h, json={
        "field_id": field["id"], "crop_master_id": crop, "zone_ids": [zone["id"]], "status": "planted",
    })).json()
    return field, zone, lot


def test_quiet_hours_cross_midnight():
    at = datetime(2026, 10, 23, 23, 0)
    assert in_quiet_hours(at, "21:00", "07:30")
    assert in_quiet_hours(at.replace(hour=6), "21:00", "07:30")
    assert not in_quiet_hours(at.replace(hour=12), "21:00", "07:30")
    assert in_quiet_hours(at.replace(hour=13), "12:00", "14:00")


async def test_a_voice_message_is_transcribed_into_the_turn_and_kept_as_evidence(
    client, signup, with_key, scripted_model, container  # noqa: F811
):
    user = await signup("voice")
    await with_key(user)
    h = user["headers"]
    await _field_with_lot(client, h)
    bad = await client.post("/api/v1/upload/audio", headers=h, files={"audio_file": ("x.webm", b"hello", "audio/webm")})
    assert bad.status_code == 415
    up = await client.post("/api/v1/upload/audio", headers=h, files={"audio_file": ("nota.webm", WEBM, "audio/webm")})
    assert up.status_code == 200, up.text
    audio_id = up.json()["audio_identifier"]
    assert (await client.get(f"/api/v1/upload/audio/{audio_id}", headers=h)).content == WEBM

    gateway = container.agent.gemini()
    scripted_model.script = [
        ("call", "log_events", {"entries": [
            {"type": "irrigation", "zone": "cantero 1", "outcome": "skipped", "reason": "la tierra seguía húmeda"},
        ]}),
        ("text", "Anotado: hoy no se regó el Cantero 1 porque la tierra seguía húmeda."),
    ]
    with patch.object(gateway, "transcribe", AsyncMock(return_value="Hoy no regué el cantero uno, seguía húmedo")):
        r = await client.post("/api/v1/chat", headers=h, json={"audio_identifier": audio_id})
    assert r.status_code == 200, r.text
    turn_text = str(scripted_model.requests[0].contents[-1].parts)
    assert "Hoy no regué el cantero uno" in turn_text and "transcripción automática" in turn_text
    conversation_id = r.json()["metadata"]["conversation_id"]
    messages = (await client.get(f"/api/v1/chat/conversations/{conversation_id}/messages", headers=h)).json()
    assert (messages[0]["content"], messages[0]["audio_identifier"]) == (
        "Hoy no regué el cantero uno, seguía húmedo", audio_id
    )
    assert (await client.post("/api/v1/chat", headers=h, json={"message": "  "})).status_code == 422


async def test_rain_is_logged_once_per_day_and_the_summary_tells_facts_and_gaps(client, signup, container):
    owner = await signup("digest")
    h = owner["headers"]
    field, zone, lot = await _field_with_lot(client, h)
    await client.post(f"{FARM}/events", headers=h, json={
        "field_id": field["id"], "zone_id": zone["id"], "type": "irrigation", "outcome": "skipped",
        "reason": "llovió",
    })
    await client.post(f"{FARM}/lots/{lot['id']}/losses", headers=h, json={"quantity": 3, "cause": "pest"})

    rain = container.application.rain_log_service()
    today = datetime.now(rain.tz).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    rows = [{"date": yesterday, "precipitation_mm": 18.4}, {"date": today.isoformat(), "precipitation_mm": 5.0}]
    weather = container.data_providers.weather_service()
    with patch.object(weather.open_meteo, "recent_daily", AsyncMock(return_value=rows)):
        repo_field = await container.application.farm_repository().get_field(
            uuid.UUID(owner["account"]["id"]), uuid.UUID(field["id"])
        )
        assert await rain.log_field(repo_field, days=3, today=today) == 1
        assert await rain.log_field(repo_field, days=3, today=today) == 0  # once per field and day
    rain_events = (await client.get(f"{FARM}/events?type=rain", headers=h)).json()
    assert (rain_events[0]["quantity"], rain_events[0]["source"], rain_events[0]["lot_ids"]) == (
        18.4, "system", [lot["id"]]
    )

    preview = await client.get("/api/v1/digests/preview?kind=weekly", headers=h)
    assert preview.status_code == 200, preview.text
    text = preview.json()["text"]
    assert "No se hizo riego en Cantero 1: llovió." in text
    assert "Llovió 18.4 mm en 1 día." in text and "Pérdida: 3" in text



@pytest.fixture
def no_forecast(container):
    weather = container.data_providers.weather_service()
    with patch.object(weather, "daily_forecast", AsyncMock(return_value=[])):
        yield


async def test_the_morning_summary_is_written_per_field_and_reaches_everyone_in_the_chat(
    client, signup, add_member, with_key, container, no_forecast  # noqa: F811
):
    owner = await signup("summary")
    h = owner["headers"]
    field, zone, lot = await _field_with_lot(client, h)
    await _field_with_lot(client, h, name="Galpón vacío")  # also growing: gets its own summary
    staff = await add_member(owner, "staff")
    engine = container.agent.digest_engine()
    members = (await container.agent.nudge_engine().accounts())[uuid.UUID(owner["account"]["id"])]
    tz = ZoneInfo(next(m for m in members if m.role == "owner").timezone or "UTC")
    today = datetime.now(tz).date()
    # told in the chat yesterday ("sumalo al resumen"): an observation in the bitácora
    noon = datetime.combine(today - timedelta(days=1), datetime.min.time().replace(hour=12), tz)
    r = await client.post(f"{FARM}/events", headers=staff["headers"], json={
        "field_id": field["id"], "zone_id": zone["id"], "type": "observation",
        "notes": "las lechugas del fondo están más chicas",
        "occurred_at": noon.isoformat(),
    })
    assert r.status_code == 201, r.text
    weather = container.data_providers.weather_service()
    hot = [{"date": today.isoformat(), "temp_max_c": 33, "temp_min_c": 19, "temp_mean_c": 26,
            "precipitation_mm": 0, "et0_mm": 6.1}]

    # without the owner's key: the plain version goes, still to everyone and still in the chat
    with patch.object(weather.open_meteo, "recent_daily", AsyncMock(return_value=hot)):
        plain = await engine.run_account(members, "daily", today)
    assert len(plain) == 2 and {d.data["writer"] for d in plain} == {"template"}

    # with it: the agent writes from the facts, once per field and day
    await with_key(owner)
    gateway = container.agent.gemini()
    writing = DigestWriting(text="Ayer hizo calor (33 °C, ET0 6 mm) y no hay riego en el Cantero 1.",
                            questions=["¿Se regó el Cantero 1 ayer?"])
    day = today - timedelta(days=1)
    yesterday_hot = [{**hot[0], "date": day.isoformat()}]
    with patch.object(weather.open_meteo, "recent_daily", AsyncMock(return_value=yesterday_hot)), \
            patch.object(gateway, "generate_structured", AsyncMock(return_value=writing)) as write:
        digests = await engine.run_account(members, "daily", day)
        assert await engine.run_account(members, "daily", day) == []  # once
    assert len(digests) == 2 and write.await_count == 2
    quinta = next(d for d in digests if d.field_id == uuid.UUID(field["id"]))
    prompt = next(c.kwargs["contents"] for c in write.await_args_list if "«Quinta»" in c.kwargs["contents"])
    assert "las lechugas del fondo están más chicas" in prompt and "et0_mm" in prompt
    assert '"irrigated_in_period": false' in prompt
    assert {c.args[0] for c in write.await_args_list} == {uuid.UUID(owner["user"]["id"])}  # the owner's key
    assert quinta.data["writer"] == "agent" and quinta.text.endswith("¿Se regó el Cantero 1 ayer?")
    assert quinta.title == f"Resumen del {day:%d/%m} · Quinta"

    # everyone gets it as the agent's message, and the notification opens that conversation
    for person in (owner, staff):
        conversation_id = quinta.data["conversations"][person["user"]["id"]]
        messages = (await client.get(f"/api/v1/chat/conversations/{conversation_id}/messages",
                                     headers=person["headers"])).json()
        assert (messages[0]["role"], messages[0]["origin"]) == ("assistant", "nudge")
        assert "no hay riego en el Cantero 1" in messages[0]["content"]
        notes = (await client.get("/api/v1/notifications", headers=person["headers"])).json()
        assert any(n["type"] == "digest" and n["entity_id"] == conversation_id for n in notes)
    listed = (await client.get(f"/api/v1/digests?field_id={field['id']}", headers=staff["headers"])).json()
    assert str(quinta.id) in [d["id"] for d in listed]
    assert {d["field_id"] for d in listed} == {field["id"]}


async def test_the_assistant_writes_first_within_the_persons_limits(
    client, signup, add_member, with_key, scripted_model, container, no_forecast  # noqa: F811
):
    owner = await signup("nudge")
    await with_key(owner)
    h = owner["headers"]
    field, zone, lot = await _field_with_lot(client, h)
    staff = await add_member(owner, "staff")
    engine = container.agent.nudge_engine()
    members = (await engine.accounts())[uuid.UUID(owner["account"]["id"])]
    # 12:00 in Argentina (outside quiet hours), anchored on yesterday: the logs written now (real time) must fall
    # inside the engine's recent window, whatever the hour the suite runs at
    now = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=15, minute=0)

    signals = await engine.signals(Actor.from_user(members[0]), now + timedelta(days=3))
    assert any(s.kind == "no_news" and "Cantero 1" in s.text for s in signals)

    gateway = container.agent.gemini()
    decision = NudgeDecision(messages=[NudgeMessage(
        recipient_user_id=staff["user"]["id"], kind="ask", title="¿Pasás por el Cantero 1?",
        text="Hace 3 días no hay noticias del Cantero 1: si pasás, mandame una foto y registro todo.",
        signal_keys=[s.key for s in signals if s.kind == "no_news"],
    )])
    # (without the tracking plans: their signals are tested on their own)
    with patch.object(gateway, "generate_structured", AsyncMock(return_value=decision)) as decide, \
            patch.object(engine, "tracking", None):
        logs = await engine.run_account(members, "morning", now + timedelta(days=3))
        assert [log.outcome for log in logs] == ["sent"]
        # already said: the same signal doesn't make it speak again
        assert await engine.run_account(members, "evening", now + timedelta(days=3)) == []
        assert decide.await_count == 1

    conversations = (await client.get("/api/v1/chat/conversations", headers=staff["headers"])).json()
    messages = (await client.get(f"/api/v1/chat/conversations/{conversations[0]['id']}/messages",
                                 headers=staff["headers"])).json()
    assert (messages[0]["role"], messages[0]["origin"]) == ("assistant", "nudge")
    notes = (await client.get("/api/v1/notifications", headers=staff["headers"])).json()
    assert notes[0]["type"] == "nudge" and notes[0]["entity_id"] == conversations[0]["id"]

    # the reply continues there, and the agent is told what it had written
    await with_key(staff)
    scripted_model.script = [("text", "Gracias, registro la foto apenas la mandes.")]
    r = await client.post("/api/v1/chat", headers=staff["headers"], json={
        "message": "sí, paso a la tarde", "conversation_id": conversations[0]["id"],
    })
    assert r.status_code == 200, r.text
    assert "Hace 3 días no hay noticias" in str(scripted_model.requests[-1].contents[-1].parts)

    # the person's own limit: no more messages today
    await client.put("/api/v1/me/notification-preferences", headers=staff["headers"], json={"max_nudges_per_day": 0})
    await client.post(f"{FARM}/lots/{lot['id']}/losses", headers=h, json={"quantity": 1})
    decision.messages[0].signal_keys = ["something-new"]
    with patch.object(gateway, "generate_structured", AsyncMock(return_value=decision)), \
            patch.object(engine, "signals", AsyncMock(return_value=[
                type(signals[0])(key="something-new", kind="loss", text="Pérdida registrada.")
            ])):
        logs = await engine.run_account(members, "evening", now + timedelta(days=3))
    assert [log.outcome for log in logs] == ["budget"]

    log = (await client.get("/api/v1/nudges/log", headers=h)).json()
    assert {entry["outcome"] for entry in log} == {"sent", "budget"}
    assert (await client.get("/api/v1/nudges/log", headers=staff["headers"])).status_code == 403


async def test_push_subscriptions_and_preferences(client, signup, add_member, container):
    owner = await signup("push")
    staff = await add_member(owner, "staff")
    prefs = (await client.get("/api/v1/me/notification-preferences", headers=staff["headers"])).json()
    assert (prefs["daily_digest"], prefs["max_nudges_per_day"], prefs["push_devices"]) == (True, 2, 0)
    sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}}
    assert (await client.post("/api/v1/push/subscriptions", headers=staff["headers"], json=sub)).json() == {
        "devices": 1
    }
    assert (await client.post("/api/v1/push/subscriptions", headers=staff["headers"], json=sub)).json() == {
        "devices": 1
    }
    push = container.application.push_service()
    recipients = await push.digest_recipients(uuid.UUID(owner["account"]["id"]), "daily")
    assert {str(r) for r in recipients} == {owner["user"]["id"], staff["user"]["id"]}  # everyone, unless they opt out
    await client.put("/api/v1/me/notification-preferences", headers=staff["headers"], json={"daily_digest": False})
    assert [str(r) for r in await push.digest_recipients(uuid.UUID(owner["account"]["id"]), "daily")] == [
        owner["user"]["id"]
    ]

    # with push configured, a notification goes to the phone; the bitácora's own entries don't
    with patch.object(push, "private_key", "x"), patch.object(push, "public_key", "y"), \
            patch.object(push, "_send_one", lambda info, payload: None):
        sent = await push.send([uuid.UUID(staff["user"]["id"])], "Hola", "Probando", "/chat")
        assert sent == 1
    await client.post("/api/v1/push/unsubscribe", headers=staff["headers"], json={"endpoint": sub["endpoint"]})
    assert (await client.get("/api/v1/me/notification-preferences", headers=staff["headers"])).json()[
        "push_devices"
    ] == 0


async def test_the_person_sets_how_closely_the_agent_follows_them(client, signup):
    user = await signup("tracking")
    h = user["headers"]
    start = (await client.get("/api/v1/auth/tracking-profile", headers=h)).json()
    assert start["intensity"] == "media" and start["intensity_source"] == "default"
    await client.post("/api/v1/auth/enroll", headers=h, json={"form": {f"q{i}": "C" for i in range(1, 11)}})
    enrolled = (await client.get("/api/v1/auth/tracking-profile", headers=h)).json()
    assert (enrolled["intensity"], enrolled["intensity_source"]) == ("alta", "enroll")
    r = await client.put("/api/v1/auth/tracking-profile", headers=h, json={
        "intensity": "baja",
        "growing_context": {"resources": [{"name": "tester de pH barato"}], "notes": "dos horas por semana"},
    })
    assert r.status_code == 200, r.text
    assert (r.json()["intensity"], r.json()["intensity_source"], r.json()["weekly_asks"]) == ("baja", "person", 2)
    assert [x["name"] for x in r.json()["growing_context"]["resources"]] == ["tester de pH barato"]
    bad = await client.put("/api/v1/auth/tracking-profile", headers=h, json={"intensity": "maxima"})
    assert bad.status_code == 422
    reset = (await client.put("/api/v1/auth/tracking-profile", headers=h, json={"reset_intensity": True})).json()
    assert (reset["intensity"], reset["growing_context"]["notes"]) == ("alta", "dos horas por semana")


async def test_the_agent_notes_what_the_person_has_from_the_chat(
    client, signup, with_key, scripted_model  # noqa: F811
):
    user = await signup("means")
    await with_key(user)
    h = user["headers"]
    scripted_model.script = [
        ("call", "update_growing_means", {"add": [{"name": "botellas como riego por goteo"}]}),
        ("text", "Anotado."),
    ]
    r = await client.post("/api/v1/chat", headers=h, json={"message": "riego con botellas enterradas"})
    assert r.status_code == 200, r.text
    means = (await client.get("/api/v1/auth/tracking-profile", headers=h)).json()["growing_context"]["resources"]
    assert [(m["name"], m["source"]) for m in means] == [("botellas como riego por goteo", "agent")]


async def test_data_requests_respect_the_weekly_budget_and_answers_are_recorded(
    client, signup, with_key, scripted_model, container, no_forecast  # noqa: F811
):
    owner = await signup("asks")
    await with_key(owner)
    h = owner["headers"]
    await _field_with_lot(client, h)
    await client.put("/api/v1/auth/tracking-profile", headers=h, json={"intensity": "baja"})
    await client.put("/api/v1/me/notification-preferences", headers=h, json={"max_nudges_per_day": 6})
    engine = container.agent.nudge_engine()
    members = (await engine.accounts())[uuid.UUID(owner["account"]["id"])]
    now = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=15, minute=0)
    gateway = container.agent.gemini()

    outcomes, prompts = [], []
    for i in range(3):  # intensidad baja: 2 pedidos por semana
        decision = NudgeDecision(messages=[NudgeMessage(
            recipient_user_id=owner["user"]["id"], kind="ask", title="Una foto",
            text=f"¿Me mandás una foto del cantero? ({i})", signal_keys=[f"k{i}"],
        )])
        with patch.object(gateway, "generate_structured", AsyncMock(return_value=decision)) as decide, \
                patch.object(engine, "signals", AsyncMock(return_value=[Signal(key=f"k{i}", kind="no_news",
                                                                                text="Sin noticias.")])):
            logs = await engine.run_account(members, "morning", now + timedelta(minutes=i))
        outcomes.append(logs[0].outcome)
        prompts.append(decide.await_args.kwargs["contents"])
    assert outcomes == ["sent", "sent", "budget"]
    assert "intensidad baja · pedidos de datos disponibles esta semana: 2" in prompts[0]
    assert "pedidos de datos disponibles esta semana: 0" in prompts[2]

    # answering in the conversation the assistant opened marks it, with the channel
    conversation_id = (await client.get("/api/v1/chat/conversations", headers=h)).json()[0]["id"]
    scripted_model.script = [("text", "Gracias.")]
    r = await client.post("/api/v1/chat", headers=h, json={"message": "ahí va", "conversation_id": conversation_id})
    assert r.status_code == 200, r.text
    log = (await client.get("/api/v1/nudges/log", headers=h)).json()
    answered = [e for e in log if e.get("responded_at")]
    assert len(answered) == 1 and answered[0]["response_channel"] == "text"
    summary = await container.application.engagement_service().summary(uuid.UUID(owner["user"]["id"]))
    assert (summary.asks_sent, summary.asks_answered, summary.channels) == (2, 1, {"text": 1})


async def test_the_daily_action_comes_from_the_plan_and_is_answered_with_one_tap(
    client, signup, with_key, scripted_model, container, no_forecast  # noqa: F811
):
    from datetime import date

    from src.application.tracking.schemas import TrackingPlanContent

    owner = await signup("oneTap")
    await with_key(owner)
    h = owner["headers"]
    field, zone, lot = await _field_with_lot(client, h)
    await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cajon"})  # free to sow
    actor = Actor(user_id=uuid.UUID(owner["user"]["id"]), account_id=uuid.UUID(owner["account"]["id"]),
                  role="owner")
    today = date.today()
    plans = container.application.tracking_plan_service()
    saved = await plans.save(actor, uuid.UUID(lot["id"]), TrackingPlanContent.model_validate({
        "summary": "Lechuga", "current_stage": "vegetativo",
        "stages": [{"key": "vegetativo", "name": "Crecimiento", "status": "actual"}],
        "key_moments": [{"key": "cosecha", "name": "Primera cosecha", "window_start": today.isoformat()}],
        "items": [{"section": "revision", "title": "Humedad a 10 cm", "why": "Mucha ET0",
                   "how": "Tocá la tierra a 10 cm", "method": "medicion", "measurement": "humedad_suelo",
                   "window_start": (today - timedelta(days=3)).isoformat(),
                   "window_end": (today - timedelta(days=1)).isoformat()}],
    }), "inicial")
    item = saved.content.items[0]

    engine = container.agent.nudge_engine()
    members = (await engine.accounts())[uuid.UUID(owner["account"]["id"])]
    signals = await engine.signals(Actor.from_user(members[0]))
    kinds = {s.kind for s in signals}
    assert {"plan_check", "key_moment", "sowing_room"} <= kinds
    check = next(s for s in signals if s.kind == "plan_check")
    assert "vencido" in check.text and check.data["item_id"] == item.id
    assert "Cajón 1" in next(s for s in signals if s.kind == "sowing_room").text

    push = container.application.push_service()
    gateway = container.agent.gemini()
    decision = NudgeDecision(messages=[NudgeMessage(
        recipient_user_id=owner["user"]["id"], kind="ask", title="¿Cómo está la tierra?",
        text="¿La tierra del Cantero 1 a 10 cm está húmeda o seca?", signal_keys=[check.key],
        quick_replies=["Húmeda", "Seca", "No sé"], plan_ref={"lot_id": lot["id"], "item_id": item.id},
    )])
    with patch.object(gateway, "generate_structured", AsyncMock(return_value=decision)) as decide, \
            patch.object(push, "send", AsyncMock(return_value=1)) as sent, \
            patch.object(type(push), "enabled", property(lambda self: True)):
        logs = await engine.run_account(members, "morning")
    assert "La acción del día" in decide.await_args.kwargs["system_instruction"]
    assert f"item_id={item.id}" in decide.await_args.kwargs["contents"]
    log = logs[0]
    assert log.outcome == "sent" and log.quick_replies == ["Húmeda", "Seca", "No sé"]
    extra = sent.await_args.kwargs["extra"]
    assert [a["title"] for a in extra["actions"]] == ["Húmeda", "Seca", "No sé"]
    assert (await plans.get(actor, uuid.UUID(lot["id"]))).content.items[0].status == "pedido"

    # from the notification: no session, the signed token instead
    bad = await client.post(f"/api/v1/nudges/{log.id}/notification-reply", json={"answer": "Seca", "token": "x"})
    assert bad.status_code == 403
    ok = await client.post(f"/api/v1/nudges/{log.id}/notification-reply",
                           json={"answer": "Seca", "token": extra["reply_token"]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["channel"] == "button" and ok.json()["plan_updated"] is True
    plan = await plans.get(actor, uuid.UUID(lot["id"]))
    assert (plan.content.items[0].status, plan.content.items[0].result) == ("respondido", "Seca")
    assert plan.revisions[-1].by == "person"
    tasks = (await client.get("/api/v1/agent-tasks", headers=h)).json()
    assert tasks[0]["kind"] == "replan_lot" and "Seca" in tasks[0]["input"]["observations"][0]
    messages = (await client.get(f"/api/v1/chat/conversations/{log.conversation_id}/messages", headers=h)).json()
    assert (messages[-1]["role"], messages[-1]["content"], messages[-1]["origin"]) == ("user", "Seca", "button")

    # the next chat turn is told about the answer
    scripted_model.script = [("call", "suggest_replies", {"options": ["Sí", "No"]}), ("text", "¿Regaste hoy?")]
    r = await client.post("/api/v1/chat", headers=h, json={"message": "dale", "conversation_id":
                                                            str(log.conversation_id)})
    assert "(la persona respondió con un toque) Seca" in str(scripted_model.requests[0].contents[-1].parts)
    chips = [a for a in r.json()["attachments"] if a["type"] == "quick_replies"]
    assert chips and chips[0]["options"] == ["Sí", "No"]

    other = await signup("intruder")
    stolen = await client.post(f"/api/v1/nudges/{log.id}/reply", headers=other["headers"], json={"answer": "x"})
    assert stolen.status_code == 404
