"""The assistant writes first.

Twice a day (and every hour for what can't wait) each account is looked at: plain code gathers OPEN signals — what
the records and the weather say, without deciding anything — and one model call per account decides whether any of it
is worth a message, to whom and what kind (ask for a data point, warn of a "no hacer", recommend, inform), or to stay
quiet. The person's own limits (messages per day, quiet hours) are applied after that decision, and every decision,
silence included, goes to the nudge log, which is also what keeps the assistant from repeating itself.

The message lands in a conversation (one per person and day) so the reply — a "sí", an audio, photos — continues
right there with the full agent, and a push notification opens it."""
import logging
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.farm.models import ACTIVE_LOT_STATUSES
from src.application.proactive.models import NudgeLog
from src.auth.domain.models import User
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.account_key import any_key_user
from src.shared.utils.errors import CropAnalysisError

from src.auth.services.tracking_profile import growing_context_lines

from .prompts.nudges import NUDGE_INSTRUCTION, build_nudge_prompt
from .prompts.voice import local_now_label, localize

logger = logging.getLogger(__name__)

Window = Literal["morning", "evening", "urgent"]
QUIET_ZONE_DAYS = 2
RECENT_DAYS = 3
FROST_C = 2.0
HEAT_C = 35.0
HEAVY_RAIN_MM = 30.0
DRAFT_STALE_HOURS = 2


class Signal(BaseModel):
    key: str  # stable: what it is about and when ("quiet_zone:<id>:<date>")
    kind: str
    text: str
    urgent: bool = False
    data: dict[str, Any] = Field(default_factory=dict)


class PlanRef(BaseModel):
    lot_id: str
    item_id: str


class NudgeMessage(BaseModel):
    recipient_user_id: str
    kind: Literal["ask", "recommend", "warn", "info"]
    title: str = Field(description="A few words for the phone notification, in Spanish")
    text: str = Field(description="The message itself, two or three short lines at most")
    signal_keys: list[str] = Field(default_factory=list)
    quick_replies: list[str] = Field(default_factory=list, description="Up to 3 one-tap answers, 1-3 words each")
    plan_ref: Optional[PlanRef] = Field(default=None, description="The tracking-plan check this message asks for")


class NudgeDecision(BaseModel):
    messages: list[NudgeMessage] = Field(default_factory=list)
    silent_reason: Optional[str] = None


