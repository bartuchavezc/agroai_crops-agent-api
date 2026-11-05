"""Runs the agent's background tasks (the `tasks` worker in src/batch.py).

An orchestrator agent keeps a visible to-do list and hands each heavy piece to a subagent with its own, throw-away
context (the lot planner loads its crop sheets and manuals, uses the models, writes the plan and returns only a
summary) — the same pattern coding harnesses use to keep the main context small. Every model call counts against the
task's budget (the person's own Gemini key). Writes to the person's data go through a proposal; the task then waits
for the decision and resumes, with its conversation intact, from where it stopped."""
import logging
import uuid
from dataclasses import replace
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from google.adk.agents import LlmAgent, RunConfig
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from sqlalchemy import select

from src.application.changes.models import ChangeProposal
from src.auth.domain.models import User
from src.auth.services.tracking_profile import growing_context_lines
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import CropAnalysisError, InvalidInputError

from ..prompts.knowledge import short_style
from ..prompts.knowledge_skills import specific_manuals_toolset
from ..prompts.long_tasks import LOT_PLANNER_INSTRUCTION, ORCHESTRATOR_INSTRUCTION, planner_context
from ..prompts.voice import local_now_label, voice_for
from ..tools import TurnContext, build_tools
from ..tools.context import tool
from .schemas import Todo
from .service import LongTaskService, short_id

logger = logging.getLogger(__name__)

APP_NAME = "agroai_tasks"
SUBAGENT_MAX_CALLS = 25

# What the lot planner may use: reading the farm, the models, the weather and soil, and its own plan.
PLANNER_TOOLS = {
    "list_fields", "get_farm_snapshot", "list_lots", "list_zones", "list_recent_events", "get_log",
    "get_field_soil_context", "get_field_sun_exposure", "find_crop_in_catalog", "get_forecast",
    "get_recent_weather_summary", "list_active_alerts", "list_followups", "get_followup", "recall_facts",
    "get_water_balance", "get_thermal_time", "get_zone_light", "get_disease_risk", "get_zone_satellite_status",
    "get_tracking_plan", "save_tracking_plan", "revise_tracking_plan", "list_seed_inventory",
}
# The orchestrator reads and proposes; it never writes the person's data directly.
ORCHESTRATOR_TOOLS = {
    "list_fields", "get_farm_snapshot", "list_lots", "list_zones", "list_recent_events", "get_log",
    "find_crop_in_catalog", "get_forecast", "list_tracking_plans", "get_tracking_plan", "propose_changes",
    "recall_facts", "list_followups",
}


class BudgetExceeded(Exception):
    pass


def _hit_call_limit(error: BaseException) -> bool:
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if type(error).__name__ == "LlmCallsLimitExceededError" or "llm calls limit" in str(error).lower():
            return True
        error = error.__cause__ or error.__context__
    return False


