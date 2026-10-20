"""
Change sets: several writes over zones, lots, the bitácora, seeds, tasks, reminders and plans, previewed and then
applied in order through the same services the API and the agent use (so every permission and check holds).

A change set is applied operation by operation; if one fails, what the set had created is removed again and the
rest is not attempted (updates and deletes done before the failure are not reverted). Proposals are change sets the
agent prepared: stored, shown to the user with their preview, and applied or rejected by them.
"""
import uuid
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.farm.schemas import (
    FieldEventCreate,
    FieldEventUpdate,
    FieldZoneCreate,
    FieldZoneUpdate,
    LotCreate,
    LotUpdate,
)
from src.application.inventory.schemas import SeedLotCreate, SeedLotUpdate
from src.application.planning.schemas import (
    PlanCreate,
    PlanCropCreate,
    PlanUpdate,
    ReminderCreate,
    ReminderRead,
    ReminderUpdate,
    StageCreate,
    StageUpdate,
)
from src.application.tasks.schemas import TaskCreate, TaskUpdate
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import CropAnalysisError, InvalidInputError, NotFoundError

from .models import ChangeProposal
from .schemas import (
    ChangeSetPreview,
    ChangeSetResult,
    Operation,
    OperationPreview,
    OperationResult,
    ProposalRead,
)

ENTITY_LABELS = {
    "zone": "zona", "lot": "lote", "event": "bitácora", "seed_lot": "semillas", "task": "tarea",
    "reminder": "recordatorio", "plan": "plan", "plan_crop": "cultivo del plan", "stage": "etapa",
}
OP_LABELS = {"create": "Crear", "update": "Cambiar", "delete": "Borrar"}
PLACEHOLDER = "00000000-0000-0000-0000-000000000000"


def _refs(value: Any, created: dict[int, UUID]) -> Any:
    """Replaces "$N" by the id operation N created (a placeholder when previewing)."""
    if isinstance(value, str) and value.startswith("$") and value[1:].isdigit():
        n = int(value[1:])
        return str(created.get(n, PLACEHOLDER))
    if isinstance(value, list):
        return [_refs(v, created) for v in value]
    if isinstance(value, dict):
        return {k: _refs(v, created) for k, v in value.items()}
    return value


def _dump(read: Any) -> Optional[dict]:
    if read is None:
        return None
    if isinstance(read, BaseModel):
        return read.model_dump(mode="json", exclude_none=True)
    return dict(read)


def _name(data: dict) -> str:
    for key in ("title", "name", "label", "type"):
        if data.get(key):
            return str(data[key])
    return ""


