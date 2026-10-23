"""The proactive loop (`python -m src.batch proactive --every-minutes 15`): every few minutes it checks, per account
and in the account's own time, whether it is time for the rain log, the evening summary, the weekly one or one of the
nudge windows — and runs each at most once. What already ran is read back from the database (digests, nudge log), so
a restart neither repeats nor skips anything."""
import logging
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.application.proactive.models import NudgeLog
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow

logger = logging.getLogger(__name__)

RAIN_EVERY = timedelta(hours=6)
URGENT_EVERY = timedelta(hours=1)


def _clock(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


class ProactiveJob:
    def __init__(self, container):
        self.app = container.application
        self.nudges = container.agent.nudge_engine()
        self.config = container.config.proactive()
        self._last_rain: Optional[datetime] = None

    async def _ran(self, account_id, window: str, since: datetime) -> bool:
        async with self.nudges.session_factory() as session:
            return (await session.execute(
                select(NudgeLog.id).where(NudgeLog.account_id == account_id, NudgeLog.window == window,
                                          NudgeLog.created_at >= since).limit(1)
            )).first() is not None

    async def run(self, now: Optional[datetime] = None) -> dict:
        now = now or utcnow()
        done = {"rain": None, "digests": 0, "nudges": 0}
        if self._last_rain is None or now - self._last_rain >= RAIN_EVERY:
            done["rain"] = await self.app.rain_log_service().run()
            self._last_rain = now

        digests = self.app.digest_service()
        windows = [("morning", _clock(self.config["nudge_windows"][0]))]
        if len(self.config["nudge_windows"]) > 1:
            windows.append(("evening", _clock(self.config["nudge_windows"][1])))
        for account_id, members in (await self.nudges.accounts()).items():
            owner = next((m for m in members if m.role == "owner"), members[0])
            tz = ZoneInfo(owner.timezone) if owner.timezone else ZoneInfo("UTC")
            local = now.astimezone(tz)
            day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
            actor = Actor.from_user(owner)
            try:
                if local.hour >= self.config["daily_digest_hour"]:
                    await digests.build(actor, "daily", local.date())
                    done["digests"] += 1
                    if local.weekday() == self.config["weekly_digest_weekday"]:
                        await digests.build(actor, "weekly", local.date())
                for window, at in windows:
                    # A window runs once a day, from its time until the next window (a late start still runs it).
                    if local.time() >= at and not await self._ran(account_id, window, day_start):
                        done["nudges"] += len(await self.nudges.run_account(members, window, now))
                if not await self._ran(account_id, "urgent", now - URGENT_EVERY):
                    done["nudges"] += len(await self.nudges.run_account(members, "urgent", now))
            except Exception:  # noqa: BLE001 - one account must not stop the rest
                logger.exception(f"Proactive job failed for account {account_id}")
        return done
