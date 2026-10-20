"""Tasks: work with someone in charge and a state, tied to a field, a zone, a lot and/or a plan. Every role adds
and updates them (staff tick their tasks day to day); deleting is manager-only. Finishing one with a
`result_event_type` logs it in the bitácora, and a transplant or sowing also moves its lot forward."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from src.application.farm.log import LogItem
from src.application.farm.schemas import FieldEventCreate, LotUpdate
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.domain.locale import today_in
from src.shared.utils.errors import InvalidInputError, NotFoundError, PermissionDeniedError

from .models import OPEN_TASK_STATUSES, Task
from .repository import TaskRepository
from .schemas import TaskCreate, TaskRead, TaskUpdate


class TaskService:
    def __init__(self, repository: TaskRepository, farm_service, management_service=None):
        self.repo = repository
        self.farm = farm_service
        self.management = management_service
        # Set by the planning service: finishing a planned lot's sowing task sows the lot (seed, stage plan).
        self.lot_sown_hook = None

    async def _resolve_place(self, actor: Actor, values: dict) -> dict:
        """Checks the field / zone / lot belong to the account and agree; fills the field from the zone or lot."""
        field_id = values.get("field_id")
        if values.get("lot_id"):
            lot = await self.farm.get_lot(actor, values["lot_id"])
            if field_id and field_id != lot.field_id:
                raise InvalidInputError("The lot is not in that field.")
            field_id = lot.field_id
        if values.get("zone_id"):
            zone = await self.farm.get_zone(actor, values["zone_id"])
            if field_id and field_id != zone.field_id:
                raise InvalidInputError("The zone is not in that field.")
            field_id = zone.field_id
        if field_id:
            await self.farm.get_field(actor, field_id)
            values["field_id"] = field_id
        if values.get("assigned_to") and self.management is not None:
            await self.management._check_assignee(actor, values["assigned_to"])
        return values

    async def list_tasks(
        self,
        actor: Actor,
        field_id=None,
        zone_id: Optional[UUID] = None,
        lot_id: Optional[UUID] = None,
        plan_id: Optional[UUID] = None,
        status: Optional[str] = None,
        open_only: bool = False,
        assigned_to=None,
    ) -> list[TaskRead]:
        lot_ids = None
        if lot_id:
            lot_ids = [lot_id]
        elif zone_id:
            lot_ids = [lot.id for lot in await self.farm.list_lots(actor, zone_id=zone_id)]
        statuses = [status] if status else (OPEN_TASK_STATUSES if open_only else None)
        rows = await self.repo.list(
            actor.account_id, field_id=field_id, zone_id=zone_id, lot_ids=lot_ids, plan_id=plan_id,
            statuses=statuses, assigned_to=assigned_to,
        )
        return [TaskRead.model_validate(t) for t in rows]

    async def get_task(self, actor: Actor, task_id: UUID) -> TaskRead:
        task = await self.repo.get(actor.account_id, task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found.")
        return TaskRead.model_validate(task)

    async def create_task(self, actor: Actor, data: TaskCreate, source: Optional[str] = None) -> TaskRead:
        values = await self._resolve_place(actor, data.model_dump())
        if values["status"] == "hecha":
            values["completed_at"] = utcnow()
        task = await self.repo.create(
            Task(
                account_id=actor.account_id, created_by=actor.user_id,
                source=source or ("agent" if actor.via == "agent" else "user"), **values,
            )
        )
        read = TaskRead.model_validate(task)
        if read.status == "hecha":
            await self._on_done(actor, read)
        return read

    async def update_task(self, actor: Actor, task_id: UUID, data: TaskUpdate) -> TaskRead:
        current = await self.get_task(actor, task_id)
        values = data.model_dump(exclude_unset=True)
        if {"field_id", "zone_id", "lot_id", "assigned_to"} & values.keys():
            merged = {k: values.get(k, getattr(current, k)) for k in ("field_id", "zone_id", "lot_id")}
            merged = await self._resolve_place(actor, {**merged, "assigned_to": values.get("assigned_to")})
            values["field_id"] = merged.get("field_id")
        finishing = values.get("status") == "hecha" and current.status != "hecha"
        if finishing:
            values["completed_at"] = utcnow()
        elif values.get("status") and values["status"] != "hecha":
            values["completed_at"] = None
        task = await self.repo.update(actor.account_id, task_id, values)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found.")
        read = TaskRead.model_validate(task)
        if finishing:
            await self._on_done(actor, read)
        return read

    async def _on_done(self, actor: Actor, task: TaskRead) -> None:
        """Logs the result in the bitácora and moves the lot forward for a sowing or a transplant."""
        if not task.result_event_type or not task.field_id:
            return
        await self.farm.create_event(
            actor,
            FieldEventCreate(
                field_id=task.field_id, zone_id=task.zone_id, lot_ids=[task.lot_id] if task.lot_id else [],
                type=task.result_event_type, occurred_at=task.completed_at, notes=task.title,
                data={"task_id": str(task.id)},
            ),
        )
        if task.lot_id and actor.is_manager and task.result_event_type in ("sowing", "transplant"):
            lot = await self.farm.get_lot(actor, task.lot_id)
            today = today_in(actor.timezone)
            changes: dict = {}
            if task.result_event_type == "sowing" and lot.status == "planned" and self.lot_sown_hook is not None:
                await self.lot_sown_hook(actor, task.lot_id)
            elif task.result_event_type == "sowing" and lot.status == "planned":
                changes = {"status": "planted", "planting_date": today}
            elif task.result_event_type == "transplant":
                changes = {"transplant_date": today, **({"status": "planted"} if lot.status in ("planned", "seedbed")
                                                       else {})}
            if changes:
                await self.farm.update_lot(actor, task.lot_id, LotUpdate(**changes))

    async def delete_task(self, actor: Actor, task_id: UUID) -> None:
        if not actor.is_manager:
            raise PermissionDeniedError("Only owner or tecnico can delete tasks.")
        if not await self.repo.delete(actor.account_id, task_id):
            raise NotFoundError(f"Task {task_id} not found.")

    async def cancel_plan_tasks(self, actor: Actor, plan_id: UUID) -> None:
        await self.repo.cancel_open_of_plan(actor.account_id, plan_id)

    async def log_items(
        self,
        actor: Actor,
        field_id: Optional[UUID] = None,
        zone_id: Optional[UUID] = None,
        lot_id: Optional[UUID] = None,
        before: Optional[datetime] = None,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> list[LogItem]:
        """Tasks done, for the bitácora (newest first)."""
        lot_ids = [lot_id] if lot_id else None
        if zone_id:
            lot_ids = [lot.id for lot in await self.farm.list_lots(actor, zone_id=zone_id)]
        rows = await self.repo.list(
            actor.account_id, field_id=field_id, zone_id=zone_id, lot_ids=lot_ids, statuses=["hecha"],
            done_before=before or utcnow(), done_since=since, limit=limit,
        )
        return [
            LogItem(
                kind="task", at=t.completed_at, title=t.title, detail=t.description, ref_id=t.id,
                type=t.result_event_type, zone_id=t.zone_id, lot_ids=[t.lot_id] if t.lot_id else [],
                source=t.source,
            )
            for t in rows if t.completed_at
        ]
