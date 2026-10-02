"""
Full chat turn through Google ADK with a scripted model in place of Gemini: tool calls hit the real
services and database, conversations are persisted, and tools can't escape the caller's account.
"""
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from sqlalchemy import text

FAKE_KEY = "AIzaSyTESTKEY-0123456789abcdefghijKLMN"


class ScriptedLlm(BaseLlm):
    """Returns the next scripted step on every model call:
    ('call', name, args), ('text', str) or ('text+call', str, name, args)."""
    script: list = []
    requests: list = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        kind, *payload = self.script.pop(0)
        if kind == "call":
            name, args = payload
            parts = [types.Part.from_function_call(name=name, args=args)]
        elif kind == "text+call":
            text, name, args = payload
            parts = [types.Part(text=text), types.Part.from_function_call(name=name, args=args)]
        else:
            parts = [types.Part(text=payload[0])]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


@pytest.fixture
def scripted_model():
    llm = ScriptedLlm(model="scripted", script=[], requests=[])
    with patch("src.agent.runner.AgentRunner._model", lambda self, api_key: llm):
        yield llm


@pytest.fixture
def with_key(client):
    async def _set(user):
        with patch("src.agent.providers.credentials_service.validate_gemini_key", AsyncMock()):
            r = await client.put(
                "/api/v1/me/provider-credentials/gemini", headers=user["headers"], json={"api_key": FAKE_KEY}
            )
        assert r.status_code == 200
    return _set


@pytest.fixture(autouse=True)
def no_title_calls(container):
    gateway = container.agent.gemini()
    with patch.object(gateway, "generate_text", AsyncMock(return_value="Siembra de tomates")):
        yield


