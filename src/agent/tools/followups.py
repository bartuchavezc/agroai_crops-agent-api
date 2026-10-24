"""Follow-up tools (seguimientos): problems being watched in a zone or on some lots — "pulgón en tomate" — from the
chat, the same ones the web's zone page and the zone analysis use. A follow-up holds what is watched and whether it
is still open; its history is bitácora entries pointing at it (detected, treated, better, resolved), each with its
evidence. Any member can open one, add entries and close it; editing it is for a manager or whoever opened it."""
from typing import Optional
from uuid import UUID

from src.application.farm.schemas import FieldEventUpdate
from src.application.followups.schemas import FollowUpClose, FollowUpCreate, FollowUpUpdate
from src.shared.utils.errors import InvalidInputError

from .context import ToolDeps, TurnContext, compact, parse_when, resolve_field, resolve_zone, tool

EVOLUTIONS = ("mejor", "igual", "peor", "no_visible")


def _summary(f) -> dict:
    return compact({
        "followup_id": str(f.id), "title": f.title, "kind": f.kind, "severity": f.severity, "status": f.status,
        "zone_id": f.zone_id and str(f.zone_id), "lot_ids": [str(i) for i in f.lot_ids], "since": f.created_at.date(),
        "photo_hint": f.photo_hint, "last_evolution": f.last_evolution,
        "last_photo_at": f.last_photo_at and f.last_photo_at.date(), "entries": f.entries, "opened_by": f.source,
    })