class ChangeSetService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        farm_service,
        planning_service,
        task_service,
        inventory_service,
    ):
        self.session_factory = session_factory
        self.farm = farm_service
        self.planning = planning_service
        self.tasks = task_service
        self.inventory = inventory_service

    # ---------- one operation ----------

    def _handlers(self) -> dict[str, dict[str, Callable[..., Awaitable[Any]]]]:
        farm, planning, tasks, inventory = self.farm, self.planning, self.tasks, self.inventory

        async def zone_create(actor, data):
            field_id = UUID(str(data.pop("field_id")))
            return await farm.create_zone(actor, field_id, FieldZoneCreate(**data))

        async def plan_crop_create(actor, data):
            plan_id = UUID(str(data.pop("plan_id")))
            return await planning.add_plan_crop(actor, plan_id, PlanCropCreate(**data))

        async def stage_create(actor, data):
            plan_id = UUID(str(data.pop("plan_id")))
            return await planning.add_stage(actor, plan_id, StageCreate(**data))

        async def reminder_get(actor, id_):
            return ReminderRead.model_validate(await planning.get_reminder(actor, id_))

        return {
            "zone": {
                "create": zone_create,
                "update": lambda a, i, d: farm.update_zone(a, i, FieldZoneUpdate(**d)),
                "delete": farm.delete_zone, "get": farm.get_zone,
            },
            "lot": {
                "create": lambda a, d: farm.create_lot(a, LotCreate(**d)),
                "update": lambda a, i, d: farm.update_lot(a, i, LotUpdate(**d)),
                "delete": farm.delete_lot, "get": farm.get_lot,
            },
            "event": {
                "create": lambda a, d: farm.create_event(a, FieldEventCreate(**d)),
                "update": lambda a, i, d: farm.update_event(a, i, FieldEventUpdate(**d)),
                "delete": farm.delete_event, "get": farm.get_event,
            },
            "seed_lot": {
                "create": lambda a, d: inventory.add_seed_lot(a, SeedLotCreate(**d)),
                "update": lambda a, i, d: inventory.update_seed_lot(a, i, SeedLotUpdate(**d)),
                "delete": inventory.delete_seed_lot, "get": inventory.get_seed_lot,
            },
            "task": {
                "create": lambda a, d: tasks.create_task(a, TaskCreate(**d)),
                "update": lambda a, i, d: tasks.update_task(a, i, TaskUpdate(**d)),
                "delete": tasks.delete_task, "get": tasks.get_task,
            },
            "reminder": {
                "create": lambda a, d: planning.create_reminder(a, ReminderCreate(**d)),
                "update": lambda a, i, d: planning.update_reminder(a, i, ReminderUpdate(**d)),
                "delete": planning.delete_reminder, "get": reminder_get,
            },
            "plan": {
                "create": lambda a, d: planning.create_plan(a, PlanCreate(**d)),
                "update": lambda a, i, d: planning.update_plan(a, i, PlanUpdate(**d)),
                "delete": planning.delete_plan, "get": planning.get_plan,
            },
            "plan_crop": {"create": plan_crop_create, "delete": planning.delete_plan_crop},
            "stage": {
                "create": stage_create,
                "update": lambda a, i, d: planning.update_stage(a, i, StageUpdate(**d)),
                "delete": planning.delete_stage,
            },
        }

    _SCHEMAS = {
        ("zone", "create"): FieldZoneCreate, ("zone", "update"): FieldZoneUpdate,
        ("lot", "create"): LotCreate, ("lot", "update"): LotUpdate,
        ("event", "create"): FieldEventCreate, ("event", "update"): FieldEventUpdate,
        ("seed_lot", "create"): SeedLotCreate, ("seed_lot", "update"): SeedLotUpdate,
        ("task", "create"): TaskCreate, ("task", "update"): TaskUpdate,
        ("reminder", "create"): ReminderCreate, ("reminder", "update"): ReminderUpdate,
        ("plan", "create"): PlanCreate, ("plan", "update"): PlanUpdate,
        ("plan_crop", "create"): PlanCropCreate, ("stage", "create"): StageCreate, ("stage", "update"): StageUpdate,
    }
    _PARENT_KEYS = {("zone", "create"): "field_id", ("plan_crop", "create"): "plan_id", ("stage", "create"): "plan_id"}

    def _check_shape(self, op: Operation, data: dict) -> None:
        handler = self._handlers()[op.entity].get(op.op)
        if handler is None:
            raise InvalidInputError(f"{OP_LABELS[op.op]} {ENTITY_LABELS[op.entity]} is not supported.")
        if op.op != "create" and not op.id:
            raise InvalidInputError("An update or delete needs the id of what it changes.")
        parent = self._PARENT_KEYS.get((op.entity, op.op))
        if parent and not data.get(parent):
            raise InvalidInputError(f"Creating a {ENTITY_LABELS[op.entity]} needs {parent}.")
        schema = self._SCHEMAS.get((op.entity, op.op))
        if schema is not None:
            schema(**{k: v for k, v in data.items() if k != parent})

    # ---------- preview / apply ----------

    async def preview(self, actor: Actor, operations: list[Operation]) -> ChangeSetPreview:
        """Checks every operation's shape and target (nothing is written) and describes it: before / after."""
        items = []
        for index, op in enumerate(operations):
            data = _refs(op.data, {})
            item = OperationPreview(
                index=index, op=op.op, entity=op.entity, after=data or None,
                title=f"{OP_LABELS[op.op]} {ENTITY_LABELS[op.entity]}" + (f": {_name(data)}" if _name(data) else ""),
            )
            try:
                self._check_shape(op, data)
                getter = self._handlers()[op.entity].get("get")
                target = _refs(op.id, {}) if op.id else None
                if target and target != PLACEHOLDER and getter is not None:
                    before = _dump(await getter(actor, UUID(target)))
                    item.before = before
                    if before and not _name(data):
                        item.title += f": {_name(before)}"
            except ValidationError as e:
                item.error = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors())
            except (CropAnalysisError, ValueError) as e:
                item.error = getattr(e, "message", None) or str(e)
            items.append(item)
        return ChangeSetPreview(ok=not any(i.error for i in items), items=items)

    async def apply(
        self, actor: Actor, operations: list[Operation], excluded: set[int] = frozenset()
    ) -> ChangeSetResult:
        handlers = self._handlers()
        created: dict[int, UUID] = {}
        created_order: list[tuple[str, UUID]] = []
        results: list[OperationResult] = []
        failed = False
        for index, op in enumerate(operations):
            if index in excluded or failed:
                results.append(OperationResult(index=index, op=op.op, entity=op.entity, ok=False, skipped=True))
                continue
            try:
                data = _refs(op.data, created)
                if any(isinstance(v, str) and v == PLACEHOLDER for v in data.values()):
                    raise InvalidInputError("It refers to an operation that was left out.")
                self._check_shape(op, data)
                handler = handlers[op.entity][op.op]
                if op.op == "create":
                    read = await handler(actor, data)
                    created[index] = read.id
                    created_order.append((op.entity, read.id))
                    results.append(OperationResult(index=index, op=op.op, entity=op.entity, ok=True, id=read.id))
                else:
                    target = UUID(_refs(op.id, created))
                    if op.op == "update":
                        await handler(actor, target, data)
                    else:
                        await handler(actor, target)
                    results.append(OperationResult(index=index, op=op.op, entity=op.entity, ok=True, id=target))
            except ValidationError as e:
                failed = True
                results.append(OperationResult(index=index, op=op.op, entity=op.entity, ok=False, error=str(e)))
            except (CropAnalysisError, ValueError) as e:
                failed = True
                results.append(OperationResult(
                    index=index, op=op.op, entity=op.entity, ok=False, error=getattr(e, "message", None) or str(e),
                ))
        undone = False
        if failed and created_order:
            for entity, created_id in reversed(created_order):
                deleter = handlers[entity].get("delete")
                try:
                    if deleter is not None:
                        await deleter(actor, created_id)
                except Exception:  # noqa: BLE001 - best effort; report what stays
                    continue
            undone = True
            for r in results:
                if r.ok and r.op == "create":
                    r.ok, r.undone, r.error = False, True, "Deshecho: otra operación del conjunto falló."
        return ChangeSetResult(
            applied=sum(1 for r in results if r.ok),
            failed=sum(1 for r in results if not r.ok and not r.skipped and not r.undone),
            undone=undone, items=results,
        )

    # ---------- proposals ----------

    @staticmethod
    def _read(p: ChangeProposal) -> ProposalRead:
        return ProposalRead(
            id=p.id, title=p.title, status=p.status, conversation_id=p.conversation_id, operations=p.operations,
            preview=p.preview, result=p.result, created_at=p.created_at, decided_at=p.decided_at,
        )

    async def propose(
        self, actor: Actor, title: str, operations: list[Operation], conversation_id: Optional[UUID] = None
    ) -> ProposalRead:
        preview = await self.preview(actor, operations)
        proposal = ChangeProposal(
            id=uuid.uuid4(), account_id=actor.account_id, user_id=actor.user_id, conversation_id=conversation_id,
            title=title[:255], operations=[o.model_dump(mode="json") for o in operations],
            preview=[i.model_dump(mode="json") for i in preview.items], status="pending",
        )
        async with self.session_factory() as session:
            session.add(proposal)
            await session.commit()
            await session.refresh(proposal)
        return self._read(proposal)

    async def _proposal(self, session: AsyncSession, actor: Actor, proposal_id: UUID) -> ChangeProposal:
        proposal = (await session.execute(
            select(ChangeProposal).where(
                ChangeProposal.id == proposal_id, ChangeProposal.account_id == actor.account_id
            )
        )).scalar_one_or_none()
        if proposal is None:
            raise NotFoundError(f"Proposal {proposal_id} not found.")
        return proposal

    async def get_proposal(self, actor: Actor, proposal_id: UUID) -> ProposalRead:
        async with self.session_factory() as session:
            return self._read(await self._proposal(session, actor, proposal_id))

    async def decide(
        self, actor: Actor, proposal_id: UUID, apply: bool, excluded: Optional[list[int]] = None
    ) -> ProposalRead:
        async with self.session_factory() as session:
            proposal = await self._proposal(session, actor, proposal_id)
            if proposal.status != "pending":
                raise InvalidInputError("That proposal was already decided.")
            operations = [Operation(**o) for o in proposal.operations]
        result = await self.apply(actor, operations, set(excluded or [])) if apply else None
        status = "rejected" if not apply else ("failed" if result.failed else "applied")
        async with self.session_factory() as session:
            proposal = await self._proposal(session, actor, proposal_id)
            proposal.status = status
            proposal.result = result.model_dump(mode="json") if result else None
            proposal.decided_at = utcnow()
            await session.commit()
            await session.refresh(proposal)
            return self._read(proposal)

    @staticmethod
    def note(proposal: ProposalRead) -> str:
        """What the conversation keeps of the decision, so the agent knows it on the next turn."""
        result = proposal.result
        if result is None:
            return f"❌ Propuesta «{proposal.title}» descartada: no se cambió nada."
        if result.failed:
            error = next((r.error for r in result.items if r.error and not r.skipped and not r.undone), "")
            return (
                f"⚠️ La propuesta «{proposal.title}» no se pudo aplicar completa ({error}). Lo que había creado se "
                "deshizo; los cambios a registros que ya existían, hechos antes del error, quedaron."
            )
        skipped = sum(1 for r in result.items if r.skipped)
        return f"✅ Propuesta «{proposal.title}» aplicada: {result.applied} cambios" + (
            f" ({skipped} destildados por el usuario)." if skipped else "."
        )
