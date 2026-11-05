"""The morning summary of each field, written by the agent.

Plain code gathers the facts of the period (src/application/proactive/digests.py: the bitácora, the analyses, the
weather the field had, the zones nobody reported on or watered); one model call per field, paid with the owner's key,
writes them as a short message with up to three questions. Everyone in the account gets it as a message from the
agent in a new conversation, with a push, so the reply ("sí, se regó a la tarde") continues right there with the full
agent and lands in the bitácora — which is also how someone adds something to the next summary: they tell the agent,
and it logs an observation. Without the owner's key, or when the model fails, the plain-text version goes instead."""
import logging
from dataclasses import replace
from datetime import date
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from src.application.proactive.digests import DigestService
from src.application.proactive.models import Digest
from src.auth.domain.models import User
from src.shared.domain.actor import Actor
from src.shared.utils.account_key import owner_key_user
from src.shared.utils.errors import CropAnalysisError

from .prompts.digests import DIGEST_INSTRUCTION, build_digest_prompt
from .prompts.knowledge import short_style
from .prompts.voice import localize

logger = logging.getLogger(__name__)


class DigestWriting(BaseModel):
    text: str = Field(description="The summary, short lines, without the questions")
    questions: list[str] = Field(default_factory=list, description="Up to 3 concrete questions")


def _name(user: User) -> str:
    return " ".join(p for p in (user.first_name, user.last_name) if p) or user.email


class DigestEngine:
    def __init__(self, gemini, digest_service: DigestService, farm_service, conversation_service, push_service,
                 notification_service, profile_service=None, engagement_service=None, tracking_service=None):
        self.gemini = gemini
        self.digests = digest_service
        self.farm = farm_service
        self.conversations = conversation_service
        self.push = push_service
        self.notifications = notification_service
        self.profiles = profile_service
        self.tracking = tracking_service

    async def run_account(self, members: list[User], kind: str, local_day: date) -> list[Digest]:
        """The summary of `local_day` (or of the week ending on it) for each field of the account, once."""
        owner = next((m for m in members if m.role == "owner"), members[0])
        actor = replace(Actor.from_user(owner), via="system")
        tz = ZoneInfo(owner.timezone) if owner.timezone else ZoneInfo("UTC")
        start, end = self.digests.period(kind, local_day, tz)
        writer: Optional[User] = None
        writer_checked = False
        out = []
        for field in await self.farm.list_fields(actor):
            if await self.digests.existing(owner.account_id, field.id, kind, local_day) is not None:
                continue
            facts = await self.digests.gather(actor, start, end, field=field)
            if not (facts["zones"] or facts["entries"] or facts["analyses"]):
                continue  # nothing growing and nothing done: nothing to tell about this field
            facts["plans"] = await self._plans(actor, field.id, local_day)
            if not writer_checked:
                writer, writer_checked = await owner_key_user(self.gemini, members), True
            text, facts = await self._write(owner, writer, kind, field.name, local_day, members, facts)
            digest = await self.digests.save(actor, field.id, kind, local_day, start, end,
                                             self.digests.title(kind, local_day, field.name), text, facts)
            out.append(await self._deliver(members, digest, field.id))
        return out

    async def _write(self, owner: User, writer: Optional[User], kind: str, field_name: str, local_day: date,
                     members: list[User], facts: dict) -> tuple[str, dict]:
        names = {str(m.id): _name(m) for m in members}
        for o in facts.get("observations", []):
            o["author"] = names.get(o.pop("author_user_id", ""), None)
        if writer is None:
            return self.digests.render(kind, facts), {**facts, "writer": "template",
                                                      "writer_reason": "El owner no cargó su API key de Gemini"}
        period = f"{local_day:%d/%m/%Y}" if kind == "daily" else f"semana al {local_day:%d/%m/%Y}"
        people = [{"id": str(m.id), "name": _name(m), "role": m.role} for m in members]
        try:
            writing: DigestWriting = await self.gemini.generate_structured(
                writer.id,
                contents=build_digest_prompt(kind, field_name, period, people, facts),
                schema=DigestWriting,
                system_instruction=localize(DIGEST_INSTRUCTION, owner.country) + await self._voice(owner),
                thinking_level="low",
            )
        except CropAnalysisError as e:
            logger.warning(f"The summary of {field_name} goes in plain text: {e.message}")
            return self.digests.render(kind, facts), {**facts, "writer": "template", "writer_reason": e.message}
        questions = [q.strip() for q in writing.questions if q.strip()][:3]
        text = writing.text.strip() + ("\n\n" + "\n".join(questions) if questions else "")
        return text, {**facts, "writer": "agent", "questions": questions}

    async def _plans(self, actor: Actor, field_id, local_day: date) -> list[dict]:
        """Where each lot of the field is on the agent's tracking plan, and what comes next."""
        if self.tracking is None:
            return []
        try:
            lots = [lot for lot in await self.farm.list_lots(actor, field_id=field_id)
                    if lot.status not in ("harvested", "failed")]
            plans = await self.tracking.list_plans(actor, [lot.id for lot in lots])
        except Exception:  # noqa: BLE001 - the summary goes without it
            logger.exception("No tracking plans for the summary")
            return []
        labels = {lot.id: lot.label for lot in lots}
        out = []
        for plan in plans:
            stage = next((s for s in plan.content.stages if s.key == plan.content.current_stage), None)
            upcoming = [m for m in plan.content.key_moments if (m.window_start or m.window_end) and
                        (m.window_start or m.window_end) >= local_day][:2]
            due = await self.tracking.due_items(actor, local_day, plans=[plan])
            out.append({
                "lot": labels.get(plan.lot_id), "stage": stage.name if stage else plan.content.current_stage,
                "next_moments": [{"name": m.name, "from": (m.window_start or m.window_end).isoformat()}
                                 for m in upcoming],
                "checks_due": [i.title for _, i in due[:3]],
            })
        return out

    async def _voice(self, owner: User) -> str:
        """The summary goes to the whole team, worded the way the owner's profile asks for."""
        if self.profiles is None:
            return ""
        try:
            context = await self.profiles.get_profile_context(owner.id)
        except Exception:  # noqa: BLE001
            return ""
        return "\n\n## Cómo hablarle a este equipo\n" + short_style(context.calculated_profile if context else None)

    async def _deliver(self, members: list[User], digest: Digest, field_id) -> Digest:
        """A new conversation per person with the summary as the agent's message, and the notification opening it."""
        recipients = set(await self.push.digest_recipients(digest.account_id, digest.kind))
        conversations = {}
        lines = [line for line in digest.text.splitlines() if line.strip()]
        first_line = lines[0] if lines else ""
        chat_text = "\n\n".join(lines)  # one paragraph per line in the chat (markdown joins single breaks)
        for member in members:
            if member.id not in recipients:
                continue
            conversation_id = await self.conversations.post_nudge(
                Actor.from_user(member), None, title=digest.title, text=chat_text, field_id=field_id,
            )
            conversations[str(member.id)] = str(conversation_id)
            await self.notifications.notify_account(
                account_id=digest.account_id, exclude_user_id=None, only_user_id=member.id, type="digest",
                title=digest.title, message=first_line, entity_type="conversation", entity_id=conversation_id,
                field_id=field_id,
            )
        return await self.digests.set_conversations(digest.id, conversations) if conversations else digest
