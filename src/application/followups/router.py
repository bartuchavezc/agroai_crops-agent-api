from typing import List, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor

from .schemas import FollowUpClose, FollowUpCreate, FollowUpDetail, FollowUpRead, FollowUpStatus, FollowUpUpdate
from .service import FollowUpService

router = APIRouter(prefix="/farm-management", tags=["Follow-ups"])

FOLLOWUPS = Provide["application.followup_service"]


@router.get("/followups", response_model=List[FollowUpRead], summary="Problems being watched (seguimientos)")
@inject
async def list_followups(
    field_id: Optional[UUID] = None,
    zone_id: Optional[UUID] = None,
    status: Optional[FollowUpStatus] = None,
    actor: Actor = Depends(get_actor),
    followups: FollowUpService = Depends(FOLLOWUPS),
):
    return await followups.list_followups(actor, field_id=field_id, zone_id=zone_id, status=status)


@router.post(
    "/followups", response_model=FollowUpDetail, status_code=status.HTTP_201_CREATED,
    summary="Open a follow-up (writes its first bitácora entry)",
)
@inject
async def create_followup(
    body: FollowUpCreate, actor: Actor = Depends(get_actor), followups: FollowUpService = Depends(FOLLOWUPS)
):
    return await followups.create(actor, body)


@router.get("/followups/{followup_id}", response_model=FollowUpDetail, summary="A follow-up and its timeline")
@inject
async def get_followup(
    followup_id: UUID, actor: Actor = Depends(get_actor), followups: FollowUpService = Depends(FOLLOWUPS)
):
    return await followups.get(actor, followup_id)


@router.patch("/followups/{followup_id}", response_model=FollowUpDetail, summary="Edit a follow-up")
@inject
async def update_followup(
    followup_id: UUID, body: FollowUpUpdate, actor: Actor = Depends(get_actor),
    followups: FollowUpService = Depends(FOLLOWUPS),
):
    return await followups.update(actor, followup_id, body)


@router.post(
    "/followups/{followup_id}/close", response_model=FollowUpDetail,
    summary="Close a follow-up: resolved or dismissed (writes its closing bitácora entry)",
)
@inject
async def close_followup(
    followup_id: UUID, body: FollowUpClose, actor: Actor = Depends(get_actor),
    followups: FollowUpService = Depends(FOLLOWUPS),
):
    return await followups.close(actor, followup_id, body)
