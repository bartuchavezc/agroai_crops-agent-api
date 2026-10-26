"""The assistant's side of the conversation: phones it can reach, what each person wants to be told, the summaries
for whoever is away and the log of what it decided to say (or not)."""
from datetime import date, datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.utils.errors import PermissionDeniedError

from .digests import DigestService
from .models import NudgeLog
from .push import PreferencesRead, PreferencesUpdate, PushService, PushSubscriptionIn

router = APIRouter(tags=["Proactive"])

PUSH = Provide["application.push_service"]
DIGESTS = Provide["application.digest_service"]
NUDGES = Provide["agent.nudge_engine"]


class DigestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[UUID] = None
    field_id: Optional[UUID] = None
    kind: Literal["daily", "weekly"]
    local_date: date
    period_start: datetime
    period_end: datetime
    title: str
    text: str
    data: dict[str, Any]
    created_at: Optional[datetime] = None


class NudgeLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: Optional[UUID] = None
    window: str
    outcome: str
    kind: Optional[str] = None
    message: Optional[str] = None
    reason: Optional[str] = None
    signal_keys: list[str] = []
    signals: list[dict[str, Any]] = []
    conversation_id: Optional[UUID] = None
    created_at: datetime


class PushKey(BaseModel):
    public_key: Optional[str]
    enabled: bool


class Unsubscribe(BaseModel):
    endpoint: str


def _require_manager(actor: Actor) -> None:
    if not actor.is_manager:
        raise PermissionDeniedError("Only owner or tecnico can do this.")


@router.get("/push/public-key", response_model=PushKey, summary="The VAPID key a browser subscribes with")
@inject
async def push_key(push: PushService = Depends(PUSH)):
    return PushKey(public_key=push.public_key or None, enabled=push.enabled)


@router.post("/push/subscriptions", status_code=status.HTTP_201_CREATED, summary="This device accepts notifications")
@inject
async def subscribe(body: PushSubscriptionIn, actor: Actor = Depends(get_actor), push: PushService = Depends(PUSH)):
    return {"devices": await push.subscribe(actor, body)}


@router.post("/push/unsubscribe", status_code=status.HTTP_204_NO_CONTENT, summary="Stop notifying this device")
@inject
async def unsubscribe(body: Unsubscribe, actor: Actor = Depends(get_actor), push: PushService = Depends(PUSH)):
    await push.unsubscribe(actor, body.endpoint)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/notification-preferences", response_model=PreferencesRead, summary="What I want to be told")
@inject
async def preferences(actor: Actor = Depends(get_actor), push: PushService = Depends(PUSH)):
    return await push.preferences(actor)


@router.put("/me/notification-preferences", response_model=PreferencesRead, summary="Change what I want to be told")
@inject
async def update_preferences(
    body: PreferencesUpdate, actor: Actor = Depends(get_actor), push: PushService = Depends(PUSH)
):
    return await push.update_preferences(actor, body)


@router.get("/digests", response_model=List[DigestRead], summary="Daily and weekly summaries, newest first")
@inject
async def list_digests(
    kind: Optional[Literal["daily", "weekly"]] = None, limit: int = Query(14, ge=1, le=100),
    field_id: Optional[UUID] = None, actor: Actor = Depends(get_actor), digests: DigestService = Depends(DIGESTS),
):
    """One per field and day (or week), written by the agent; `data.conversations` says where each person got it."""
    return await digests.list_digests(actor, kind, limit, field_id)


@router.get("/digests/preview", response_model=DigestRead, summary="The summary so far (not saved)")
@inject
async def preview_digest(
    kind: Literal["daily", "weekly"] = "daily", actor: Actor = Depends(get_actor),
    digests: DigestService = Depends(DIGESTS),
):
    """How today (or the week up to today) reads right now for the whole account, in plain text: no model call."""
    return await digests.preview(actor, kind)


@router.get("/digests/{digest_id}", response_model=DigestRead, summary="A summary")
@inject
async def get_digest(digest_id: UUID, actor: Actor = Depends(get_actor), digests: DigestService = Depends(DIGESTS)):
    return await digests.get(actor, digest_id)


@router.get("/nudges/log", response_model=List[NudgeLogRead], summary="What the assistant decided, and why")
@inject
async def nudge_log(
    limit: int = Query(30, ge=1, le=200), actor: Actor = Depends(get_actor), nudges=Depends(NUDGES),
):
    """Every check of the account (owner/tecnico): the signals it saw, what it wrote and to whom, or why it stayed
    quiet."""
    _require_manager(actor)
    async with nudges.session_factory() as session:
        rows = (await session.execute(
            select(NudgeLog).where(NudgeLog.account_id == actor.account_id)
            .order_by(NudgeLog.created_at.desc()).limit(limit)
        )).scalars().all()
    return [NudgeLogRead.model_validate(r) for r in rows]


@router.post("/nudges/check", response_model=List[NudgeLogRead], summary="Ask the assistant to look now")
@inject
async def check_now(actor: Actor = Depends(get_actor), nudges=Depends(NUDGES)):
    """Runs the check for this account right away (owner/tecnico), with the same limits as the scheduled one."""
    _require_manager(actor)
    members = (await nudges.accounts()).get(actor.account_id, [])
    return [NudgeLogRead.model_validate(log) for log in await nudges.run_account(members, "evening")]