async def test_chat_turn_registers_crop_cycle_and_event(client, signup, add_member, with_key, scripted_model):
    owner = await signup("agent")
    await with_key(owner)
    h = owner["headers"]
    await client.post(
        "/api/v1/farm-management/fields",
        headers=h,
        json={"name": "Cantero 1", "latitude": -34.92, "longitude": -57.95},
    )

    scripted_model.script = [
        ("call", "create_crop_cycle", {"crop_name": "Tomate", "variety": "Cherry", "field": "cantero 1"}),
        ("call", "log_event", {"event_type": "irrigation", "field": "Cantero 1", "quantity": 10, "unit": "litros"}),
        ("text", "¡Listo! Registré la siembra de tomate cherry y el riego de 10 litros en Cantero 1."),
    ]
    response = await client.post(
        "/api/v1/chat",
        headers=h,
        json={"message": "hoy sembré tomate cherry en el cantero 1 y regué 10 litros"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["response"].startswith("¡Listo!")
    assert [t["name"] for t in body["metadata"]["tool_calls"]] == ["create_crop_cycle", "log_event"]
    assert all(t["ok"] for t in body["metadata"]["tool_calls"])
    conversation_id = body["metadata"]["conversation_id"]

    # The system instruction carries the static knowledge base and the account's modules — kept free
    # of anything that changes turn to turn (see AgentRunner._static_instruction) so Gemini/ADK's
    # context caching can reuse this prefix across turns instead of reprocessing it every time.
    system = str(scripted_model.requests[0].config.system_instruction)
    assert "Cantero 1" not in system

    # No profile yet -> falls back to the guardian's module set: general + horticulture, nothing else.
    assert "## Agronomía general" in system and "## Horticultura a campo abierto" in system
    assert "## Viticultura" not in system and "## Cultivos extensivos" not in system

    # Per-turn account context (fields, date) rides in the user message content instead, so it never
    # touches the cached system instruction.
    history = " ".join(str(c.parts) for c in scripted_model.requests[0].contents)
    assert "Campos de la cuenta" in history and "Cantero 1" in history

    cycles = (await client.get("/api/v1/farm-management/crop-cycles", headers=h)).json()
    assert len(cycles) == 1 and cycles[0]["status"] == "planted" and cycles[0]["expected_harvest_date"]
    events = (await client.get("/api/v1/farm-management/events", headers=h)).json()
    assert events[0]["type"] == "irrigation" and events[0]["source"] == "agent" and events[0]["quantity"] == 10

    conv = (await client.get(f"/api/v1/chat/conversations/{conversation_id}", headers=h)).json()
    assert conv["title"] == "Siembra de tomates"
    messages = (await client.get(f"/api/v1/chat/conversations/{conversation_id}/messages", headers=h)).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]

    # Same account, another member: shares the farm data, not the conversation.
    staff = await add_member(owner, "staff")
    other = await client.get(f"/api/v1/chat/conversations/{conversation_id}", headers=staff["headers"])
    assert other.status_code == 404
    assert len((await client.get("/api/v1/farm-management/events", headers=staff["headers"])).json()) == 1


async def test_conversations_keep_separate_threads(client, signup, with_key, scripted_model, container):
    user = await signup("threads")
    await with_key(user)
    h = user["headers"]

    scripted_model.script = [("text", "Hola A")]
    a = (await client.post("/api/v1/chat", headers=h, json={"message": "conversación A"})).json()
    scripted_model.script = [("text", "Hola B")]
    b = (await client.post("/api/v1/chat", headers=h, json={"message": "conversación B"})).json()
    scripted_model.script = [("text", "Seguimos en A")]
    scripted_model.requests.clear()
    a2 = await client.post(
        "/api/v1/chat", headers=h, json={"message": "seguimos", "conversation_id": a["metadata"]["conversation_id"]}
    )
    assert a2.status_code == 200

    history = " ".join(str(c.parts) for c in scripted_model.requests[0].contents)
    assert "conversación A" in history and "conversación B" not in history

    listed = (await client.get("/api/v1/chat/conversations", headers=h)).json()
    assert {c["id"] for c in listed} == {a["metadata"]["conversation_id"], b["metadata"]["conversation_id"]}

    conv_id = b["metadata"]["conversation_id"]
    assert (await client.delete(f"/api/v1/chat/conversations/{conv_id}", headers=h)).status_code == 204
    async with container.db_session_factory()() as session:
        remaining = (
            await session.execute(text("SELECT count(*) FROM adk.sessions WHERE id = :id"), {"id": conv_id})
        ).scalar_one()
    assert remaining == 0


async def test_tools_cannot_touch_other_accounts(client, signup, with_key, scripted_model):
    victim = await signup("victim")
    victim_field = (
        await client.post("/api/v1/farm-management/fields", headers=victim["headers"], json={"name": "Privado"})
    ).json()

    attacker = await signup("attacker")
    await with_key(attacker)
    scripted_model.script = [
        ("call", "log_event", {"event_type": "observation", "field": victim_field["id"], "notes": "hola"}),
        ("text", "No pude registrar el evento."),
    ]
    response = await client.post("/api/v1/chat", headers=attacker["headers"], json={"message": "registrá algo"})
    assert response.status_code == 200
    assert response.json()["metadata"]["tool_calls"][0]["ok"] is False
    assert (await client.get("/api/v1/farm-management/events", headers=victim["headers"])).json() == []


async def test_staff_does_not_get_management_tools(client, signup, add_member, with_key, scripted_model):
    owner = await signup("tools-owner")
    staff = await add_member(owner, "staff")
    await with_key(staff)
    scripted_model.script = [("text", "ok")]
    await client.post("/api/v1/chat", headers=staff["headers"], json={"message": "hola"})
    declared = {
        f.name for tool in scripted_model.requests[0].config.tools or [] for f in (tool.function_declarations or [])
    }
    assert "log_event" in declared
    assert "create_field" not in declared and "create_crop_cycle" not in declared


async def test_web_search_failure_does_not_break_the_turn(client, signup, with_key, scripted_model, container):
    from src.shared.utils.errors import ProviderError

    user = await signup("search")
    await with_key(user)
    scripted_model.script = [
        ("call", "web_search", {"query": "calendario de siembra zapallito La Plata"}),
        ("text", "No pude verificarlo en la web, pero en general se siembra de octubre a enero."),
    ]
    tavily = container.data_providers.search()
    with patch.object(tavily, "search", AsyncMock(side_effect=ProviderError("Tavily unavailable"))):
        response = await client.post("/api/v1/chat", headers=user["headers"], json={"message": "¿cuándo siembro?"})
    assert response.status_code == 200
    body = response.json()
    call = body["metadata"]["tool_calls"][0]
    assert call["name"] == "web_search" and call["ok"] is False
    assert body["metadata"]["search_performed"] is True


async def test_web_search_sources_are_returned(client, signup, with_key, scripted_model, container):
    from src.providers.search.tavily import SearchHit

    user = await signup("search-ok")
    await with_key(user)
    scripted_model.script = [
        ("call", "web_search", {"query": "siembra zapallito"}),
        ("text", "Según el INTA, de octubre a enero."),
    ]
    tavily = container.data_providers.search()
    hits = [SearchHit(title="INTA", url="https://inta.gob.ar/zapallito", content="De octubre a enero.")]
    with patch.object(tavily, "search", AsyncMock(return_value=hits)):
        response = await client.post("/api/v1/chat", headers=user["headers"], json={"message": "¿cuándo siembro?"})
    assert response.json()["sources"] == [{"title": "INTA", "uri": "https://inta.gob.ar/zapallito"}]


def _parse_sse(raw: str) -> list[tuple[str, dict]]:
    import json

    events = []
    for block in raw.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def test_stream_emits_events_in_order_and_persists(client, signup, with_key, scripted_model):
    user = await signup("stream")
    await with_key(user)
    h = user["headers"]
    await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Maceta"})
    scripted_model.script = [
        ("text+call", "Dale, lo registro.", "log_event", {"event_type": "irrigation", "quantity": 2, "unit": "litros"}),
        ("text", "Listo, registré 2 litros."),
    ]
    response = await client.post("/api/v1/chat/stream", headers=h, json={"message": "regué 2 litros"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    names = [e[0] for e in events]
    assert names[0] == "meta" and names[-1] == "done"
    assert names.index("tool_call") < names.index("tool_result")
    assert "".join(d["text"] for n, d in events if n == "delta") == "Dale, lo registro.\n\nListo, registré 2 litros."
    done = events[-1][1]
    assert done["response"] == "Dale, lo registro.\n\nListo, registré 2 litros."
    conversation_id = events[0][1]["conversation_id"]
    assert done["metadata"]["conversation_id"] == conversation_id
    messages = (await client.get(f"/api/v1/chat/conversations/{conversation_id}/messages", headers=h)).json()
    assert messages[-1]["content"] == done["response"]


async def test_stream_without_key_is_plain_409(client, signup):
    user = await signup("stream-nokey")
    response = await client.post("/api/v1/chat/stream", headers=user["headers"], json={"message": "hola"})
    assert response.status_code == 409
    assert response.json()["error_code"] == "PROVIDER_KEY_MISSING"


async def test_get_latest_periodic_report_tool(client, signup, with_key, scripted_model, container):
    from uuid import UUID

    from src.application.reports.schemas import ReportCreate, ReportUpdate
    from src.shared.domain.actor import Actor

    owner = await signup("periodic-tool")
    await with_key(owner)
    h = owner["headers"]
    field = (await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Cantero P"})).json()

    actor = Actor(UUID(owner["user"]["id"]), UUID(owner["account"]["id"]), "owner")
    reports = container.application.reports_service()
    report = await reports.create_report(
        actor,
        ReportCreate(field_id=UUID(field["id"]), report_type="periodic", image_identifier="fake.jpg"),
    )
    await reports.update_report(
        actor,
        report.id,
        ReportUpdate(
            status="ANALYSIS_COMPLETED",
            summary="La planta está sana y en buen desarrollo.",
            raw_analysis_data={"llm_structured_periodic": {"risks": [], "health_status": "good"}},
        ),
    )

    scripted_model.script = [
        ("call", "get_latest_periodic_report", {"field": "Cantero P"}),
        ("text", "Según el último análisis, tu huerta está sana."),
    ]
    response = await client.post("/api/v1/chat", headers=h, json={"message": "¿cómo está la huerta?"})
    assert response.status_code == 200, response.text
    call = response.json()["metadata"]["tool_calls"][0]
    assert call["name"] == "get_latest_periodic_report" and call["ok"] is True


async def test_get_latest_periodic_report_tool_when_none_exists(client, signup, with_key, scripted_model):
    owner = await signup("periodic-tool-empty")
    await with_key(owner)
    await client.post(
        "/api/v1/farm-management/fields", headers=owner["headers"], json={"name": "Cantero vacío"}
    )
    scripted_model.script = [
        ("call", "get_latest_periodic_report", {"field": "Cantero vacío"}),
        ("text", "Todavía no hay análisis de seguimiento para ese campo."),
    ]
    response = await client.post(
        "/api/v1/chat", headers=owner["headers"], json={"message": "¿cómo está la huerta?"}
    )
    assert response.json()["metadata"]["tool_calls"][0]["ok"] is True


async def test_chat_report_id_context_adds_note_to_first_turn(client, signup, with_key, scripted_model, container):
    from uuid import UUID

    from src.application.reports.schemas import ReportCreate
    from src.shared.domain.actor import Actor

    owner = await signup("deeplink")
    await with_key(owner)
    h = owner["headers"]

    actor = Actor(UUID(owner["user"]["id"]), UUID(owner["account"]["id"]), "owner")
    reports = container.application.reports_service()
    report = await reports.create_report(
        actor,
        ReportCreate(
            title="Diagnóstico tomate",
            summary="Tizón tardío detectado en las hojas inferiores.",
            status="ANALYSIS_COMPLETED",
            report_type="diagnosis",
        ),
    )

    scripted_model.script = [("text", "Sí, vi el reporte del tizón.")]
    response = await client.post(
        "/api/v1/chat",
        headers=h,
        json={"message": "¿qué opinás de esto?", "context": {"report_id": str(report.id)}},
    )
    assert response.status_code == 200, response.text
    # The report note is per-turn account context, so it rides in the message content, not the
    # (cacheable) system instruction — see AgentRunner._account_snapshot.
    history = " ".join(str(c.parts) for c in scripted_model.requests[0].contents)
    assert "Tizón tardío" in history


async def test_chat_unknown_report_id_is_ignored_silently(client, signup, with_key, scripted_model):
    import uuid

    owner = await signup("deeplink-missing")
    await with_key(owner)
    scripted_model.script = [("text", "Hola.")]
    response = await client.post(
        "/api/v1/chat",
        headers=owner["headers"],
        json={"message": "hola", "context": {"report_id": str(uuid.uuid4())}},
    )
    assert response.status_code == 200


async def test_management_tools_field_assignee_status_and_delete(client, signup, add_member, with_key, scripted_model):
    owner = await signup("tools-mg")
    staff = await add_member(owner, "staff")
    h = owner["headers"]
    await with_key(owner)
    field = (await client.post("/api/v1/farm-management/fields", headers=h, json={"name": "Huerta Norte"})).json()

    scripted_model.script = [
        ("call", "add_roadmap_item", {"title": "Atar tomates", "field": "Huerta Norte", "assigned_to": staff["email"]}),
        ("text", "Listo."),
    ]
    response = await client.post("/api/v1/chat", headers=h, json={"message": "agendá atar tomates"})
    assert response.json()["metadata"]["tool_calls"][0]["ok"] is True
    task = (await client.get("/api/v1/management/roadmap", headers=h)).json()[0]
    assert task["field_id"] == field["id"] and task["assigned_to"] == staff["user"]["id"]

    scripted_model.script = [
        ("call", "update_roadmap_item", {"item_id": task["id"], "status": "cancelado", "assigned_to": "ninguno"}),
        ("text", "Cancelada."),
    ]
    await client.post("/api/v1/chat", headers=h, json={"message": "cancelala"})
    task = (await client.get("/api/v1/management/roadmap", headers=h)).json()[0]
    assert task["status"] == "cancelado" and task["assigned_to"] is None and task["field_id"] == field["id"]

    scripted_model.script = [("call", "remove_roadmap_item", {"item_id": task["id"]}), ("text", "Borrada.")]
    await client.post("/api/v1/chat", headers=h, json={"message": "sí, borrala"})
    assert (await client.get("/api/v1/management/roadmap", headers=h)).json() == []

    await with_key(staff)
    scripted_model.script = [("text", "ok")]
    await client.post("/api/v1/chat", headers=staff["headers"], json={"message": "hola"})
    declared = {
        f.name for tool in scripted_model.requests[-1].config.tools or [] for f in (tool.function_declarations or [])
    }
    assert "update_shopping_item" in declared and "list_account_members" in declared
    assert not declared & {"remove_shopping_item", "remove_budget_entry", "remove_roadmap_item", "update_budget_entry"}
