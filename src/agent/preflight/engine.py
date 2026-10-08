"""Plans (router), runs (parallel read-only tools) and assembles (block) the preflight of a chat turn."""
import asyncio
import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from uuid import UUID

from ..usage import TurnUsage
from .blocks import build_block
from .plan import PreflightPlan, ToolRequest

logger = logging.getLogger(__name__)

# Only tools that read and have no side effect worth the surprise. Writes, the Gemini-vision tools (harvest verdict)
# and the expert analysis (a model call of its own) are never run speculatively: the chat model asks for them if needed.
READ_ONLY_TOOLS = frozenset({
    "list_fields", "list_crop_cycles", "list_zones", "list_recent_events", "find_crop_in_catalog",
    "get_harvest_totals", "list_active_alerts", "get_latest_periodic_report", "list_reminders",
    "get_field_soil_context", "get_field_sun_exposure", "recall_facts",
    "get_current_weather", "get_forecast", "get_recent_weather_summary", "get_solar_radiation_context",
    "get_irrigation_recommendation", "get_zone_satellite_status", "web_search",
})
# The satellite tool also runs a Gemini vision call on the map when asked for the image: not as a side trip.
FORCED_ARGS: dict[str, dict[str, Any]] = {"get_zone_satellite_status": {"include_image": False}}

MAX_SKILLS = 6
MAX_TOOLS = 6
MIN_MESSAGE_CHARS = 12  # "hola", "gracias", "ok": nothing to gather, don't pay for a router call
TOOL_RESULT_MAX_CHARS = 6000

ROUTER_INSTRUCTION = """Eres el enrutador de contexto de AgroAI, un asistente agronómico. NO respondes a la persona:
decides qué hay que reunir ANTES de que el asistente responda, para que lo tenga todo en una sola ronda.

Devuelves un plan con tres cosas:
- skills: nombres EXACTOS del menú de skills (máximo 6, los más importantes primero).
- tools: herramientas de lectura del menú, con sus argumentos como objeto JSON en texto (máximo 6).
- web_query: una sola búsqueda web específica (incluye el país y el cultivo), o null.

Criterios:
- Elige solo lo que cambia la respuesta. Un saludo, un agradecimiento, una confirmación o algo que la persona cuenta
  haber hecho (regué, sembré, cosechamos) no necesita nada: listas vacías y web_query null.
- Cultivo mencionado, o activo en el campo o zona de que se trata: su `ficha-<cultivo>`. Si la pregunta es un
  síntoma, una plaga o una enfermedad: además `plagas-<cultivo>` y, si el síntoma sugiere nutrición o agua, el
  fragmento `fisiologia-*` que corresponda. Pregunta por varios cultivos o por una zona: la ficha de cada uno.
- Fertilizar, suelo o dosis de nutrientes: `core-fertilizantes-y-enmiendas`. Aplicar un plaguicida o seguridad del
  aplicador: `core-uso-y-manejo-de-plaguicidas-mx`. Malezas resistentes: `core-resistencia-a-herbicidas-hrac`.
  Fungicidas y su momento: `core-fungicidas-eficacia-y-momento-uc`. Orgánico, certificación, inocuidad, trazabilidad:
  la guía que corresponda. Planificar hortalizas: además `inocuidad-produccion-primaria-vegetales`.
- Datos vivos solo si el tema es el estado del cultivo, un estrés, el riego, el clima o una decisión que dependa de
  ellos: `get_recent_weather_summary` (cómo fue el último mes), `get_forecast`, `get_current_weather`,
  `get_irrigation_recommendation`, `get_zone_satellite_status`, más los registros del cultivo (`list_crop_cycles`,
  `list_recent_events`). Para ver los datos del cultivo en el campo o la zona correctos, usa el nombre del campo de
  la cuenta como argumento `field`.
- web_query solo para productos, dosis, normativa o registro, precios, calendarios de siembra de la zona o plagas
  nuevas; escrita para la fuente oficial del país de la persona. Nunca para conocimiento general que ya está en
  un skill.
- No inventes nombres: si algo no está en los menús, no lo pidas. No incluyas herramientas que escriban o borren."""


@dataclass
class PreflightInputs:
    user_id: UUID
    country: str
    message: str
    account_text: str
    recent: list[tuple[str, str]]  # (role, text), oldest first
    tools: dict[str, Callable]
    skills: dict[str, Any]  # name -> ADK Skill (needs .frontmatter.description and .instructions)
    usage: TurnUsage = field(default_factory=TurnUsage)  # filled by the router call; the turn's usage continues it


@dataclass
class PreflightResult:
    block: str
    calls: list[dict] = field(default_factory=list)  # [{name, args, ok}] in the shape of ToolCallInfo
    summary: str = ""


def _tool_signature(fn: Callable) -> str:
    sig = inspect.signature(fn)
    params = ", ".join(
        p.name if p.default is inspect.Parameter.empty else f"{p.name}={p.default!r}" for p in sig.parameters.values()
    )
    doc = " ".join((fn.__doc__ or "").split())
    return f"- {fn.__name__}({params}): {doc[:150]}"


def _router_prompt(inp: PreflightInputs) -> str:
    skills = "\n".join(
        f"- {name}: {' '.join(s.frontmatter.description.split())[:240]}" for name, s in inp.skills.items()
    )
    tools = "\n".join(_tool_signature(fn) for name, fn in inp.tools.items() if name in READ_ONLY_TOOLS)
    recent = "\n".join(f"{role}: {text[:300]}" for role, text in inp.recent[-4:]) or "(conversación nueva)"
    return (
        f"## Mensaje de la persona\n{inp.message}\n\n## País de la persona\n{inp.country}\n\n"
        f"## Estado de la cuenta\n{inp.account_text}\n\n## Conversación reciente\n{recent}\n\n"
        f"## Menú de skills\n{skills}\n\n## Menú de herramientas de lectura\n{tools}"
    )


