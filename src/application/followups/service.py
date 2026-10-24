"""
Follow-ups (seguimientos): a problem being watched — "pulgón en tomate" — and the bitácora entries about it.

The follow-up only holds what is being watched and whether it is still open; everything that happened (seen,
treated, better, resolved) is a bitácora entry with `followup_id` and its evidence, so it shows in the field's,
zone's and lots' bitácora like any other entry. Opening and closing each write their own entry.
"""
from datetime import datetime
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.farm.models import FieldEvent, FollowUp
from src.application.farm.schemas import EventEvidence, FieldEventCreate, FieldEventRead
from src.application.farm.service import FarmService
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError, NotFoundError, PermissionDeniedError

from .capture_plan import capture_plan
from .schemas import CapturePlan, FollowUpClose, FollowUpCreate, FollowUpDetail, FollowUpRead, FollowUpUpdate

# `data.followup_action` of the entries a follow-up writes: what each one was in its life.
OPENED, EVALUATED, RESOLVED, DISMISSED = "opened", "evaluated", "resolved", "dismissed"


def summarize(followup: FollowUp, events: Sequence[FieldEventRead]) -> dict:
    """The read model's derived fields, from its entries (newest first)."""
    evolution = next((e.data["evolution"] for e in events if (e.data or {}).get("evolution")), None)
    photo = next(
        ((ev.identifier, e.occurred_at) for e in events for ev in e.evidence if ev.kind == "photo"), (None, None)
    )
    return {
        **FollowUpRead.model_validate(followup).model_dump(exclude={"last_evolution", "last_photo", "entries"}),
        "last_evolution": evolution,
        "last_photo": photo[0],
        "last_photo_at": photo[1],
        "entries": len(events),
    }


