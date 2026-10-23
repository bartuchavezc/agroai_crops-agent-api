"""Daily and weekly summaries for whoever isn't at the field: what was done, what was skipped and why, how much it
rained, what was applied and until when nothing can be harvested, what was lost — and the gaps: zones nobody
reported on, tasks overdue, inputs running out. Facts read from the records, never a made-up score."""
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
        supply_service, task_service, notification_service, preferences,
    ):
        self.session_factory = session_factory
        self.farm = farm_service
        self.applications = application_service
        self.supplies = supply_service
        self.tasks = task_service
        self.notifications = notification_service
        self.preferences = preferences

    async def gather(self, actor: Actor, start: datetime, end: datetime) -> dict:
        """The facts of [start, end) for the account, as plain data (the text is built from it)."""
        tz = ZoneInfo(actor.timezone) if actor.timezone else None
        events = await self.farm.list_events(actor, since=start, until=end, limit=500)
        zones = {z.id: z for f in await self.farm.list_fields(actor) for z in await self.farm.list_zones(actor, f.id)}
        lots = await self.farm.list_lots(actor, statuses=list(ACTIVE_LOT_STATUSES))

        done = Counter(EVENT_WORDS.get(e.type, e.type) for e in events
                       if e.outcome == "done" and e.type not in ("rain", "photo", "loss"))
        skipped = [
            {"what": EVENT_WORDS.get(e.type, e.type), "where": zones[e.zone_id].label if e.zone_id in zones else None,
             "reason": e.reason}
            for e in events if e.outcome == "skipped"
        ]
        rain_by_day: dict[str, float] = {}
        for e in events:
            if e.type == "rain" and e.quantity:
                day = e.data.get("date") or e.occurred_at.astimezone(tz).date().isoformat()
                rain_by_day[day] = max(rain_by_day.get(day, 0.0), e.quantity)  # several fields: the wettest
        sightings = [e.notes for e in events if e.type in ("inspection", "observation") and e.notes][:5]
        losses = [
            {"quantity": e.quantity, "unit": e.unit, "cause": e.data.get("cause"), "reason": e.reason}
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
            for a in await self.applications.list_applications(actor, since=start, until=end, status="confirmed")
        ]
        drafts = len(await self.applications.list_applications(actor, status="draft"))
        today = end.astimezone(tz).date() if tz else end.date()
        blocked = [{"lot": lot.label, "until": lot.harvest_blocked_until.isoformat()}
                   for lot in lots if lot.harvest_blocked_until and lot.harvest_blocked_until > today]

        # gaps: zones with something growing that nobody reported on lately
        recent = await self.farm.list_events(actor, since=end - timedelta(days=STALE_ZONE_DAYS), limit=500)
        touched_zones = {e.zone_id for e in recent if e.source != "system"}
        touched_lots = {lot_id for e in recent if e.source != "system" for lot_id in e.lot_ids}
        growing_zones = {z for lot in lots if lot.status != "planned" for z in lot.zone_ids}
        quiet = sorted(
            zones[z].label for z in growing_zones
            if z in zones and z not in touched_zones
            and not any(lot.id in touched_lots for lot in lots if z in lot.zone_ids)
        )
        tasks = await self.tasks.list_tasks(actor, open_only=True)
        overdue = [t.title for t in tasks if t.due_date and t.due_date < today]
        due_today = [t.title for t in tasks if t.due_date == today]
        low = [f"{i.name} ({i.quantity:g} {i.unit})" for i in await self.supplies.list_items(actor, in_stock=False)]
        expiring = [
            f"{i.name} (vence {i.expiry_date:%d/%m})"
            for i in await self.supplies.list_items(actor, in_stock=True, expiring_within_days=EXPIRING_DAYS)
        ]
        return {
            "done": dict(done), "skipped": skipped, "rain_mm": round(sum(rain_by_day.values()), 1),
            "rain_days": len(rain_by_day), "sightings": sightings, "losses": losses, "harvests": harvests,
            "applications": applied, "application_drafts": drafts, "harvest_blocked": blocked,
            "quiet_zones": quiet, "tasks_overdue": overdue, "tasks_today": due_today, "out_of_stock": low,
            "expiring": expiring, "entries": sum(1 for e in events if e.source != "system"),
        }

    @staticmethod
    def render(kind: str, data: dict) -> str:
        lines: list[str] = []
        if data["done"]:
            lines.append("Hecho: " + ", ".join(f"{n} {w}" for w, n in sorted(data["done"].items())) + ".")
        elif not data["entries"]:
            lines.append("Nadie cargó nada en la bitácora.")
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

    def _period(self, kind: str, local_day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
        end = datetime.combine(local_day + timedelta(days=1), time(0), tzinfo=tz)
        return end - timedelta(days=7 if kind == "weekly" else 1), end

    async def build(self, actor: Actor, kind: str, local_day: Optional[date] = None, save: bool = True,
                    notify: bool = True) -> Optional[Digest]:
        """The summary of that local day (or the week ending that day). Saved once per account, kind and day: a
        second call returns the saved one."""
        tz = ZoneInfo(actor.timezone) if actor.timezone else ZoneInfo("UTC")
        local_day = local_day or datetime.now(tz).date()
        if save:
            existing = await self._existing(actor.account_id, kind, local_day)
            if existing is not None:
                return existing
        start, end = self._period(kind, local_day, tz)
        data = await self.gather(actor, start, min(end, utcnow()))
        title = (f"Resumen del {local_day:%d/%m}" if kind == "daily"
                 else f"Resumen de la semana al {local_day:%d/%m}")
        digest = Digest(account_id=actor.account_id, kind=kind, local_date=local_day, period_start=start,
                        period_end=end, title=title, text=self.render(kind, data), data=data)
        if not save:
            return digest
        async with self.session_factory() as session:
            session.add(digest)
            await session.commit()
            await session.refresh(digest)
        if notify:
            await self._notify(actor, digest)
        return digest

    async def _existing(self, account_id: UUID, kind: str, local_day: date) -> Optional[Digest]:
        async with self.session_factory() as session:
            return (await session.execute(select(Digest).where(
                Digest.account_id == account_id, Digest.kind == kind, Digest.local_date == local_day
            ))).scalar_one_or_none()

    async def _notify(self, actor: Actor, digest: Digest) -> None:
        recipients = await self.preferences.digest_recipients(actor.account_id, digest.kind)
        first_line = digest.text.splitlines()[0] if digest.text else ""
        for user_id in recipients:
            await self.notifications.notify_account(
                account_id=actor.account_id, exclude_user_id=None, only_user_id=user_id,
                type="digest", title=digest.title, message=first_line, entity_type="digest", entity_id=digest.id,
            )

    async def list_digests(self, actor: Actor, kind: Optional[str] = None, limit: int = 14) -> list[Digest]:
        stmt = select(Digest).where(Digest.account_id == actor.account_id)
        if kind:
            stmt = stmt.where(Digest.kind == kind)
        async with self.session_factory() as session:
            return list((await session.execute(
                stmt.order_by(Digest.local_date.desc(), Digest.kind).limit(max(1, min(limit, 100)))
            )).scalars())

    async def get(self, actor: Actor, digest_id: UUID) -> Digest:
        async with self.session_factory() as session:
            digest = await session.get(Digest, digest_id)
        if digest is None or digest.account_id != actor.account_id:
            raise NotFoundError(f"Digest {digest_id} not found.")
        return digest
