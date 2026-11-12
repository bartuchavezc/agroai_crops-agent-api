"""The queue and the bookkeeping of the agent's background work. Deterministic: who runs what is the worker's
(src/agent/long_tasks/runner.py) and what to do is the agent's."""
import logging
import uuid
from datetime import timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError, NotFoundError

from .models import OPEN_TASK_STATUSES, AgentTask
from .schemas import AgentTaskRead, Todo

logger = logging.getLogger(__name__)

MAX_TRACE = 200
STALE_RUNNING = timedelta(minutes=30)  # a worker that died mid-task: it goes back to the queue
DEFAULT_CALLS = {"plan_lots": 40, "replan_lot": 20, "general": 60}
PER_LOT_CALLS = 15


class LongTaskService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def create(self, actor: Actor, kind: str, goal: str, data: Optional[dict] = None,
                     conversation_id: Optional[UUID] = None) -> AgentTaskRead:
        """Queue a task. A re-plan of a lot that is already queued absorbs the new reason instead of piling up."""
        data = dict(data or {})
        async with self.session_factory() as session:
            if kind == "replan_lot" and data.get("lot_ids"):
                wanted = sorted(str(i) for i in data["lot_ids"])
                queued = (await session.execute(
                    select(AgentTask).where(AgentTask.account_id == actor.account_id,
                                            AgentTask.kind == "replan_lot", AgentTask.status == "queued")
                )).scalars().all()
                existing = next((t for t in queued if sorted((t.input or {}).get("lot_ids") or []) == wanted), None)
                if existing is not None:
                    reasons = [*existing.input.get("observations", []), data.get("observation")]
                    existing.input = {**existing.input, "observations": [r for r in reasons if r][-5:]}
                    await session.commit()
                    await session.refresh(existing)
                    return AgentTaskRead.model_validate(existing)
                data["observations"] = [data.pop("observation")] if data.get("observation") else []
            lots = len(data.get("lot_ids") or []) or 1
            max_calls = DEFAULT_CALLS.get(kind, 40) if kind != "plan_lots" else min(150, 10 + PER_LOT_CALLS * lots)
            if data.get("lot_ids"):
                data["lot_ids"] = [str(i) for i in data["lot_ids"]]
            task = AgentTask(
                account_id=actor.account_id, user_id=actor.user_id, conversation_id=conversation_id, kind=kind,
                goal=goal.strip()[:2000], input={k: (str(v) if isinstance(v, UUID) else v) for k, v in data.items()},
                status="queued", todos=[], trace=[], max_calls=max_calls,
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)
        logger.info(f"Agent task {task.id} queued ({kind}) for account {actor.account_id}")
        return AgentTaskRead.model_validate(task)

    async def get(self, actor: Actor, task_id: UUID) -> AgentTaskRead:
        async with self.session_factory() as session:
            task = await session.get(AgentTask, task_id)
        if task is None or task.account_id != actor.account_id:
            raise NotFoundError("Task not found.")
        return AgentTaskRead.model_validate(task)

    async def list_tasks(self, actor: Actor, conversation_id: Optional[UUID] = None, open_only: bool = False,
                         limit: int = 20) -> list[AgentTaskRead]:
        async with self.session_factory() as session:
            stmt = select(AgentTask).where(AgentTask.account_id == actor.account_id)
            if conversation_id is not None:
                stmt = stmt.where(AgentTask.conversation_id == conversation_id)
            if open_only:
                stmt = stmt.where(AgentTask.status.in_(OPEN_TASK_STATUSES))
            rows = (await session.execute(stmt.order_by(AgentTask.created_at.desc()).limit(limit))).scalars().all()
        return [AgentTaskRead.model_validate(r) for r in rows]

    async def cancel(self, actor: Actor, task_id: UUID) -> AgentTaskRead:
        async with self.session_factory() as session:
            task = await session.get(AgentTask, task_id)
            if task is None or task.account_id != actor.account_id:
                raise NotFoundError("Task not found.")
            if task.status not in OPEN_TASK_STATUSES:
                raise InvalidInputError("The task already finished.")
            task.status, task.finished_at = "cancelled", utcnow()
            await session.commit()
            await session.refresh(task)
        return AgentTaskRead.model_validate(task)

    # ---------- the worker's side ----------

    async def claim_next(self, account_id: Optional[UUID] = None) -> Optional[UUID]:
        """The oldest queued task (or one whose worker died), now running. Safe with several workers."""
        now = utcnow()
        async with self.session_factory() as session:
            stmt = select(AgentTask).where(or_(
                AgentTask.status == "queued",
                (AgentTask.status == "running") & (AgentTask.updated_at < now - STALE_RUNNING),
            ))
            if account_id is not None:
                stmt = stmt.where(AgentTask.account_id == account_id)
            task = (await session.execute(
                stmt.order_by(AgentTask.created_at).limit(1).with_for_update(skip_locked=True)
            )).scalar_one_or_none()
            if task is None:
                return None
            task.status, task.attempts = "running", task.attempts + 1
            task.started_at = task.started_at or now
            await session.commit()
            return task.id

    async def load(self, task_id: UUID) -> AgentTask:
        async with self.session_factory() as session:
            task = await session.get(AgentTask, task_id)
            if task is None:
                raise NotFoundError("Task not found.")
            session.expunge(task)
            return task

    async def is_cancelled(self, task_id: UUID) -> bool:
        async with self.session_factory() as session:
            return (await session.get(AgentTask, task_id)).status == "cancelled"

    async def set_todos(self, task_id: UUID, todos: list[Todo]) -> list[Todo]:
        async with self.session_factory() as session:
            await session.execute(update(AgentTask).where(AgentTask.id == task_id).values(
                todos=[t.model_dump() for t in todos], updated_at=utcnow()))
            await session.commit()
        return todos

    async def update_todo(self, task_id: UUID, todo_id: str, status: Optional[str], note: Optional[str]) -> list[Todo]:
        task = await self.load(task_id)
        todos = [Todo.model_validate(t) for t in task.todos or []]
        todo = next((t for t in todos if t.id == todo_id), None)
        if todo is None:
            raise InvalidInputError(f"No to-do '{todo_id}' ({', '.join(t.id for t in todos)}).")
        if status:
            todo.status = status
        if note is not None:
            todo.note = note[:400]
        return await self.set_todos(task_id, todos)

    async def note(self, task_id: UUID, kind: str, text: str) -> None:
        async with self.session_factory() as session:
            task = await session.get(AgentTask, task_id)
            if task is None:
                return
            task.trace = [*(task.trace or []), {"at": utcnow().isoformat(), "kind": kind, "text": text[:1000]}][
                -MAX_TRACE:]
            await session.commit()

    async def count_calls(self, task_id: UUID, calls: int, tokens: int) -> tuple[int, int]:
        """Adds to the budget used; returns (used, max)."""
        async with self.session_factory() as session:
            task = await session.get(AgentTask, task_id)
            task.used_calls += calls
            task.tokens += tokens
            await session.commit()
            return task.used_calls, task.max_calls

    async def finish(self, task_id: UUID, status: str, result: Optional[str] = None, error: Optional[str] = None,
                     proposal_id: Optional[UUID] = None) -> None:
        async with self.session_factory() as session:
            task = await session.get(AgentTask, task_id)
            if task is None or task.status == "cancelled":
                return
            task.status, task.result, task.error, task.proposal_id = status, result, error, proposal_id
            if status in ("done", "failed"):
                task.finished_at = utcnow()
            await session.commit()

    async def resume_decided(self, decided: dict[UUID, str]) -> list[UUID]:
        """Tasks waiting on a proposal the person decided go back to the queue with what was decided."""
        if not decided:
            return []
        resumed = []
        async with self.session_factory() as session:
            rows = (await session.execute(select(AgentTask).where(
                AgentTask.status == "waiting_approval", AgentTask.proposal_id.in_(list(decided))
            ))).scalars().all()
            for task in rows:
                task.status = "queued"
                task.input = {**(task.input or {}), "resume": decided[task.proposal_id]}
                resumed.append(task.id)
            await session.commit()
        return resumed

    async def waiting_proposals(self) -> list[UUID]:
        async with self.session_factory() as session:
            return [r for r in (await session.execute(select(AgentTask.proposal_id).where(
                AgentTask.status == "waiting_approval", AgentTask.proposal_id.is_not(None)
            ))).scalars()]


def short_id() -> str:
    return uuid.uuid4().hex[:6]