class FollowUpService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], farm_service: FarmService):
        self.session_factory = session_factory
        self.farm = farm_service

    # ---------- reads ----------

    async def _row(self, actor: Actor, followup_id: UUID) -> FollowUp:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(FollowUp).where(FollowUp.id == followup_id, FollowUp.account_id == actor.account_id)
                )
            ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"Follow-up {followup_id} not found.")
        return row

    async def _events_by_followup(self, actor: Actor, ids: list[UUID]) -> dict[UUID, list[FieldEventRead]]:
        if not ids:
            return {}
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(FieldEvent)
                    .where(FieldEvent.account_id == actor.account_id, FieldEvent.followup_id.in_(ids))
                    .order_by(FieldEvent.occurred_at.desc(), FieldEvent.id.desc())
                )
            ).scalars().all()
        out: dict[UUID, list[FieldEventRead]] = {i: [] for i in ids}
        for event in await self.farm.event_reads(rows):
            out[event.followup_id].append(event)
        return out

    async def list_followups(
        self,
        actor: Actor,
        field_id: Optional[UUID] = None,
        zone_id: Optional[UUID] = None,
        status: Optional[str] = None,
    ) -> list[FollowUpRead]:
        stmt = select(FollowUp).where(FollowUp.account_id == actor.account_id)
        if field_id:
            stmt = stmt.where(FollowUp.field_id == field_id)
        if zone_id:
            stmt = stmt.where(FollowUp.zone_id == zone_id)
        if status:
            stmt = stmt.where(FollowUp.status == status)
        async with self.session_factory() as session:
            rows = (await session.execute(stmt.order_by(FollowUp.created_at.desc()))).scalars().all()
        events = await self._events_by_followup(actor, [r.id for r in rows])
        return [FollowUpRead(**summarize(r, events[r.id])) for r in rows]

    async def get(self, actor: Actor, followup_id: UUID) -> FollowUpDetail:
        row = await self._row(actor, followup_id)
        events = (await self._events_by_followup(actor, [row.id]))[row.id]
        return FollowUpDetail(**summarize(row, events), events=events)

    # ---------- writes ----------

    async def _check_place(
        self, actor: Actor, field_id: UUID, zone_id: Optional[UUID], lot_ids: list[UUID]
    ) -> None:
        await self.farm.get_field(actor, field_id)
        if zone_id and (await self.farm.get_zone(actor, zone_id)).field_id != field_id:
            raise InvalidInputError("The zone does not belong to that field.")
        for lot_id in lot_ids:
            if (await self.farm.get_lot(actor, lot_id)).field_id != field_id:
                raise InvalidInputError("A lot does not belong to that field.")

    async def create(self, actor: Actor, data: FollowUpCreate) -> FollowUpDetail:
        lot_ids = list(dict.fromkeys(data.lot_ids))
        await self._check_place(actor, data.field_id, data.zone_id, lot_ids)
        if data.zone_id is None and lot_ids:
            data = data.model_copy(update={"zone_id": (await self.farm.get_lot(actor, lot_ids[0])).zone_id})
        row = FollowUp(
            account_id=actor.account_id,
            field_id=data.field_id,
            zone_id=data.zone_id,
            lot_ids=[str(i) for i in lot_ids],
            title=data.title.strip(),
            kind=data.kind,
            severity=data.severity,
            photo_hint=(data.photo_hint or "").strip() or None,
            status="abierto",
            source=actor.via,
            origin_report_id=data.origin_report_id,
            created_by=actor.user_id,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        notes = f"Se detectó: {row.title}" + (f". {data.notes.strip()}" if (data.notes or "").strip() else "")
        await self.write_entry(actor, row, notes, {"followup_action": OPENED, "severity": row.severity},
                               data.evidence, data.origin_report_id)
        return await self.get(actor, row.id)

    async def write_entry(
        self, actor: Actor, followup: FollowUp | FollowUpRead, notes: str, data: dict, evidence=(),
        report_id: Optional[UUID] = None, occurred_at: Optional[datetime] = None,
    ) -> FieldEventRead:
        """A bitácora entry about this follow-up, on its zone and lots: an `inspection` (a check-up: seen,
        evaluated, resolved). The analysis it came from, if any, is added to its evidence."""
        evidence = [EventEvidence.model_validate(e) for e in evidence]
        if report_id and not any(e.kind == "report" and e.identifier == str(report_id) for e in evidence):
            evidence.append(EventEvidence(kind="report", identifier=str(report_id)))
        return await self.farm.create_event(actor, FieldEventCreate(
            field_id=followup.field_id,
            zone_id=followup.zone_id,
            lot_ids=[UUID(str(i)) for i in followup.lot_ids],
            type="inspection",
            occurred_at=occurred_at,
            notes=notes,
            data=data,
            followup_id=followup.id,
            evidence=evidence,
        ))

    def _check_editable(self, actor: Actor, row: FollowUp) -> None:
        if not actor.is_manager and row.created_by != actor.user_id:
            raise PermissionDeniedError("Only a manager or whoever opened it can change this follow-up.")

    async def update(self, actor: Actor, followup_id: UUID, data: FollowUpUpdate) -> FollowUpDetail:
        row = await self._row(actor, followup_id)
        self._check_editable(actor, row)
        values = data.model_dump(exclude_unset=True)
        if data.lot_ids is not None:
            await self._check_place(actor, row.field_id, None, data.lot_ids)
            values["lot_ids"] = [str(i) for i in dict.fromkeys(data.lot_ids)]
        async with self.session_factory() as session:
            row = await session.get(FollowUp, row.id)
            for key, value in values.items():
                setattr(row, key, value)
            await session.commit()
        return await self.get(actor, followup_id)

    async def close(self, actor: Actor, followup_id: UUID, data: FollowUpClose) -> FollowUpDetail:
        """Any member can close it — it is a check-up like any other — but only an open one."""
        row = await self._row(actor, followup_id)
        if row.status != "abierto":
            raise InvalidInputError("This follow-up is already closed.")
        verb = "Resuelto" if data.status == "resuelto" else "Descartado"
        notes = f"{verb}: {row.title}" + (f". {data.notes.strip()}" if (data.notes or "").strip() else "")
        action = RESOLVED if data.status == "resuelto" else DISMISSED
        await self.write_entry(actor, row, notes, {"followup_action": action}, data.evidence, data.origin_report_id)
        async with self.session_factory() as session:
            row = await session.get(FollowUp, row.id)
            row.status, row.closed_at = data.status, utcnow()
            await session.commit()
        return await self.get(actor, followup_id)

    # ---------- guided walk ----------

    async def capture_plan(self, actor: Actor, field_id: UUID) -> CapturePlan:
        """What a guided walk of this field asks for, zone by zone (see capture_plan.py)."""
        zones = await self.farm.list_zones(actor, field_id)
        overview = next((o for o in await self.farm.overview(actor) if o.field.id == field_id), None)
        lots = overview.active_lots if overview else []
        followups = await self.list_followups(actor, field_id=field_id, status="abierto")
        return capture_plan(field_id, zones, lots, followups)
