"""How a person actually uses the assistant: when they were last around, which messages they answered and how
(text, voice, photo, a notification button), and at what time of day they usually show up.

Nothing here decides anything: these are facts the agent reads before writing to someone, so it can learn that a
person answers voice notes in the morning but never sends photos, or that it is asking too much."""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.shared.domain.base import utcnow

from .models import NudgeLog

WINDOW_DAYS = 14
ANSWER_WINDOW_HOURS = 48

_ACTIVITY_SQL = """
    SELECT m.created_at AS at
      FROM conversation_messages m JOIN conversations c ON c.id = m.conversation_id
     WHERE m.role = 'user' AND c.user_id = :user_id AND m.created_at >= :since
    UNION ALL
    SELECT r.created_at FROM reports r
     WHERE r.created_by = :user_id AND r.image_identifier IS NOT NULL AND r.created_at >= :since
    UNION ALL
    SELECT e.created_at FROM field_events e
     WHERE e.author_user_id = :user_id AND e.source = 'user' AND e.created_at >= :since
"""
_LAST_SQL = f"SELECT max(at) FROM ({_ACTIVITY_SQL.replace('>= :since', '>= :ever')}) a"


@dataclass
class Engagement:
    last_active_at: Optional[datetime] = None
    days_inactive: Optional[int] = None
    active_days: int = 0  # distinct days with activity in the window
    sent: int = 0
    answered: int = 0
    asks_sent: int = 0
    asks_answered: int = 0
    asks_this_week: int = 0
    channels: dict[str, int] = field(default_factory=dict)
    usual_hours: list[int] = field(default_factory=list)  # local hours they show up most

    def line(self) -> str:
        """One line for a prompt."""
        parts = []
        if self.days_inactive is None:
            parts.append("todavía no usó la app")
        elif self.days_inactive == 0:
            parts.append("activo hoy")
        else:
            parts.append(f"sin entrar hace {self.days_inactive} días")
        parts.append(f"{self.active_days} días activos en {WINDOW_DAYS}")
        if self.sent:
            parts.append(f"respondió {self.answered} de {self.sent} mensajes tuyos")
        if self.asks_sent:
            parts.append(f"{self.asks_answered} de {self.asks_sent} pedidos de datos")
        if self.channels:
            parts.append("responde por " + ", ".join(f"{k} ({v})" for k, v in
                                                     sorted(self.channels.items(), key=lambda kv: -kv[1])))
        if self.usual_hours:
            parts.append("suele aparecer a las " + ", ".join(f"{h}h" for h in self.usual_hours))
        return "; ".join(parts)


class EngagementService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def summary(self, user_id: UUID, timezone: Optional[str] = None,
                      now: Optional[datetime] = None) -> Engagement:
        now = now or utcnow()
        tz = ZoneInfo(timezone) if timezone else ZoneInfo("UTC")
        since = now - timedelta(days=WINDOW_DAYS)
        week_start = now.astimezone(tz) - timedelta(days=now.astimezone(tz).weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.session_factory() as session:
            moments = [r[0] for r in (await session.execute(
                text(_ACTIVITY_SQL), {"user_id": user_id, "since": since}
            )).all()]
            last = (await session.execute(
                text(_LAST_SQL), {"user_id": user_id, "ever": now - timedelta(days=365)}
            )).scalar_one_or_none()
            logs = list((await session.execute(
                select(NudgeLog).where(NudgeLog.user_id == user_id, NudgeLog.outcome == "sent",
                                       NudgeLog.created_at >= min(since, week_start))
            )).scalars())
        out = Engagement(last_active_at=last)
        if last is not None:
            out.days_inactive = (now.astimezone(tz).date() - last.astimezone(tz).date()).days
        local = [m.astimezone(tz) for m in moments]
        out.active_days = len({m.date() for m in local})
        hours = Counter(m.hour for m in local)
        out.usual_hours = sorted(h for h, _ in hours.most_common(2))
        recent = [log for log in logs if log.created_at >= since]
        out.sent = len(recent)
        out.answered = sum(1 for log in recent if log.responded_at)
        out.asks_sent = sum(1 for log in recent if log.kind == "ask")
        out.asks_answered = sum(1 for log in recent if log.kind == "ask" and log.responded_at)
        out.asks_this_week = sum(1 for log in logs if log.kind == "ask" and log.created_at >= week_start)
        out.channels = dict(Counter(log.response_channel for log in recent if log.response_channel))
        return out

    async def mark_responded(self, user_id: UUID, conversation_id: UUID, channel: str,
                             answer: Optional[str] = None, now: Optional[datetime] = None) -> Optional[UUID]:
        """The person wrote in a conversation the assistant opened: the latest unanswered message of the last two
        days there counts as answered. Returns the nudge it marked."""
        now = now or utcnow()
        async with self.session_factory() as session:
            log = (await session.execute(
                select(NudgeLog).where(
                    NudgeLog.conversation_id == conversation_id, NudgeLog.user_id == user_id,
                    NudgeLog.outcome == "sent", NudgeLog.responded_at.is_(None),
                    NudgeLog.created_at >= now - timedelta(hours=ANSWER_WINDOW_HOURS),
                ).order_by(NudgeLog.created_at.desc()).limit(1)
            )).scalar_one_or_none()
            if log is None:
                return None
            await session.execute(update(NudgeLog).where(NudgeLog.id == log.id).values(
                responded_at=now, response_channel=channel, response_text=(answer or "")[:2000] or None,
            ))
            await session.commit()
            return log.id