class NudgeEngine:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], gemini, farm_service, application_service,
        supply_service, task_service, weather_service, alert_service, conversation_service, push_service,
        notification_service, profile_service=None, engagement_service=None, tracking_service=None,
    ):
        self.session_factory = session_factory
        self.gemini = gemini
        self.farm = farm_service
        self.applications = application_service
        self.supplies = supply_service
        self.tasks = task_service
        self.weather = weather_service
        self.alerts = alert_service
        self.conversations = conversation_service
        self.push = push_service
        self.notifications = notification_service
        self.profiles = profile_service
        self.engagement = engagement_service
        self.tracking = tracking_service

    # ---------- signals ----------

    async def signals(self, actor: Actor, now: Optional[datetime] = None) -> list[Signal]:
        """What is going on in the account, as facts. Broad on purpose: deciding is the model's job."""
        now = now or utcnow()
        tz = ZoneInfo(actor.timezone) if actor.timezone else ZoneInfo("UTC")
        today = now.astimezone(tz).date()
        out: list[Signal] = []
        fields = await self.farm.list_fields(actor)
        zones = {z.id: z for f in fields for z in await self.farm.list_zones(actor, f.id)}
        lots = await self.farm.list_lots(actor, statuses=list(ACTIVE_LOT_STATUSES))
        recent = await self.farm.list_events(actor, since=now - timedelta(days=RECENT_DAYS + 4), limit=500)

        for e in recent:
            if e.type == "rain" and e.occurred_at >= now - timedelta(hours=36):
                field = next((f.name for f in fields if f.id == e.field_id), "")
                out.append(Signal(key=f"rain:{e.field_id}:{e.data.get('date')}", kind="rain_recorded",
                                  text=f"Lluvia estimada en {field}: {e.quantity:g} mm el {e.data.get('date')}.",
                                  data={"mm": e.quantity}))

        for f in fields:
            if f.latitude is None or f.longitude is None:
                continue
            try:
                days = await self.weather.daily_forecast(f.latitude, f.longitude, days=2)
            except Exception:  # noqa: BLE001 - no forecast is no signal
                days = []
            for d in days:
                facts = []
                if d.tmin is not None and d.tmin <= FROST_C:
                    facts.append(f"mínima {d.tmin:.0f} °C")
                if d.tmax is not None and d.tmax >= HEAT_C:
                    facts.append(f"máxima {d.tmax:.0f} °C")
                if d.precipitation_mm:
                    facts.append(f"lluvia {d.precipitation_mm:.0f} mm")
                if d.max_wind_speed is not None and d.max_wind_speed >= 8:
                    facts.append(f"viento hasta {d.max_wind_speed:.0f} m/s")
                if facts:
                    urgent = (d.tmin is not None and d.tmin <= FROST_C) or (d.precipitation_mm or 0) >= HEAVY_RAIN_MM
                    out.append(Signal(key=f"forecast:{f.id}:{d.date.isoformat()}", kind="forecast", urgent=urgent,
                                      text=f"Pronóstico {f.name} {d.date:%d/%m}: " + ", ".join(facts) + ".",
                                      data=d.to_dict()))

        human = [e for e in recent if e.source != "system"]
        for zone_id in {z for lot in lots if lot.status != "planned" for z in lot.zone_ids}:
            zone = zones.get(zone_id)
            if zone is None:
                continue
            lot_ids = {lot.id for lot in lots if zone_id in lot.zone_ids}
            last = max((e.occurred_at for e in human if e.zone_id == zone_id or lot_ids & set(e.lot_ids)),
                       default=None)
            if last is None or last < now - timedelta(days=QUIET_ZONE_DAYS):
                days = (now - last).days if last else None
                out.append(Signal(key=f"quiet_zone:{zone_id}:{today.isoformat()}", kind="no_news",
                                  text=f"{zone.label}: sin registros hace " + (f"{days} días." if days else
                                                                                "más de una semana.")))

        for e in human:
            if e.outcome == "skipped" and e.occurred_at >= now - timedelta(hours=36):
                out.append(Signal(key=f"skipped:{e.id}", kind="skipped",
                                  text=f"No se hizo {e.type}: {e.reason}."))
            if e.type == "loss" and e.occurred_at >= now - timedelta(hours=36):
                out.append(Signal(key=f"loss:{e.id}", kind="loss",
                                  text=f"Pérdida registrada: {e.quantity:g} {e.unit or ''} ({e.reason or ''})."))

        for t in await self.tasks.list_tasks(actor, open_only=True):
            if t.due_date and t.due_date <= today + timedelta(days=1):
                when = "vencida" if t.due_date < today else "hoy" if t.due_date == today else "mañana"
                out.append(Signal(key=f"task:{t.id}:{today.isoformat()}", kind="task",
                                  text=f"Tarea {when}: {t.title}.", data={"assigned_to": str(t.assigned_to or "")}))

        for lot in lots:
            if lot.harvest_blocked_until and today <= lot.harvest_blocked_until <= today + timedelta(days=1):
                out.append(Signal(key=f"withholding_ends:{lot.id}:{lot.harvest_blocked_until}", kind="withholding",
                                  text=f"{lot.label}: la carencia termina el {lot.harvest_blocked_until:%d/%m}."))
            if lot.expected_harvest_date and today <= lot.expected_harvest_date <= today + timedelta(days=3):
                out.append(Signal(key=f"harvest_soon:{lot.id}", kind="harvest_soon",
                                  text=f"{lot.label}: cosecha esperada el {lot.expected_harvest_date:%d/%m}"
                                  + (f" (en carencia hasta el {lot.harvest_blocked_until:%d/%m})"
                                     if lot.harvest_blocked_until and lot.harvest_blocked_until > today else "")
                                  + "."))

        for draft in await self.applications.list_applications(actor, status="draft"):
            if draft.created_at < now - timedelta(hours=DRAFT_STALE_HOURS):
                out.append(Signal(key=f"draft:{draft.id}", kind="application_draft",
                                  text="Aplicación sin confirmar en el registro: "
                                  + ", ".join(p.name for p in draft.products) + "."))

        for item in await self.supplies.list_items(actor, in_stock=False):
            out.append(Signal(key=f"no_stock:{item.id}", kind="stock", text=f"Sin stock: {item.name}."))
        for item in await self.supplies.list_items(actor, in_stock=True, expiring_within_days=7):
            out.append(Signal(key=f"expiring:{item.id}", kind="stock",
                              text=f"Vence pronto: {item.name} ({item.expiry_date:%d/%m})."))

        for alert in (await self.alerts.get_active_alerts(actor))[:5]:
            out.append(Signal(key=f"alert:{alert.id}", kind="alert", urgent=alert.severity in ("high", "critical"),
                              text=f"Alerta [{alert.severity}]: {alert.message}"))
        out += await self._plan_signals(actor, lots, today, now)
        out += self._sowing_signals(fields, zones, lots, today)
        return out

    async def _plan_signals(self, actor: Actor, lots, today, now: datetime) -> list[Signal]:
        """What the agent's own tracking plans say: checks due, key moments about to come, plans no observation has
        corrected for a while (the drift the person can fix with one photo)."""
        if self.tracking is None:
            return []
        labels = {lot.id: lot.label or "lote" for lot in lots}
        plans = await self.tracking.list_plans(actor, list(labels))
        out = []
        for plan, item in (await self.tracking.due_items(actor, today, plans=plans))[:6]:
            overdue = item.window_end is not None and item.window_end < today
            out.append(Signal(
                key=f"plan_check:{plan.lot_id}:{item.id}:{today.isoformat()}", kind="plan_check",
                text=f"{labels.get(plan.lot_id)}: chequeo «{item.title}» ({item.section}"
                     + (", vencido" if overdue else "") + f"). Cómo: {item.how} Por qué: {item.why}"
                     + (f" Necesita: {item.requires_tool} (si no lo tiene: {item.alternative})."
                        if item.requires_tool else ""),
                data={"lot_id": str(plan.lot_id), "item_id": item.id, "method": item.method,
                      "status": item.status},
            ))
        for plan in plans:
            label = labels.get(plan.lot_id)
            for moment in plan.content.key_moments:
                start = moment.window_start or moment.window_end
                if start and today <= start <= today + timedelta(days=3):
                    out.append(Signal(key=f"moment:{plan.lot_id}:{moment.key}", kind="key_moment",
                                      text=f"{label}: se acerca «{moment.name}» (desde el {start:%d/%m})"
                                           + (f": {moment.why}" if moment.why else "."),
                                      data={"lot_id": str(plan.lot_id)}))
            if self.tracking.stale(plan, now):
                out.append(Signal(key=f"plan_stale:{plan.lot_id}:{today.isocalendar()[1]}", kind="plan_drift",
                                  text=f"{label}: el plan lleva más de 10 días sin una observación que lo confirme "
                                       f"(etapa estimada: {plan.content.current_stage or 'sin dato'}).",
                                  data={"lot_id": str(plan.lot_id)}))
        missing = [lot for lot in lots if lot.status != "planned" and lot.id not in {p.lot_id for p in plans}]
        if missing:
            out.append(Signal(key=f"no_plan:{today.isoformat()}", kind="no_plan",
                              text="Lotes sin plan de seguimiento todavía: "
                                   + ", ".join(labels[lot.id] for lot in missing[:5]) + "."))
        return out

    @staticmethod
    def _sowing_signals(fields, zones, lots, today) -> list[Signal]:
        """Room to sow: zones with nothing growing, and the date — for «hoy es buen día para sembrar…» the model
        crosses it with the season, the region and the forecast."""
        busy = {z for lot in lots for z in lot.zone_ids}
        free = [z for z in zones.values() if z.id not in busy]
        if not free:
            return []
        names = ", ".join(z.label for z in free[:6])
        return [Signal(key=f"free_zones:{today.isocalendar()[1]}", kind="sowing_room",
                       text=f"Zonas sin cultivo ahora: {names}. Fecha: {today:%d/%m} (para ver qué conviene sembrar "
                            "según la época, la región y el pronóstico).")]

    # ---------- decision ----------

    async def _recent_log(self, account_id: UUID, now: datetime) -> list[NudgeLog]:
        async with self.session_factory() as session:
            return list((await session.execute(
                select(NudgeLog).where(NudgeLog.account_id == account_id,
                                       NudgeLog.created_at >= now - timedelta(days=RECENT_DAYS))
                .order_by(NudgeLog.created_at)
            )).scalars())

    async def run_account(self, members: list[User], window: Window, now: Optional[datetime] = None) -> list[NudgeLog]:
        now = now or utcnow()
        owner = next((m for m in members if m.role == "owner"), members[0])
        actor = replace(Actor.from_user(owner), via="system")
        signals = await self.signals(actor, now)
        said = await self._recent_log(owner.account_id, now)
        spoken = {k for log in said if log.outcome == "sent" for k in log.signal_keys or []}
        fresh = [s for s in signals if s.key not in spoken]
        if window == "urgent":
            fresh = [s for s in fresh if s.urgent]
        if not fresh:
            return []

        people = []
        for m in members:
            left, quiet = await self.push.nudge_budget_left(m, now)
            people.append({"id": str(m.id), "name": " ".join(p for p in (m.first_name, m.last_name) if p) or m.email,
                           "role": m.role, "left": left, "quiet": quiet, "user": m,
                           **await self._person_profile(m, now)})
        if not any(p["left"] for p in people):
            return [await self._log(owner.account_id, None, window, fresh, "budget", reason="Sin mensajes disponibles")]

        holder = await any_key_user(self.gemini, members)
        if holder is None:
            return [await self._log(owner.account_id, None, window, fresh, "failed", reason="Sin API key de Gemini")]
        tz = ZoneInfo(owner.timezone) if owner.timezone else ZoneInfo("UTC")
        try:
            decision: NudgeDecision = await self.gemini.generate_structured(
                holder.id,
                contents=build_nudge_prompt(people, fresh, said, local_now_label(now.astimezone(tz))),
                schema=NudgeDecision,
                system_instruction=localize(NUDGE_INSTRUCTION, owner.country),
                thinking_level="low",
            )
        except CropAnalysisError as e:
            return [await self._log(owner.account_id, None, window, fresh, "failed", reason=e.message)]

        if not decision.messages:
            return [await self._log(owner.account_id, None, window, fresh, "silent", reason=decision.silent_reason)]
        logs = []
        by_id = {p["id"]: p for p in people}
        for msg in decision.messages[: len(people)]:
            person = by_id.get(msg.recipient_user_id)
            if person is None:
                continue
            urgent = any(s.urgent for s in fresh if s.key in msg.signal_keys)
            if person["left"] <= 0:
                logs.append(await self._log(owner.account_id, person["user"].id, window, fresh, "budget", msg))
                continue
            if person["quiet"] and not urgent:
                logs.append(await self._log(owner.account_id, person["user"].id, window, fresh, "quiet_hours", msg))
                continue
            if msg.kind == "ask" and person.get("asks_left", 1) <= 0 and not urgent:
                logs.append(await self._log(owner.account_id, person["user"].id, window, fresh, "budget", msg,
                                            reason="Sin pedidos de datos disponibles esta semana (intensidad "
                                                   f"{person.get('intensity')})"))
                continue
            logs.append(await self._deliver(person["user"], window, fresh, msg, now))
            person["left"] -= 1
        return logs

    async def _person_profile(self, user: User, now: datetime) -> dict:
        """How to talk to this person and how much asking is left: their profile's guide, the tracking intensity
        they chose (and the weekly data requests it allows) and how they have actually been answering."""
        out: dict = {}
        if self.profiles is not None:
            try:
                context = await self.profiles.get_profile_context(user.id)
                tracking = await self.profiles.tracking_profile(user.id)
            except Exception:  # noqa: BLE001 - a missing profile is just the default voice
                logger.exception(f"No profile for {user.id}")
            else:
                out["profile"] = context.calculated_profile if context else None
                out["intensity"] = tracking.intensity
                out["weekly_asks"] = tracking.weekly_asks
                out["means"] = growing_context_lines(tracking)[1:]
        if self.engagement is not None:
            try:
                engagement = await self.engagement.summary(user.id, user.timezone, now)
            except Exception:  # noqa: BLE001
                logger.exception(f"No engagement summary for {user.id}")
            else:
                out["engagement"] = engagement.line()
                if "weekly_asks" in out:
                    out["asks_left"] = max(out["weekly_asks"] - engagement.asks_this_week, 0)
        return out

    async def _deliver(self, user: User, window: Window, signals: list[Signal], msg: NudgeMessage,
                       now: datetime) -> NudgeLog:
        actor = Actor.from_user(user)
        tz = ZoneInfo(user.timezone) if user.timezone else ZoneInfo("UTC")
        local_day = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.session_factory() as session:
            today = (await session.execute(
                select(NudgeLog.conversation_id).where(
                    NudgeLog.user_id == user.id, NudgeLog.outcome == "sent", NudgeLog.created_at >= local_day,
                    NudgeLog.conversation_id.is_not(None),
                ).order_by(NudgeLog.created_at.desc()).limit(1)
            )).scalar_one_or_none()
        conversation_id = await self.conversations.post_nudge(
            actor, today, title=f"Avisos del {now.astimezone(tz):%d/%m}", text=msg.text,
        )
        log = await self._log(user.account_id, user.id, window, signals, "sent", msg, conversation_id)
        replies = [r.strip()[:24] for r in msg.quick_replies if r.strip()][:3]
        extra = None
        if replies:
            extra = {"nudge_id": str(log.id), "reply_token": self.push.reply_token(log.id),
                     "actions": [{"action": f"r{i}", "title": r} for i, r in enumerate(replies)],
                     "replies": replies}
        await self.notifications.notify_account(
            account_id=user.account_id, exclude_user_id=None, only_user_id=user.id, type="nudge",
            title=msg.title, message=msg.text, entity_type="conversation", entity_id=conversation_id,
            push_extra=extra,
        )
        if msg.plan_ref and self.tracking is not None:
            try:
                from src.application.tracking.schemas import ItemChange, PlanRevise

                await self.tracking.revise(actor, UUID(msg.plan_ref.lot_id), PlanRevise(
                    reason=f"Pedido a la persona: «{msg.title}»",
                    items=[ItemChange(id=msg.plan_ref.item_id, status="pedido")],
                ), by="system")
            except Exception:  # noqa: BLE001 - a stale reference must not lose the message
                logger.warning(f"Could not mark plan item {msg.plan_ref} as asked")
        return log

    async def _log(self, account_id: UUID, user_id: Optional[UUID], window: Window, signals: list[Signal],
                   outcome: str, msg: Optional[NudgeMessage] = None, conversation_id: Optional[UUID] = None,
                   reason: Optional[str] = None) -> NudgeLog:
        log = NudgeLog(
            account_id=account_id, user_id=user_id, window=window,
            signals=[s.model_dump() for s in signals], signal_keys=msg.signal_keys if msg else [],
            outcome=outcome, kind=msg.kind if msg else None, message=msg.text if msg else None,
            reason=reason, conversation_id=conversation_id,
            quick_replies=[r.strip()[:24] for r in msg.quick_replies if r.strip()][:3] if msg else [],
            plan_ref=msg.plan_ref.model_dump() if msg and msg.plan_ref else None,
        )
        async with self.session_factory() as session:
            session.add(log)
            await session.commit()
            await session.refresh(log)
        return log

    # ---------- the job ----------

    async def accounts(self) -> dict[UUID, list[User]]:
        async with self.session_factory() as session:
            users = (await session.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
        out: dict[UUID, list[User]] = {}
        for user in users:
            out.setdefault(user.account_id, []).append(user)
        return out

    async def run(self, window: Window, now: Optional[datetime] = None) -> dict:
        sent = silent = failed = 0
        for account_id, members in (await self.accounts()).items():
            try:
                for log in await self.run_account(members, window, now):
                    sent += log.outcome == "sent"
                    silent += log.outcome == "silent"
            except Exception:  # noqa: BLE001 - one account must not stop the rest
                failed += 1
                logger.exception(f"Nudge check failed for account {account_id}")
        logger.info(f"Nudges ({window}): {sent} sent, {silent} silent, {failed} failed")
        return {"sent": sent, "silent": silent, "failed": failed}
