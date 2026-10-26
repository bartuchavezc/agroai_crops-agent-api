"""Reaching the phone: Web Push to every browser a person allowed, and what each person wants to be told.

Web Push needs nothing from a store: the browser (Chrome on Android, Safari on iPhone with the app added to the home
screen) gives a subscription, and we sign each message with our VAPID key. A subscription the push service says is
gone (404/410) is dropped; a notification is always in the app as well, so a missed push loses nothing."""
import asyncio
import json
import logging
from datetime import datetime, time
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.auth.domain.models import User
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow

from .models import NotificationPreferences, NudgeLog, PushSubscription

logger = logging.getLogger(__name__)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    keys: dict[str, str] = Field(description="{p256dh, auth} as the browser's PushSubscription.toJSON() gives them")
    user_agent: Optional[str] = Field(default=None, max_length=255)


class PreferencesRead(BaseModel):
    nudges_enabled: bool = True
    max_nudges_per_day: int = 2
    quiet_start: str = "21:00"
    quiet_end: str = "07:30"
    daily_digest: bool
    weekly_digest: bool
    push_enabled: bool = True
    push_devices: int = 0


class PreferencesUpdate(BaseModel):
    nudges_enabled: Optional[bool] = None
    max_nudges_per_day: Optional[int] = Field(default=None, ge=0, le=6)
    quiet_start: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_end: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    daily_digest: Optional[bool] = None
    weekly_digest: Optional[bool] = None
    push_enabled: Optional[bool] = None