class LongTaskRunner:
    def __init__(self, tasks: LongTaskService, agent_runner, session_factory, profile_service):
        self.tasks = tasks
        self.agent = agent_runner  # AgentRunner: models (user's key), tool deps, conversations
        self.session_factory = session_factory
        self.profiles = profile_service
        self.sessions = agent_runner.sessions  # persistent ADK sessions: a task resumes with its history

    # ---------- the worker ----------

    async def run_once(self, account_id: Optional[UUID] = None) -> Optional[UUID]:
        """Resume tasks whose proposal was decided, then run the next queued task (of one account, if given).
        Returns its id, if any."""
        await self._resume_decided()
        task_id = await self.tasks.claim_next(account_id)
        if task_id is None:
            return None
        try:
            await self.run(task_id)
        except Exception as e:  # noqa: BLE001 - one task must never stop the worker
            logger.exception(f"Agent task {task_id} failed")
            await self.tasks.note(task_id, "error", f"{type(e).__name__}: {e}")
            await self.tasks.finish(task_id, "failed", error=str(e)[:500])
        return task_id

    async def run_all(self, limit: int = 20) -> int:
        done = 0
        while done < limit and await self.run_once() is not None:
            done += 1
        return done

    async def _resume_decided(self) -> None:
        waiting = await self.tasks.waiting_proposals()
        if not waiting:
            return
        async with self.session_factory() as session:
            rows = (await session.execute(select(ChangeProposal).where(
                ChangeProposal.id.in_(waiting), ChangeProposal.status != "pending"
            ))).scalars().all()
        await self.tasks.resume_decided({p.id: p.status for p in rows})

    async def _actor(self, user_id: UUID) -> Actor:
        async with self.session_factory() as session:
            user = await session.get(User, user_id)
        if user is None or not user.is_active:
            raise InvalidInputError("The person who asked for this task is no longer active.")
        return replace(Actor.from_user(user), via="agent")

    # ---------- one task ----------

    async def run(self, task_id: UUID) -> None:
        task = await self.tasks.load(task_id)
        actor = await self._actor(task.user_id)
        try:
            api_key = await self.agent.gemini.api_key_for(actor.user_id)
        except CropAnalysisError as e:
            await self.tasks.finish(task_id, "failed", error=e.message)
            return
        state = {"proposal_id": None}
        tz = self.agent._tz_for(actor)
        ctx = TurnContext(actor=actor, conversation_id=task.conversation_id or task.id, tz=tz)
        allowed = ORCHESTRATOR_TOOLS if task.conversation_id else ORCHESTRATOR_TOOLS - {"propose_changes"}
        tools = [t for t in build_tools(self.agent.tool_deps, ctx) if t.__name__ in allowed]
        tools += self._orchestrator_tools(task_id, actor, api_key, tz, state)
        agent = LlmAgent(
            name="agroai_orchestrator", model=self.agent._model(api_key),
            instruction=ORCHESTRATOR_INSTRUCTION + "\n\n" + voice_for(actor.country),
            tools=tools, generate_content_config=self.agent.gemini.chat_generation_config(),
        )
        message = self._opening(task, tz) if not (task.input or {}).get("resume") else self._resume_note(task)
        await self.tasks.note(task_id, "start", "Retomo: " + task.input["resume"] if (task.input or {}).get(
            "resume") else f"Empiezo: {task.goal}")
        session_id = str(task.id)
        if await self.sessions.get_session(app_name=APP_NAME, user_id=str(actor.user_id),
                                           session_id=session_id) is None:
            await self.sessions.create_session(app_name=APP_NAME, user_id=str(actor.user_id), session_id=session_id)
        runner = Runner(app=App(name=APP_NAME, root_agent=agent), session_service=self.sessions)
        try:
            text = await self._drive(task_id, runner, actor, session_id, message, task.max_calls)
        except BudgetExceeded:
            await self.tasks.note(task_id, "budget", "Se agotó el presupuesto de llamadas de la tarea.")
            await self._close_open_todos(task_id, "sin presupuesto")
            await self.tasks.finish(task_id, "failed", error="Se agotó el presupuesto de llamadas al modelo.")
            await self._post(task, actor, "No llegué a terminar esta tarea: se agotó el presupuesto de llamadas. "
                                          "Lo que alcancé a hacer quedó guardado.")
            return
        if await self.tasks.is_cancelled(task_id):
            return
        if state["proposal_id"]:
            await self.tasks.finish(task_id, "waiting_approval", result=text, proposal_id=state["proposal_id"])
            await self._post(task, actor, text or "Te dejé una propuesta para confirmar; sigo cuando decidas.",
                             proposal_id=state["proposal_id"])
            return
        await self._close_open_todos(task_id, None)
        await self.tasks.finish(task_id, "done", result=text)
        if text:
            await self._post(task, actor, text)

    def _opening(self, task, tz: ZoneInfo) -> types.Content:
        data = task.input or {}
        lines = [f"Fecha y hora local: {local_now_label(utcnow().astimezone(tz))}.", f"Tarea: {task.goal}"]
        if data.get("lot_ids"):
            lines.append("Lotes: " + ", ".join(data["lot_ids"]))
        if data.get("replan"):
            lines.append("Es una replanificación: corregí los planes existentes con lo nuevo, sin perder lo ya "
                         "observado.")
        for obs in data.get("observations") or []:
            lines.append(f"Observación que lo dispara: {obs}")
        if data.get("reason"):
            lines.append(f"Motivo: {data['reason']}")
        return types.Content(role="user", parts=[types.Part(text="\n".join(lines))])

    @staticmethod
    def _resume_note(task) -> types.Content:
        decided = task.input.get("resume")
        word = {"applied": "aplicó", "rejected": "rechazó", "failed": "no pudo aplicar"}.get(decided, decided)
        return types.Content(role="user", parts=[types.Part(
            text=f"La persona {word} la propuesta {task.proposal_id}. Seguí con la tarea desde donde quedaste.")])

    async def _drive(self, task_id: UUID, runner: Runner, actor: Actor, session_id: str,
                     message: types.Content, max_calls: int, count_into: Optional[dict] = None) -> str:
        """Runs one agent to the end, counting its model calls against the task's budget."""
        text_parts: list[str] = []
        task = await self.tasks.load(task_id)
        left = max(1, task.max_calls - task.used_calls)
        try:
            await self._consume(task_id, runner, actor, session_id, message, min(left, max_calls), text_parts)
        except BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001 - ADK wraps the call-limit error; anything else propagates
            if _hit_call_limit(e):
                raise BudgetExceeded() from e
            raise
        return "".join(text_parts[-1:]).strip() if text_parts else ""

    async def _consume(self, task_id: UUID, runner: Runner, actor: Actor, session_id: str, message: types.Content,
                       max_calls: int, text_parts: list[str]) -> None:
        async for event in runner.run_async(
            user_id=str(actor.user_id), session_id=session_id, new_message=message,
            run_config=RunConfig(max_llm_calls=max_calls),
        ):
            if event.partial:
                continue
            if event.author != "user" and event.content is not None and event.content.role == "model":
                tokens = 0
                if event.usage_metadata is not None:
                    tokens = (event.usage_metadata.prompt_token_count or 0) + \
                        (event.usage_metadata.candidates_token_count or 0)
                used, limit = await self.tasks.count_calls(task_id, 1, tokens)
                if used > limit:
                    raise BudgetExceeded()
                for part in event.content.parts or []:
                    if part.text and not part.thought:
                        text_parts.append(part.text)
                    if part.function_call is not None:
                        await self.tasks.note(task_id, "tool", part.function_call.name)
            if await self.tasks.is_cancelled(task_id):
                break

    async def _close_open_todos(self, task_id: UUID, note: Optional[str]) -> None:
        task = await self.tasks.load(task_id)
        todos = [Todo.model_validate(t) for t in task.todos or []]
        changed = False
        for t in todos:
            if t.status in ("pending", "in_progress"):
                t.status, t.note, changed = "skipped", note or t.note or "no hizo falta", True
        if changed:
            await self.tasks.set_todos(task_id, todos)

    async def _post(self, task, actor: Actor, text: str, proposal_id: Optional[UUID] = None) -> None:
        """The result goes where the person asked for it (or to a new conversation for automatic ones)."""
        if not text:
            return
        attachments = [{"type": "proposal", "proposal_id": str(proposal_id), "caption": "Propuesta de la tarea"}] \
            if proposal_id else None
        try:
            await self.agent.conversations.post_nudge(
                replace(actor, via="user"), task.conversation_id, title=task.goal[:80], text=text,
                attachments=attachments,
            )
        except Exception:  # noqa: BLE001 - the task's own record already has the result
            logger.exception(f"Could not post the result of task {task.id}")

    # ---------- the orchestrator's own tools ----------

    def _orchestrator_tools(self, task_id: UUID, actor: Actor, api_key: str, tz: ZoneInfo, state: dict) -> list:
        tasks = self.tasks

        @tool
        async def write_todos(items: list[str]) -> dict:
            """Your to-do list for this task: short, concrete steps in order (one per lot or piece of work).
            Replaces the current list. Mark each with update_todo as you go."""
            todos = [Todo(id=short_id(), title=str(t)[:160]) for t in items if str(t).strip()]
            await tasks.set_todos(task_id, todos)
            return {"todos": [t.model_dump() for t in todos]}

        @tool
        async def update_todo(todo_id: str, status: str, note: Optional[str] = None) -> dict:
            """Mark a step: in_progress | done | skipped (say why in note)."""
            todos = await tasks.update_todo(task_id, todo_id, status, note)
            return {"todos": [t.model_dump() for t in todos]}

        @tool
        async def run_subagent(kind: str, lot_id: str, instructions: str) -> dict:
            """Hand one lot to a subagent with its own context. kind: lot_planner (writes or corrects that lot's
            tracking plan with the crop sheet, the manuals and the models). instructions: what to do and why (what
            changed, which observation corrects it). Returns its short summary."""
            if kind != "lot_planner":
                raise InvalidInputError("Only kind=lot_planner exists for now.")
            summary = await self.run_planner(task_id, actor, api_key, tz, UUID(lot_id), instructions)
            await tasks.note(task_id, "subagent", f"lot_planner {lot_id}: {summary[:300]}")
            return {"lot_id": lot_id, "summary": summary}

        @tool
        async def wait_for_approval(proposal_id: str) -> dict:
            """After propose_changes: the task pauses until the person confirms or rejects that proposal, and then
            continues from here. End your turn right after with one line saying what you are waiting for."""
            state["proposal_id"] = UUID(proposal_id)
            await tasks.note(task_id, "approval", f"Espera la propuesta {proposal_id}")
            return {"waiting": True}

        return [write_todos, update_todo, run_subagent, wait_for_approval]

    # ---------- the lot planner ----------

    async def run_planner(self, task_id: UUID, actor: Actor, api_key: str, tz: ZoneInfo, lot_id: UUID,
                          instructions: str) -> str:
        lot = await self.agent.tool_deps.farm.get_lot(actor, lot_id)  # access check before spending calls
        tracking = await self.profiles.tracking_profile(actor.user_id)
        context = await self.profiles.get_profile_context(actor.user_id)
        instruction = "\n\n".join([
            LOT_PLANNER_INSTRUCTION,
            planner_context(growing_context_lines(tracking),
                            short_style(context.calculated_profile if context else None)),
            voice_for(actor.country),
        ])
        ctx = TurnContext(actor=actor, conversation_id=task_id, tz=tz, default_field_id=lot.field_id)
        tools = [t for t in build_tools(self.agent.tool_deps, ctx) if t.__name__ in PLANNER_TOOLS]
        agent = LlmAgent(
            name="lot_planner", model=self.agent._model(api_key),
            instruction=instruction, tools=[*tools, specific_manuals_toolset()],
            generate_content_config=self.agent.gemini.chat_generation_config(),
        )
        sessions = InMemorySessionService()  # its context lives only while it works
        session_id = uuid.uuid4().hex
        await sessions.create_session(app_name="lot_planner", user_id=str(actor.user_id), session_id=session_id)
        runner = Runner(app=App(name="lot_planner", root_agent=agent), session_service=sessions)
        message = types.Content(role="user", parts=[types.Part(text=(
            f"Fecha local: {local_now_label(utcnow().astimezone(tz))}.\nLote: {lot_id} ({lot.label or ''}).\n"
            f"{instructions}"))])
        return await self._drive(task_id, runner, actor, session_id, message, SUBAGENT_MAX_CALLS) or \
            "El subagente terminó sin resumen."
