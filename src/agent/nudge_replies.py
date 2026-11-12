"""A one-tap answer to the assistant's message, straight from the notification (or from a chip in the chat): it is
recorded as the person's answer, shows in the conversation, and — when the message asked for a check of a lot's
tracking plan — goes back to that check and sends the lot to be re-planned with it. No model call here: the agent
reads the answer on its next pass."""
import logging
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import update

from src.application.proactive.models import NudgeLog
from src.application.tracking.schemas import ItemChange, PlanRevise
from src.auth.domain.models import User
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import NotFoundError, PermissionDeniedError

logger = logging.getLogger(__name__)


class NudgeReply(BaseModel):
    answer: str = Field(min_length=1, max_length=200)
    token: Optional[str] = Field(default=None, description="From the notification, when there is no session")


class NudgeReplyRead(BaseModel):
    nudge_id: UUID
    answer: str
    channel: Literal["button", "text"]
    responded_at: datetime
    plan_updated: bool = False


class NudgeReplyService:
    def __init__(self, session_factory, push_service, conversation_service, tracking_service, long_task_service):
        self.session_factory = session_factory
        self.push = push_service
        self.conversations = conversation_service
        self.tracking = tracking_service
        self.tasks = long_task_service

    async def reply(self, nudge_id: UUID, data: NudgeReply, actor: Optional[Actor] = None) -> NudgeReplyRead:
        async with self.session_factory() as session:
            log = await session.get(NudgeLog, nudge_id)
            if log is None or log.outcome != "sent" or log.user_id is None:
                raise NotFoundError("Message not found.")
            if actor is not None:
                if actor.user_id != log.user_id:
                    raise NotFoundError("Message not found.")
            elif not self.push.valid_reply_token(nudge_id, data.token):
                raise PermissionDeniedError("Invalid reply token.")
            user = await session.get(User, log.user_id)
        person = actor or Actor.from_user(user)
        answer = data.answer.strip()
        channel = "button" if actor is None or answer in (log.quick_replies or []) else "text"
        now = utcnow()
        if log.responded_at is not None and log.response_text == answer:
            return NudgeReplyRead(nudge_id=nudge_id, answer=answer, channel=channel, responded_at=log.responded_at)
        async with self.session_factory() as session:
            await session.execute(update(NudgeLog).where(NudgeLog.id == nudge_id).values(
                responded_at=now, response_channel="button" if channel == "button" else "text", response_text=answer,
            ))
            await session.commit()
        if log.conversation_id:
            try:
                await self.conversations.post_reply(person, log.conversation_id, answer)
            except Exception:  # noqa: BLE001 - the answer is recorded anyway
                logger.exception(f"Could not show the reply to nudge {nudge_id} in the chat")
        plan_updated = False
        ref = log.plan_ref or {}
        if ref.get("lot_id") and ref.get("item_id"):
            lot_id = UUID(ref["lot_id"])
            try:
                await self.tracking.revise(person, lot_id, PlanRevise(
                    reason=f"Respuesta de la persona: «{answer}»", observation=f"Respondió «{answer}» a: {log.message}",
                    items=[ItemChange(id=ref["item_id"], status="respondido", result=answer)],
                ), by="person")
                await self.tasks.create(person, "replan_lot", "Corregir el plan con una respuesta",
                                        {"lot_ids": [str(lot_id)],
                                         "observation": f"A «{log.message}» respondió «{answer}»"})
                plan_updated = True
            except Exception:  # noqa: BLE001 - a plan that changed meanwhile must not lose the answer
                logger.exception(f"Could not take the reply to nudge {nudge_id} back to the plan")
        return NudgeReplyRead(nudge_id=nudge_id, answer=answer, channel=channel, responded_at=now,
                              plan_updated=plan_updated)