def _clock(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def in_quiet_hours(now_local: datetime, start: str, end: str) -> bool:
    """Quiet hours may cross midnight (21:00 → 07:30)."""
    t, a, b = now_local.time(), _clock(start), _clock(end)
    return (a <= t or t < b) if a > b else (a <= t < b)


class PushService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], config: dict):
        self.session_factory = session_factory
        self.public_key = config.get("vapid_public_key") or ""
        self.private_key = config.get("vapid_private_key") or ""
        self.subject = config.get("vapid_subject") or "mailto:soporte@agroai.app"
        self.base_url = (config.get("web_base_url") or "").rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.public_key and self.private_key)

    # ---------- preferences ----------

    async def _prefs(self, session: AsyncSession, user_id: UUID) -> Optional[NotificationPreferences]:
        return await session.get(NotificationPreferences, user_id)

    async def preferences(self, actor: Actor) -> PreferencesRead:
        async with self.session_factory() as session:
            prefs = await self._prefs(session, actor.user_id)
            devices = (await session.execute(
                select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == actor.user_id)
            )).scalar_one()
        if prefs is None:
            return PreferencesRead(daily_digest=True, weekly_digest=True, push_devices=devices)
        return PreferencesRead(
            nudges_enabled=prefs.nudges_enabled, max_nudges_per_day=prefs.max_nudges_per_day,
            quiet_start=prefs.quiet_start, quiet_end=prefs.quiet_end,
            daily_digest=True if prefs.daily_digest is None else prefs.daily_digest,
            weekly_digest=True if prefs.weekly_digest is None else prefs.weekly_digest,
            push_enabled=prefs.push_enabled, push_devices=devices,
        )

    async def update_preferences(self, actor: Actor, data: PreferencesUpdate) -> PreferencesRead:
        async with self.session_factory() as session:
            prefs = await self._prefs(session, actor.user_id)
            if prefs is None:
                prefs = NotificationPreferences(user_id=actor.user_id)
                session.add(prefs)
            for key, value in data.model_dump(exclude_unset=True).items():
                setattr(prefs, key, value)
            await session.commit()
        return await self.preferences(actor)

    async def digest_recipients(self, account_id: UUID, kind: str) -> list[UUID]:
        """Who gets a daily/weekly summary: everyone in the account, unless they turned it off."""
        async with self.session_factory() as session:
            rows = (await session.execute(
                select(User, NotificationPreferences)
                .outerjoin(NotificationPreferences, NotificationPreferences.user_id == User.id)
                .where(User.account_id == account_id, User.is_active.is_(True))
            )).all()
        out = []
        for user, prefs in rows:
            chosen = getattr(prefs, f"{kind}_digest", None) if prefs is not None else None
            if chosen is None or chosen:
                out.append(user.id)
        return out

    async def nudge_budget_left(self, user: User, now: Optional[datetime] = None) -> tuple[int, bool]:
        """(nudges still allowed today, whether now is inside the person's quiet hours)."""
        tz = ZoneInfo(user.timezone) if user.timezone else ZoneInfo("UTC")
        now_local = (now or utcnow()).astimezone(tz)
        async with self.session_factory() as session:
            prefs = await self._prefs(session, user.id)
            if prefs is not None and not prefs.nudges_enabled:
                return 0, False
            day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            sent = (await session.execute(
                select(func.count()).select_from(NudgeLog).where(
                    NudgeLog.user_id == user.id, NudgeLog.outcome == "sent", NudgeLog.created_at >= day_start
                )
            )).scalar_one()
        limit = prefs.max_nudges_per_day if prefs is not None else 2
        start, end = (prefs.quiet_start, prefs.quiet_end) if prefs else ("21:00", "07:30")
        quiet = in_quiet_hours(now_local, start, end)
        return max(limit - sent, 0), quiet

    # ---------- subscriptions ----------

    async def subscribe(self, actor: Actor, data: PushSubscriptionIn) -> int:
        async with self.session_factory() as session:
            existing = (await session.execute(
                select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)
            )).scalar_one_or_none()
            if existing is None:
                existing = PushSubscription(endpoint=data.endpoint)
                session.add(existing)
            existing.user_id, existing.account_id = actor.user_id, actor.account_id
            existing.p256dh, existing.auth = data.keys.get("p256dh", ""), data.keys.get("auth", "")
            existing.user_agent, existing.failures = data.user_agent, 0
            await session.commit()
            return (await session.execute(
                select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == actor.user_id)
            )).scalar_one()

    async def unsubscribe(self, actor: Actor, endpoint: str) -> None:
        async with self.session_factory() as session:
            await session.execute(delete(PushSubscription).where(
                PushSubscription.user_id == actor.user_id, PushSubscription.endpoint == endpoint
            ))
            await session.commit()

    # ---------- sending ----------

    def _send_one(self, subscription: dict, payload: str) -> Optional[int]:
        from pywebpush import WebPushException, webpush  # only needed when push is configured

        try:
            webpush(subscription_info=subscription, data=payload, vapid_private_key=self.private_key,
                    vapid_claims={"sub": self.subject}, ttl=12 * 3600, timeout=10)
            return None
        except WebPushException as e:
            return getattr(e.response, "status_code", 0) or 0

    async def send(self, user_ids: list[UUID], title: str, body: str, url: str, tag: Optional[str] = None) -> int:
        """Push to every device of those users (who didn't turn push off). Returns how many devices got it."""
        if not self.enabled or not user_ids:
            return 0
        async with self.session_factory() as session:
            rows = (await session.execute(
                select(PushSubscription)
                .outerjoin(NotificationPreferences, NotificationPreferences.user_id == PushSubscription.user_id)
                .where(PushSubscription.user_id.in_(user_ids),
                       func.coalesce(NotificationPreferences.push_enabled, True).is_(True))
            )).scalars().all()
        payload = json.dumps({"title": title, "body": body[:240], "url": url, "tag": tag}, ensure_ascii=False)
        delivered = 0
        for sub in rows:
            info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
            status = await asyncio.to_thread(self._send_one, info, payload)
            async with self.session_factory() as session:
                current = await session.get(PushSubscription, sub.id)
                if current is None:
                    continue
                if status is None:
                    current.last_success_at, current.failures = utcnow(), 0
                    delivered += 1
                elif status in (404, 410):
                    await session.delete(current)
                else:
                    current.failures += 1
                    logger.warning(f"Web push to {sub.id} failed with {status}")
                await session.commit()
        return delivered

    def url_for(self, entity_type: str, entity_id: UUID, field_id: Optional[UUID] = None) -> str:
        """Where tapping the notification lands in the web app."""
        paths = {
            "conversation": f"/chat?c={entity_id}", "digest": f"/resumenes?d={entity_id}",
            "report": f"/reportes/{entity_id}", "event": f"/eventos/{entity_id}", "reminder": "/recordatorios",
            "application": f"/aplicaciones/{entity_id}", "market_order": f"/mercado?pedido={entity_id}",
        }
        return f"{self.base_url}{paths.get(entity_type, '/inicio')}"