class PreflightEngine:
    def __init__(
        self, gemini, enabled: bool = True, max_tokens: int = 60000, router_timeout: float = 15.0,
        tool_timeout: float = 20.0,
    ):
        self.gemini = gemini
        self.enabled = enabled
        self.max_tokens = max_tokens
        self.router_timeout = router_timeout
        self.tool_timeout = tool_timeout

    # ------------------------------------------------------------------ plan

    async def plan(self, inp: PreflightInputs) -> Optional[PreflightPlan]:
        """The router's plan, cleaned up; None when preflight is off, the message is trivial or the router failed."""
        if not self.enabled or len(inp.message.strip()) < MIN_MESSAGE_CHARS:
            return None
        try:
            raw = await asyncio.wait_for(
                self.gemini.generate_structured(
                    inp.user_id,
                    contents=_router_prompt(inp),
                    schema=PreflightPlan,
                    system_instruction=ROUTER_INSTRUCTION,
                    model=self.gemini.lite_model,
                    thinking_level="low",  # every Gemini 3 model accepts "low"; "minimal" is only on some
                    usage_sink=inp.usage,
                ),
                timeout=self.router_timeout,
            )
        except Exception as exc:  # noqa: BLE001 - the classic agent loop still answers
            logger.warning(f"Preflight router failed ({type(exc).__name__}); falling back to the plain loop")
            return None
        plan = self.sanitize(raw, inp)
        logger.info(
            f"preflight plan skills={plan.skills} tools={[t.name for t in plan.tools]} reason={plan.reason!r}"
        )
        return plan if (plan.skills or plan.tools) else None

    @staticmethod
    def sanitize(plan: PreflightPlan, inp: PreflightInputs) -> PreflightPlan:
        """Keeps only what exists and is allowed: known skills, read-only tools with arguments that tool accepts."""
        skills = list(dict.fromkeys(n for n in plan.skills if n in inp.skills))[:MAX_SKILLS]
        requests: list[ToolRequest] = list(plan.tools)
        query = (plan.web_query or "").strip()
        if query and not any(r.name == "web_search" for r in requests):
            requests.append(ToolRequest(name="web_search", args=json.dumps({"query": query[:200]})))
        tools, seen = [], set()
        for req in requests:
            fn = inp.tools.get(req.name)
            if req.name not in READ_ONLY_TOOLS or fn is None:
                continue
            try:
                args = json.loads(req.args or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            accepted = inspect.signature(fn).parameters
            args = {k: v for k, v in args.items() if k in accepted}
            args.update(FORCED_ARGS.get(req.name, {}))
            key = (req.name, json.dumps(args, sort_keys=True, default=str))
            if key in seen:
                continue
            seen.add(key)
            tools.append(ToolRequest(name=req.name, args=json.dumps(args, ensure_ascii=False)))
        return PreflightPlan(skills=skills, tools=tools[:MAX_TOOLS], web_query=None, reason=plan.reason)

    # --------------------------------------------------------------- execute

    async def _run_tool(self, inp: PreflightInputs, req: ToolRequest) -> tuple[ToolRequest, Any]:
        args = json.loads(req.args)
        try:
            result = await asyncio.wait_for(inp.tools[req.name](**args), timeout=self.tool_timeout)
        except Exception as exc:  # noqa: BLE001 - one slow or failing tool must not sink the rest
            result = {"error": f"{type(exc).__name__}: no se pudo consultar a tiempo"}
        return req, result

    async def execute(self, inp: PreflightInputs, plan: PreflightPlan) -> PreflightResult:
        """Runs the plan's tools in parallel and builds the block, within the token budget."""
        outcomes = await asyncio.gather(*(self._run_tool(inp, req) for req in plan.tools))
        sections: list[tuple[str, str]] = []
        calls: list[dict] = []
        budget = self.max_tokens

        for req, result in outcomes:
            text = json.dumps(result, ensure_ascii=False, default=str)
            if len(text) > TOOL_RESULT_MAX_CHARS:
                text = text[:TOOL_RESULT_MAX_CHARS] + " …(recortado)"
            ok = not (isinstance(result, dict) and "error" in result)
            calls.append({"name": req.name, "args": json.loads(req.args), "ok": ok})
            title = f"Datos: {req.name}({req.args})" if req.name != "web_search" else (
                f"Búsqueda web: {json.loads(req.args).get('query', '')}"
            )
            sections.append((title, text))
            budget -= len(text) // 4

        loaded = []
        for name in plan.skills:
            text = inp.skills[name].instructions
            cost = len(text) // 4
            if cost > budget:
                logger.info(f"preflight skill {name} left out: {cost} tokens over the {budget} left")
                continue
            budget -= cost
            loaded.append(name)
            calls.append({"name": "load_skill", "args": {"skill_name": name}, "ok": True})
            sections.insert(len(loaded) - 1, (f"Skill: {name}", text))

        what = []
        if loaded:
            what.append("skills " + ", ".join(loaded))
        if outcomes:
            what.append("datos " + ", ".join(dict.fromkeys(req.name for req, _ in outcomes)))
        summary = "; ".join(what) or "nada"
        return PreflightResult(block=build_block(summary, sections), calls=calls, summary=summary)
