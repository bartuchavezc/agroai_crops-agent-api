"""Reading and correcting the tracking plans of lots.

Deterministic on purpose: this only stores what the agent decided (a whole plan, or a correction with its reason) and
keeps the history of why it changed. Planning and re-planning are the agent's job (src/agent/long_tasks)."""
from datetime import date, datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError, NotFoundError

from .models import LotTrackingPlan
from .schemas import (
    OPEN_ITEM_STATUSES, PlanItem, PlanRevise, PlanRevision, TrackingPlanContent, TrackingPlanRead, clean,
)

MAX_REVISIONS = 60  # older ones are dropped: the plan keeps the recent story of why it changed
MAX_ITEMS = 40  # a plan is a handful of key checks, never a chore list


def _read(row: LotTrackingPlan) -> TrackingPlanRead:
    return TrackingPlanRead(
        id=row.id, lot_id=row.lot_id, version=row.version, content=TrackingPlanContent.model_validate(row.content),
        revisions=[PlanRevision.model_validate(r) for r in row.revisions or []],
        last_observation_at=row.last_observation_at, created_at=row.created_at, updated_at=row.updated_at,
    )


def _window(start: Optional[date], end: Optional[date]) -> str:
    if start and end and start != end:
        return f"{start:%d/%m}–{end:%d/%m}"
    return f"{(start or end):%d/%m}" if (start or end) else "sin ventana"


