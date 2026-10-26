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
from .prompts.voice import localize

logger = logging.getLogger(__name__)


class DigestWriting(BaseModel):
    text: str = Field(description="The summary, short lines, without the questions")
    questions: list[str] = Field(default_factory=list, description="Up to 3 concrete questions")


def _name(user: User) -> str:
    return " ".join(p for p in (user.first_name, user.last_name) if p) or user.email


class DigestEngine:
    def __init__(self, gemini, digest_service: DigestService, farm_service, conversation_service, push_service,
                 notification_service):
        self.gemini = gemini
        self.digests = digest_service
        self.farm = farm_service
        self.conversations = conversation_service
        self.push = push_service
        self.notifications = notification_service

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
                system_instruction=localize(DIGEST_INSTRUCTION, owner.country),
                thinking_level="low",
            )
        except CropAnalysisError as e:
            logger.warning(f"The summary of {field_name} goes in plain text: {e.message}")
            return self.digests.render(kind, facts), {**facts, "writer": "template", "writer_reason": e.message}
        questions = [q.strip() for q in writing.questions if q.strip()][:3]
        text = writing.text.strip() + ("\n\n" + "\n".join(questions) if questions else "")
        return text, {**facts, "writer": "agent", "questions": questions}

    async def _deliver(self, members: list[User], digest: Digest, field_id) -> Digest:
        """A new conversation per person with the summary as the agent's message, and the notification opening it."""
        recipients = set(await self.push.digest_recipients(digest.account_id, digest.kind))
        conversations = {}
        first_line = digest.text.splitlines()[0] if digest.text else ""
        for member in members:
            if member.id not in recipients:
                continue
            conversation_id = await self.conversations.post_nudge(
                Actor.from_user(member), None, title=digest.title, text=digest.text, field_id=field_id,
            )
            conversations[str(member.id)] = str(conversation_id)
            await self.notifications.notify_account(
                account_id=digest.account_id, exclude_user_id=None, only_user_id=member.id, type="digest",
                title=digest.title, message=first_line, entity_type="conversation", entity_id=conversation_id,
                field_id=field_id,
            )
        return await self.digests.set_conversations(digest.id, conversations) if conversations else digest
