import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from google.genai import types

from src.agent.preflight import PreflightEngine, PreflightInputs, PreflightPlan, ToolRequest, prune_consulted_blocks
from src.agent.preflight.blocks import END, START, build_block
from src.agent.preflight.engine import MAX_SKILLS, MAX_TOOLS


def _skill(text="x" * 400, description="descripción"):
    return SimpleNamespace(frontmatter=SimpleNamespace(description=description), instructions=text)


async def _echo(field=None, days=30, include_image=True):
    """Pretend tool."""
    return {"field": field, "days": days, "include_image": include_image}


def _inputs(skills=None, tools=None, message="las hojas del tomate se ponen amarillas"):
    return PreflightInputs(
        user_id=uuid4(), country="AR", message=message, account_text="cuenta", recent=[],
        tools=tools if tools is not None else {"get_recent_weather_summary": _echo, "log_event": _echo},
        skills=skills if skills is not None else {"ficha-tomate": _skill(), "plagas-tomate": _skill()},
    )


def _engine(**kw):
    return PreflightEngine(gemini=SimpleNamespace(lite_model="lite"), **kw)


def _req(name, **args):
    return ToolRequest(name=name, args=json.dumps(args))


def test_sanitize_keeps_only_known_skills_and_read_only_tools_with_accepted_arguments():
    inp = _inputs(tools={"get_recent_weather_summary": _echo, "log_event": _echo, "get_zone_satellite_status": _echo})
    plan = PreflightPlan(
        skills=["ficha-tomate", "inventada", "ficha-tomate", "plagas-tomate"],
        tools=[
            _req("get_recent_weather_summary", field="Huerta", days=30, nope="descartado"),
            _req("log_event", event_type="irrigation"),  # a write: never run speculatively
            _req("get_zone_satellite_status", field="Huerta", include_image=True),
            ToolRequest(name="get_recent_weather_summary", args="{not json"),
        ],
        web_query="mosca blanca tomate productos registrados SENASA",
    )
    clean = PreflightEngine.sanitize(plan, inp)
    assert clean.skills == ["ficha-tomate", "plagas-tomate"]
    names = [t.name for t in clean.tools]
    assert "log_event" not in names
    weather = json.loads(clean.tools[0].args)
    assert weather == {"field": "Huerta", "days": 30}  # the unknown argument is gone
    satellite = next(t for t in clean.tools if t.name == "get_zone_satellite_status")
    assert json.loads(satellite.args)["include_image"] is False  # forced: no vision call as a side trip


def test_sanitize_adds_the_web_search_only_if_the_tool_exists_and_caps_the_counts():
    inp = _inputs(skills={f"s{i}": _skill() for i in range(10)}, tools={"web_search": _echo})
    plan = PreflightPlan(skills=[f"s{i}" for i in range(10)], web_query="  calendario siembra  ")
    clean = PreflightEngine.sanitize(plan, inp)
    assert len(clean.skills) == MAX_SKILLS
    assert [t.name for t in clean.tools] == ["web_search"]
    # web_search isn't available in this deployment: the query is ignored
    assert PreflightEngine.sanitize(plan, _inputs(tools={})).tools == []
    many = PreflightPlan(tools=[_req("get_recent_weather_summary", field=f"c{i}") for i in range(20)])
    assert len(PreflightEngine.sanitize(many, _inputs()).tools) == MAX_TOOLS


async def test_plan_is_skipped_for_trivial_messages_and_when_disabled_without_calling_the_router():
    engine = _engine()
    engine.gemini.generate_structured = AsyncMock()
    assert await engine.plan(_inputs(message="gracias")) is None
    assert await _engine(enabled=False).plan(_inputs()) is None
    engine.gemini.generate_structured.assert_not_awaited()