class TrackingPlanService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], farm_service):
        self.session_factory = session_factory
        self.farm = farm_service

    async def _row(self, session: AsyncSession, account_id: UUID, lot_id: UUID) -> Optional[LotTrackingPlan]:
        return (await session.execute(
            select(LotTrackingPlan).where(LotTrackingPlan.account_id == account_id, LotTrackingPlan.lot_id == lot_id)
        )).scalar_one_or_none()

    async def get(self, actor: Actor, lot_id: UUID) -> Optional[TrackingPlanRead]:
        await self.farm.get_lot(actor, lot_id)  # access check
        async with self.session_factory() as session:
            row = await self._row(session, actor.account_id, lot_id)
        return _read(row) if row else None

    async def require(self, actor: Actor, lot_id: UUID) -> TrackingPlanRead:
        plan = await self.get(actor, lot_id)
        if plan is None:
            raise NotFoundError("This lot has no tracking plan yet.")
        return plan

    async def list_plans(self, actor: Actor, lot_ids: Optional[list[UUID]] = None) -> list[TrackingPlanRead]:
        async with self.session_factory() as session:
            stmt = select(LotTrackingPlan).where(LotTrackingPlan.account_id == actor.account_id)
            if lot_ids is not None:
                stmt = stmt.where(LotTrackingPlan.lot_id.in_(lot_ids))
            rows = (await session.execute(stmt)).scalars().all()
        return [_read(r) for r in rows]

    async def save(self, actor: Actor, lot_id: UUID, content: TrackingPlanContent, reason: str,
                   by: str = "agent", observation: Optional[str] = None) -> TrackingPlanRead:
        """A whole plan, written (or rewritten) by the planner. Results already gathered on items that keep their id
        are kept."""
        await self.farm.get_lot(actor, lot_id)
        if len(content.items) > MAX_ITEMS:
            raise InvalidInputError(f"Too many items ({len(content.items)}): keep the plan to the key checks "
                                    f"(at most {MAX_ITEMS}).")
        now = utcnow()
        async with self.session_factory() as session:
            row = await self._row(session, actor.account_id, lot_id)
            if row is not None:
                old = {i.id: i for i in TrackingPlanContent.model_validate(row.content).items}
                for item in content.items:
                    previous = old.get(item.id)
                    if previous and previous.result and not item.result:
                        item.result, item.status = previous.result, previous.status
            revision = PlanRevision(at=now, by=by, reason=clean(reason), observation=observation,
                                    changes=["Plan armado" if row is None else "Plan rehecho"])
            if row is None:
                row = LotTrackingPlan(account_id=actor.account_id, lot_id=lot_id, version=1, revisions=[])
                session.add(row)
            else:
                row.version += 1
            row.content = content.model_dump(mode="json")
            row.revisions = [*(row.revisions or []), revision.model_dump(mode="json")][-MAX_REVISIONS:]
            if observation:
                row.last_observation_at = now
            await session.commit()
            await session.refresh(row)
        return _read(row)

    async def revise(self, actor: Actor, lot_id: UUID, data: PlanRevise, by: str = "agent") -> TrackingPlanRead:
        """A correction: windows that move, a stage that starts, checks done, added or dropped — with its reason."""
        await self.farm.get_lot(actor, lot_id)
        now = utcnow()
        async with self.session_factory() as session:
            row = await self._row(session, actor.account_id, lot_id)
            if row is None:
                raise NotFoundError("This lot has no tracking plan yet: write one first.")
            content = TrackingPlanContent.model_validate(row.content)
            changes: list[str] = []
            stages = {s.key: s for s in content.stages}
            for change in data.stages:
                stage = stages.get(change.key)
                if stage is None:
                    raise InvalidInputError(f"No stage '{change.key}' in the plan ({', '.join(stages)}).")
                before = _window(stage.window_start, stage.window_end)
                for attr in ("window_start", "window_end", "status"):
                    value = getattr(change, attr)
                    if value is not None:
                        setattr(stage, attr, value)
                after = _window(stage.window_start, stage.window_end)
                changes.append(f"{stage.name}: {before} → {after}" if before != after else
                               f"{stage.name}: {stage.status}")
            if data.current_stage and data.current_stage != content.current_stage:
                if data.current_stage not in stages:
                    raise InvalidInputError(f"No stage '{data.current_stage}' in the plan.")
                for key, stage in stages.items():
                    if key == data.current_stage:
                        stage.status = "actual"
                    elif stage.status == "actual":
                        stage.status = "cumplida"
                changes.append(f"Etapa actual: {stages[data.current_stage].name}")
                content.current_stage = data.current_stage
            items = {i.id: i for i in content.items}
            for change in data.items:
                item = items.get(change.id)
                if item is None:
                    raise InvalidInputError(f"No item '{change.id}' in the plan.")
                values = change.model_dump(exclude_unset=True, exclude={"id"})
                for attr, value in values.items():
                    setattr(item, attr, value)
                item.updated_at = now
                changes.append(f"{item.title}: " + ", ".join(
                    f"{k}={v}" for k, v in values.items() if k not in ("result",)
                ) + (" (con resultado)" if "result" in values else ""))
            for item in data.new_items:
                item.updated_at = now
                content.items.append(item)
                changes.append(f"Nuevo: {item.title} ({_window(item.window_start, item.window_end)})")
            if data.key_moments is not None:
                content.key_moments = data.key_moments
                changes.append("Momentos clave actualizados")
            if data.missing_context is not None:
                content.missing_context = data.missing_context
            content = TrackingPlanContent.model_validate(content.model_dump())  # fresh ids for new items
            if len(content.items) > MAX_ITEMS:
                raise InvalidInputError(f"Too many items: discard done or stale ones (at most {MAX_ITEMS}).")
            revision = PlanRevision(at=now, by=by, reason=clean(data.reason), observation=data.observation,
                                    changes=changes)
            row.content = content.model_dump(mode="json")
            row.revisions = [*(row.revisions or []), revision.model_dump(mode="json")][-MAX_REVISIONS:]
            row.version += 1
            if data.observation:
                row.last_observation_at = now
            await session.commit()
            await session.refresh(row)
        return _read(row)

    async def set_item_result(self, actor: Actor, lot_id: UUID, item_id: str, status: str,
                              result: Optional[str], reason: str, by: str = "person") -> TrackingPlanRead:
        from .schemas import ItemChange

        return await self.revise(actor, lot_id, PlanRevise(
            reason=reason, observation=result, items=[ItemChange(id=item_id, status=status, result=result)],
        ), by=by)

    async def due_items(self, actor: Actor, today: date, ahead_days: int = 1,
                        plans: Optional[list[TrackingPlanRead]] = None) -> list[tuple[TrackingPlanRead, PlanItem]]:
        """Checks the person could be asked for now: open, for the person, with a window already started (or about
        to). Overdue first."""
        horizon = today + timedelta(days=ahead_days)
        out = []
        for plan in plans if plans is not None else await self.list_plans(actor):
            for item in plan.content.items:
                if item.status not in ("pendiente", "pedido") or not item.ask_user:
                    continue
                start = item.window_start or item.window_end
                if start is None or start <= horizon:
                    out.append((plan, item))
        out.sort(key=lambda pi: pi[1].window_end or pi[1].window_start or date.max)
        return out

    @staticmethod
    def open_items(plan: TrackingPlanRead) -> list[PlanItem]:
        return [i for i in plan.content.items if i.status in OPEN_ITEM_STATUSES]

    @staticmethod
    def stale(plan: TrackingPlanRead, now: Optional[datetime] = None, days: int = 10) -> bool:
        """No observation has corrected it for a while."""
        now = now or utcnow()
        last = plan.last_observation_at or plan.created_at
        return last < now - timedelta(days=days)