def followup_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    def _turn_evidence(attach_current_photo: bool) -> list[dict]:
        evidence = []
        if attach_current_photo:
            if not ctx.image_identifier:
                raise InvalidInputError("There is no photo in this message to attach.")
            evidence.append({"kind": "photo", "identifier": ctx.image_identifier})
        if ctx.audio_identifier:
            evidence.append({"kind": "audio", "identifier": ctx.audio_identifier, "note": "audio del turno"})
        return evidence

    @tool
    async def list_followups(field: Optional[str] = None, zone: Optional[str] = None, status: str = "abierto") -> dict:
        """The problems being followed (seguimientos) of a field or one zone ('cantero 2'): what, since when, how it
        went at its last evaluation, when it was last photographed. status: abierto (default) | resuelto |
        descartado | all. Look here before opening a new one, and when an application or a check-up may be about
        one of them."""
        target = await resolve_field(deps, ctx, field)
        zone_id = (await resolve_zone(deps, ctx, target, zone)).id if zone else None
        items = await deps.followups.list_followups(
            ctx.actor, field_id=target.id, zone_id=zone_id, status=None if status == "all" else status
        )
        return {"followups": [_summary(f) for f in items], "field_name": target.name}

    @tool
    async def get_followup(followup_id: str) -> dict:
        """One follow-up and its whole history, oldest first: detected, treated, evaluated (better / same / worse /
        not seen), closed — to answer "¿cómo viene el pulgón?", "¿qué le hicimos?"."""
        detail = await deps.followups.get(ctx.actor, UUID(followup_id))
        return {
            **_summary(detail),
            "history": [
                compact({
                    "event_id": str(e.id), "date": e.occurred_at.date(), "type": e.type, "notes": e.notes,
                    "evolution": (e.data or {}).get("evolution"), "by": e.source,
                    "photos": sum(1 for ev in e.evidence if ev.kind == "photo") or None,
                    "from_analysis": next((ev.identifier for ev in e.evidence if ev.kind == "report"), None),
                })
                for e in reversed(detail.events)
            ],
        }

    @tool
    async def open_followup(
        title: str,
        field: Optional[str] = None,
        zone: Optional[str] = None,
        lots: Optional[list[str]] = None,
        kind: str = "pest",
        severity: str = "medium",
        photo_hint: Optional[str] = None,
        notes: Optional[str] = None,
        attach_current_photo: bool = False,
    ) -> dict:
        """Start following a problem the person saw or a photo shows ("tengo pulgón en los tomates del cajón 1"):
        writes its first bitácora entry ("Se detectó: …"). Check list_followups first: if it is already being
        followed, add an entry to that one instead.
        - title: short, problem + crop ("Pulgón en tomate"). kind: pest | disease | deficiency | other.
          severity: low | medium | high | critical.
        - zone ('cajón 1') and/or lots (lot ids): where. photo_hint: what to photograph to follow it ("envés de las
          hojas de arriba"): the guided walk asks for exactly that.
        - notes: what was seen. attach_current_photo: the photo of this message as its evidence."""
        target = await resolve_field(deps, ctx, field)
        zone_id = (await resolve_zone(deps, ctx, target, zone)).id if zone else None
        created = await deps.followups.create(ctx.actor, FollowUpCreate(
            field_id=target.id, zone_id=zone_id, lot_ids=[UUID(str(i)) for i in lots or []], title=title,
            kind=kind, severity=severity, photo_hint=photo_hint, notes=notes,
            evidence=_turn_evidence(attach_current_photo),
        ))
        return {"opened": _summary(created)}

    @tool
    async def update_followup(
        followup_id: str,
        title: Optional[str] = None,
        kind: Optional[str] = None,
        severity: Optional[str] = None,
        photo_hint: Optional[str] = None,
        lots: Optional[list[str]] = None,
    ) -> dict:
        """Fix what a follow-up is about: its title, kind, severity, what to photograph, the lots affected (the whole
        list). Its history isn't touched: what happened goes in add_followup_entry."""
        values = {"title": title, "kind": kind, "severity": severity, "photo_hint": photo_hint}
        values = {k: v for k, v in values.items() if v is not None}
        if lots is not None:
            values["lot_ids"] = [UUID(str(i)) for i in lots]
        updated = await deps.followups.update(ctx.actor, UUID(followup_id), FollowUpUpdate(**values))
        return {"followup": _summary(updated)}

    @tool
    async def add_followup_entry(
        followup_id: str,
        notes: str,
        evolution: Optional[str] = None,
        event_type: str = "inspection",
        occurred_at: Optional[str] = None,
        attach_current_photo: bool = False,
    ) -> dict:
        """Add to a follow-up's history what the person saw or did about it ("hoy el pulgón está mucho mejor",
        "le saqué las hojas afectadas"): a bitácora entry on its zone and lots.
        - evolution (when it's a check-up): mejor | igual | peor | no_visible — only from what the person said or the
          photo shows, never assumed.
        - event_type: inspection (a check-up, default) | observation | pruning | weeding | other bitácora types.
          A phytosanitary or fertilizer APPLICATION goes through record_application with followup_id instead.
        - attach_current_photo: the photo of this message as its evidence."""
        if evolution is not None and evolution not in EVOLUTIONS:
            raise InvalidInputError(f"evolution must be one of: {', '.join(EVOLUTIONS)}.")
        followup = await deps.followups.get(ctx.actor, UUID(followup_id))
        if followup.status != "abierto":
            raise InvalidInputError("That follow-up is closed. Open a new one if the problem came back.")
        data = {"followup_action": "evaluated" if evolution else "noted"}
        if evolution:
            data["evolution"] = evolution
        entry = await deps.followups.write_entry(
            ctx.actor, followup, notes, data, _turn_evidence(attach_current_photo),
            occurred_at=parse_when(occurred_at, ctx.tz), event_type=event_type,
        )
        return {"logged": compact({"event_id": str(entry.id), "type": entry.type, "evolution": evolution})}

    @tool
    async def close_followup(
        followup_id: str, status: str = "resuelto", notes: Optional[str] = None, attach_current_photo: bool = False,
    ) -> dict:
        """Close a follow-up: resuelto (it's gone) or descartado (it wasn't what it seemed). ONLY when the person
        says so in a message of their own — the analysis may propose it, but closing is the person's call. Writes its
        closing bitácora entry."""
        if status not in ("resuelto", "descartado"):
            raise InvalidInputError("status must be resuelto or descartado.")
        closed = await deps.followups.close(ctx.actor, UUID(followup_id), FollowUpClose(
            status=status, notes=notes, evidence=_turn_evidence(attach_current_photo),
        ))
        return {"closed": _summary(closed)}

    @tool
    async def link_to_followup(followup_id: str, event_ids: list[str]) -> dict:
        """Join bitácora entries already logged to a follow-up's history ("el riego con purín de ortiga de ayer era
        por el pulgón"). For an application record use link_application_to_followup (it links its entry too)."""
        followup = await deps.followups.get(ctx.actor, UUID(followup_id))
        linked = []
        for event_id in event_ids:
            event = await deps.farm.update_event(ctx.actor, UUID(event_id), FieldEventUpdate(followup_id=followup.id))
            linked.append(str(event.id))
        return {"linked": linked, "followup": followup.title}

    return [
        list_followups, get_followup, open_followup, update_followup, add_followup_entry, close_followup,
        link_to_followup,
    ]