async def test_plan_falls_back_to_none_when_the_router_fails_or_asks_for_nothing():
    engine = _engine()
    engine.gemini.generate_structured = AsyncMock(side_effect=RuntimeError("boom"))
    assert await engine.plan(_inputs()) is None
    engine.gemini.generate_structured = AsyncMock(return_value=PreflightPlan(reason="saludo"))
    assert await engine.plan(_inputs()) is None
    engine.gemini.generate_structured = AsyncMock(return_value=PreflightPlan(skills=["ficha-tomate"]))
    plan = await engine.plan(_inputs())
    assert plan.skills == ["ficha-tomate"]
    kwargs = engine.gemini.generate_structured.await_args.kwargs
    assert kwargs["thinking_level"] == "low" and kwargs["model"] == "lite"  # a routing call needs no deep thinking


async def test_execute_runs_tools_in_parallel_survives_a_failure_and_puts_skills_first():
    async def slow(field=None):
        await asyncio.sleep(0.2)
        return {"ok": field}

    async def broken(field=None):
        raise RuntimeError("down")

    inp = _inputs(tools={"get_current_weather": slow, "get_forecast": slow, "list_crop_cycles": broken})
    plan = PreflightPlan(
        skills=["ficha-tomate"],
        tools=[_req("get_current_weather", field="a"), _req("get_forecast", field="a"), _req("list_crop_cycles")],
    )
    started = time.perf_counter()
    result = await _engine().execute(inp, plan)
    assert time.perf_counter() - started < 0.35  # two 0.2 s tools overlapped
    assert [c["ok"] for c in result.calls if c["name"] != "load_skill"] == [True, True, False]
    assert {"name": "load_skill", "args": {"skill_name": "ficha-tomate"}, "ok": True} in result.calls
    assert result.block.index("## Skill: ficha-tomate") < result.block.index("## Datos: get_current_weather")
    assert result.block.startswith(START) and result.block.rstrip().endswith(END)
    assert "Consultado: skills ficha-tomate; datos get_current_weather, get_forecast, list_crop_cycles" in result.block


async def test_execute_keeps_data_and_drops_the_skills_that_do_not_fit_the_token_budget():
    big = _skill("y" * 40_000)  # ~10k tokens
    inp = _inputs(skills={"ficha-tomate": _skill("z" * 400), "fisiologia-grande": big})
    plan = PreflightPlan(skills=["ficha-tomate", "fisiologia-grande"], tools=[_req("get_recent_weather_summary")])
    result = await _engine(max_tokens=2_000).execute(inp, plan)
    assert "## Skill: ficha-tomate" in result.block and "fisiologia-grande" not in result.block
    assert "## Datos: get_recent_weather_summary" in result.block


def _user(text):
    return types.Content(role="user", parts=[types.Part(text=text)])


def test_old_turns_lose_their_block_but_the_current_message_keeps_it():
    old = build_block("skills ficha-tomate", [("Skill: ficha-tomate", "TEXTO LARGO DE LA FICHA")])
    new = build_block("datos get_forecast", [("Datos: get_forecast", "LLUVIA 12 MM")])
    contents = [
        _user(f"[Contexto]\n{old}\n\nprimera pregunta"),
        types.Content(role="model", parts=[types.Part(text="respuesta")]),
        _user(f"[Contexto]\n{new}\n\nsegunda pregunta"),
        types.Content(role="model", parts=[types.Part.from_function_call(name="x", args={})]),
        types.Content(role="user", parts=[types.Part.from_function_response(name="x", response={"a": 1})]),
    ]
    request = SimpleNamespace(contents=contents)
    assert prune_consulted_blocks(None, request) is None
    first, current = request.contents[0].parts[0].text, request.contents[2].parts[0].text
    assert "TEXTO LARGO" not in first and "[Consultado en un mensaje anterior: skills ficha-tomate]" in first
    assert "primera pregunta" in first  # only the block went, never the user's words
    assert "LLUVIA 12 MM" in current  # the block of the current turn stays, even after tool calls in it
