"""Daily and weekly summaries of each field for everyone in the account: what was done, what was skipped and why, what
the analyses said, the weather the field had, what was applied and until when nothing can be harvested, what was lost
— and the gaps: zones nobody reported on, a dry day with no irrigation, tasks overdue, inputs running out.

This module gathers the FACTS (plain data read from the records and the weather) and saves the summary; the agent
writes it (src/agent/digests.py). `render` is the plain-text fallback when the agent can't write (no key, an error)
and the preview of the day so far. Never a made-up score."""
import logging
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.farm.models import ACTIVE_LOT_STATUSES
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import NotFoundError

from .models import Digest

logger = logging.getLogger(__name__)

STALE_ZONE_DAYS = 3
EXPIRING_DAYS = 15
EVENT_WORDS = {
    "irrigation": "riego", "fertilization": "fertilización", "pest_control": "tratamiento", "sowing": "siembra",
    "transplant": "trasplante", "harvest": "cosecha", "inspection": "revisión", "observation": "observación",
    "soil_prep": "preparación de suelo", "amendment": "enmienda", "pruning": "poda", "weeding": "desmalezado",
    "photo": "foto", "loss": "pérdida",
}


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


class DigestService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], farm_service, application_service,
        supply_service, task_service, reports_service=None, weather_service=None,
    ):
        self.session_factory = session_factory
        self.farm = farm_service
        self.applications = application_service
        self.supplies = supply_service
        self.tasks = task_service
        self.reports = reports_service
        self.weather = weather_service

    async def gather(self, actor: Actor, start: datetime, end: datetime, field=None) -> dict:
        """The facts of [start, end) as plain data: for one field when given (the summary is per field), else for the
        whole account (the preview). The agent writes the summary from this; `render` is the plain fallback."""
        tz = ZoneInfo(actor.timezone) if actor.timezone else None
        field_id = field.id if field is not None else None
        events = await self.farm.list_events(actor, field_id=field_id, since=start, until=end, limit=500)
        fields = [field] if field is not None else await self.farm.list_fields(actor)
        zones = {z.id: z for f in fields for z in await self.farm.list_zones(actor, f.id)}
        lots = await self.farm.list_lots(actor, field_id=field_id, statuses=list(ACTIVE_LOT_STATUSES))
        where = lambda zone_id: zones[zone_id].label if zone_id in zones else None  # noqa: E731

        done = Counter(EVENT_WORDS.get(e.type, e.type) for e in events
                       if e.outcome == "done" and e.type not in ("rain", "photo", "loss"))
        skipped = [
            {"what": EVENT_WORDS.get(e.type, e.type), "where": where(e.zone_id), "reason": e.reason}
            for e in events if e.outcome == "skipped"
        ]
        rain_by_day: dict[str, float] = {}
        for e in events:
            if e.type == "rain" and e.quantity:
                day = e.data.get("date") or e.occurred_at.astimezone(tz).date().isoformat()
                rain_by_day[day] = max(rain_by_day.get(day, 0.0), e.quantity)  # several fields: the wettest
        observations = [
            {"where": where(e.zone_id), "text": e.notes, "author_user_id": str(e.author_user_id or ""),
             "at": e.occurred_at.astimezone(tz).strftime("%d/%m %H:%M") if tz else e.occurred_at.isoformat()}
            for e in events if e.type in ("inspection", "observation") and e.notes
        ]
        losses = [
            {"where": where(e.zone_id), "quantity": e.quantity, "unit": e.unit, "cause": e.data.get("cause"),
             "reason": e.reason}
            for e in events if e.type == "loss"
        ]
        harvests: dict[str, float] = {}
        for e in events:
            if e.type == "harvest" and e.outcome == "done" and e.quantity:
                harvests[e.unit or "unidades"] = round(harvests.get(e.unit or "unidades", 0.0) + e.quantity, 2)

        applied = [
            {"products": [p.name for p in a.products], "lots": a.lot_labels,
             "release": a.harvest_release_date.isoformat() if a.harvest_release_date else None,
             "warnings": a.warnings}
            for a in await self.applications.list_applications(
                actor, field_id=field_id, since=start, until=end, status="confirmed"
            )
        ]
        drafts = len(await self.applications.list_applications(actor, field_id=field_id, status="draft"))
        today = end.astimezone(tz).date() if tz else end.date()
        blocked = [{"lot": lot.label, "until": lot.harvest_blocked_until.isoformat()}
                   for lot in lots if lot.harvest_blocked_until and lot.harvest_blocked_until > today]

        # gaps: zones with something growing that nobody reported on lately, and whether they were watered
        recent = await self.farm.list_events(
            actor, field_id=field_id, since=end - timedelta(days=STALE_ZONE_DAYS), until=end, limit=500
        )
        touched_zones = {e.zone_id for e in recent if e.source != "system"}
        touched_lots = {lot_id for e in recent if e.source != "system" for lot_id in e.lot_ids}
        growing_zones = {z for lot in lots if lot.status != "planned" for z in lot.zone_ids}
        quiet = sorted(
            zones[z].label for z in growing_zones
            if z in zones and z not in touched_zones
            and not any(lot.id in touched_lots for lot in lots if z in lot.zone_ids)
        )
        tasks = await self.tasks.list_tasks(actor, field_id=field_id, open_only=True)
        overdue = [t.title for t in tasks if t.due_date and t.due_date < today]
        due_today = [t.title for t in tasks if t.due_date == today]
        low = [f"{i.name} ({i.quantity:g} {i.unit})" for i in await self.supplies.list_items(actor, in_stock=False)]
        expiring = [
            f"{i.name} (vence {i.expiry_date:%d/%m})"
            for i in await self.supplies.list_items(actor, in_stock=True, expiring_within_days=EXPIRING_DAYS)
        ]
        data = {
            "done": dict(done), "skipped": skipped, "rain_mm": round(sum(rain_by_day.values()), 1),
            "rain_days": len(rain_by_day), "sightings": [o["text"] for o in observations][:5], "losses": losses,
            "harvests": harvests, "applications": applied, "application_drafts": drafts, "harvest_blocked": blocked,
            "quiet_zones": quiet, "tasks_overdue": overdue, "tasks_today": due_today, "out_of_stock": low,
            "expiring": expiring, "entries": sum(1 for e in events if e.source != "system"),
        }
        if field is None:
            return data

        data["observations"] = observations
        data["zones"] = await self._zones(actor, field, zones, lots, events, end)
        data["analyses"] = await self._analyses(actor, field.id, start, end, where)
        data["weather"] = await self._weather(field, start, end, tz)
        return data

    async def _zones(self, actor: Actor, field, zones: dict, lots: list, events: list, end: datetime) -> list[dict]:
        """Each zone with something growing: its crops, how long since anyone logged anything, and whether it was
        watered in the period (the agent crosses this with the weather to ask)."""
        crops: dict = {}
        for o in await self.farm.overview(actor):
            if o.field.id == field.id:
                for lot in o.active_lots:
                    for z in lot.zone_ids or ([lot.zone_id] if lot.zone_id else []):
                        crops.setdefault(z, []).append(lot.crop_name + (f" {lot.variety}" if lot.variety else ""))
        history = await self.farm.list_events(actor, field_id=field.id, since=end - timedelta(days=30), until=end,
                                              limit=1000)
        out = []
        for zone_id in sorted({z for lot in lots if lot.status != "planned" for z in lot.zone_ids}, key=str):
            zone = zones.get(zone_id)
            if zone is None:
                continue
            lot_ids = {lot.id for lot in lots if zone_id in lot.zone_ids}
            mine = [e for e in history if e.source != "system"
                    and (e.zone_id == zone_id or lot_ids & set(e.lot_ids))]
            last = max((e.occurred_at for e in mine), default=None)
            watered = [e for e in events if e.type == "irrigation" and e.outcome == "done"
                       and (e.zone_id == zone_id or lot_ids & set(e.lot_ids))]
            out.append({
                "zone": zone.label, "crops": crops.get(zone_id, []),
                "days_since_last_record": (end - last).days if last else None,
                "irrigated_in_period": bool(watered),
                "irrigation_skipped_in_period": any(
                    e.type == "irrigation" and e.outcome == "skipped" and e.zone_id == zone_id for e in events
                ),
            })
        return out

    async def _analyses(self, actor: Actor, field_id: UUID, start: datetime, end: datetime, where) -> list[dict]:
        if self.reports is None:
            return []
        reports = await self.reports.list_reports(actor, field_id=field_id, since=start, until=end, limit=20)
        return [
            {"type": r.report_type, "where": where(r.zone_id), "status": r.status, "title": r.title,
             "summary": (r.summary or "")[:600], "recommendations": (r.recommendations or "")[:400]}
            for r in reports
        ]

    async def _weather(self, field, start: datetime, end: datetime, tz) -> dict:
        """What the field had (Open-Meteo's estimate for the point, not a station) and what today brings."""
        if self.weather is None or field.latitude is None or field.longitude is None:
            return {}
        first, last = (start.astimezone(tz).date(), end.astimezone(tz).date()) if tz else (start.date(), end.date())
        out: dict = {}
        try:
            rows = await self.weather.open_meteo.recent_daily(field.latitude, field.longitude,
                                                              days=(datetime.now(tz).date() - first).days + 1)
            out["days"] = [r for r in rows if first.isoformat() <= r["date"] < last.isoformat()]
            forecast = await self.weather.daily_forecast(field.latitude, field.longitude, days=1)
            if forecast:
                out["today_forecast"] = forecast[0].to_dict()
        except Exception:  # noqa: BLE001 - the summary is still worth it without the weather
            logger.warning(f"No weather for the summary of field {field.id}", exc_info=True)
        return out

    @staticmethod
    def render(kind: str, data: dict) -> str:
        lines: list[str] = []
        if data["done"]:
            lines.append("Hecho: " + ", ".join(f"{n} {w}" for w, n in sorted(data["done"].items())) + ".")
        elif not data["entries"]:
            lines.append("Sin registros en la bitácora.")
        for s in data["skipped"]:
            where = f" en {s['where']}" if s["where"] else ""
            lines.append(f"No se hizo {s['what']}{where}: {s['reason']}.")
        if data["rain_mm"]:
            lines.append(f"Llovió {data['rain_mm']:g} mm en {_plural(data['rain_days'], 'día', 'días')}.")
        for a in data["applications"]:
            lots = " + ".join(a["lots"]) or "el campo"
            release = f"; no cosechar hasta el {date.fromisoformat(a['release']):%d/%m}" if a["release"] else ""
            lines.append(f"Aplicado: {', '.join(a['products'])} en {lots}{release}.")
        if data["application_drafts"]:
            lines.append(
                f"{_plural(data['application_drafts'], 'aplicación', 'aplicaciones')} sin confirmar en el registro."
            )
        for loss in data["losses"]:
            amount = f"{loss['quantity']:g} {loss['unit'] or ''}".strip() if loss["quantity"] else "una parte"
            lines.append(f"Pérdida: {amount}" + (f" ({loss['reason'] or loss['cause']})" if loss["reason"]
                                                 or loss["cause"] else "") + ".")
        if data["harvests"]:
            lines.append("Cosecha: " + ", ".join(f"{q:g} {u}" for u, q in data["harvests"].items()) + ".")
        for note in data["sightings"]:
            lines.append(f"Visto: {note}")
        gaps = []
        if data["quiet_zones"]:
            gaps.append(f"sin noticias hace {STALE_ZONE_DAYS}+ días: {', '.join(data['quiet_zones'])}")
        if data["tasks_overdue"]:
            gaps.append(f"tareas vencidas: {', '.join(data['tasks_overdue'][:4])}")
        if data["out_of_stock"]:
            gaps.append(f"sin stock: {', '.join(data['out_of_stock'][:4])}")
        if data["expiring"]:
            gaps.append(f"por vencer: {', '.join(data['expiring'][:4])}")
        if gaps:
            lines.append("Pendiente: " + "; ".join(gaps) + ".")
        if data["tasks_today"] and kind == "daily":
            lines.append(f"Para hoy: {', '.join(data['tasks_today'][:4])}.")
        if data["harvest_blocked"]:
            lines.append("En carencia: " + ", ".join(
                f"{b['lot']} hasta el {date.fromisoformat(b['until']):%d/%m}" for b in data["harvest_blocked"]
            ) + ".")
        return "\n".join(lines)

    @staticmethod
    def period(kind: str, local_day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
        """The local day `local_day`, or the week ending on it."""
        end = datetime.combine(local_day + timedelta(days=1), time(0), tzinfo=tz)
        return end - timedelta(days=7 if kind == "weekly" else 1), end

    @staticmethod
    def title(kind: str, local_day: date, field_name: Optional[str] = None) -> str:
        what = f"Resumen del {local_day:%d/%m}" if kind == "daily" else f"Resumen de la semana al {local_day:%d/%m}"
        return f"{what} · {field_name}" if field_name else what

    async def preview(self, actor: Actor, kind: str) -> Digest:
        """How today (or the week up to today) reads right now for the whole account, in plain text (not saved, no
        model call)."""
        tz = ZoneInfo(actor.timezone) if actor.timezone else ZoneInfo("UTC")
        local_day = datetime.now(tz).date()
        start, end = self.period(kind, local_day, tz)
        data = await self.gather(actor, start, min(end, utcnow()))
        return Digest(account_id=actor.account_id, kind=kind, local_date=local_day, period_start=start,
                      period_end=end, title=self.title(kind, local_day), text=self.render(kind, data), data=data)

    async def existing(self, account_id: UUID, field_id: Optional[UUID], kind: str,
                       local_day: date) -> Optional[Digest]:
        async with self.session_factory() as session:
            return (await session.execute(select(Digest).where(
                Digest.account_id == account_id, Digest.field_id == field_id, Digest.kind == kind,
                Digest.local_date == local_day,
            ))).scalar_one_or_none()

    async def save(self, actor: Actor, field_id: UUID, kind: str, local_day: date, start: datetime, end: datetime,
                   title: str, text: str, data: dict) -> Digest:
        digest = Digest(account_id=actor.account_id, field_id=field_id, kind=kind, local_date=local_day,
                        period_start=start, period_end=end, title=title, text=text, data=data)
        async with self.session_factory() as session:
            session.add(digest)
            await session.commit()
            await session.refresh(digest)
        return digest

    async def set_conversations(self, digest_id: UUID, conversations: dict[str, str]) -> Digest:
        """Where each person got it: {user_id: conversation_id}, so the summary page can open the reply."""
        async with self.session_factory() as session:
            digest = await session.get(Digest, digest_id)
            digest.data = {**digest.data, "conversations": conversations}
            await session.commit()
            await session.refresh(digest)
        return digest

    async def list_digests(self, actor: Actor, kind: Optional[str] = None, limit: int = 14,
                           field_id: Optional[UUID] = None) -> list[Digest]:
        stmt = select(Digest).where(Digest.account_id == actor.account_id)
        if kind:
            stmt = stmt.where(Digest.kind == kind)
        if field_id:
            stmt = stmt.where(Digest.field_id == field_id)
        async with self.session_factory() as session:
            return list((await session.execute(
                stmt.order_by(Digest.local_date.desc(), Digest.kind, Digest.created_at).limit(max(1, min(limit, 100)))
            )).scalars())

    async def get(self, actor: Actor, digest_id: UUID) -> Digest:
        async with self.session_factory() as session:
            digest = await session.get(Digest, digest_id)
        if digest is None or digest.account_id != actor.account_id:
            raise NotFoundError(f"Digest {digest_id} not found.")
        return digest
