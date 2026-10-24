from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Response, status

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.utils.routing import route_with_and_without_slash as _both

from .schemas import (
    AccountProductRead,
    ApplicationCorrection,
    ApplicationCreate,
    ApplicationDraftUpdate,
    ApplicationFollowUpLink,
    ApplicationRead,
    ApplicationStatus,
    ApplicationVoid,
    ProductIntervalRead,
)
from .service import ApplicationService

router = APIRouter(prefix="/applications", tags=["Applications"])

APPLICATIONS = Provide["application.application_service"]


@_both(router.get, "", response_model=List[ApplicationRead], summary="The application records in force")
@inject
async def list_applications(
    field_id: Optional[UUID] = None,
    lot_id: Optional[UUID] = None,
    status_filter: Optional[ApplicationStatus] = Query(None, alias="status"),
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = Query(100, ge=1, le=1000),
    actor: Actor = Depends(get_actor),
    applications: ApplicationService = Depends(APPLICATIONS),
):
    return await applications.list_applications(
        actor, field_id=field_id, lot_id=lot_id, status=status_filter, since=since, until=until, limit=limit
    )


@_both(router.post, "", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED,
       summary="Start an application record (a draft)")
@inject
async def create_application(
    body: ApplicationCreate, actor: Actor = Depends(get_actor),
    applications: ApplicationService = Depends(APPLICATIONS),
):
    return await applications.create_draft(actor, body)


@router.get("/export", summary="The cuaderno de aplicaciones, as PDF or CSV")
@inject
async def export_applications(
    format: Literal["pdf", "csv"] = "pdf",
    field_id: Optional[UUID] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    actor: Actor = Depends(get_actor),
    applications: ApplicationService = Depends(APPLICATIONS),
):
    content, media_type, filename = await applications.export(actor, format, field_id, since, until)
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/products", response_model=List[AccountProductRead], summary="Products of the account not in the registry")
@inject
async def account_products(
    q: Optional[str] = None, actor: Actor = Depends(get_actor),
    applications: ApplicationService = Depends(APPLICATIONS),
):
    return await applications.account_products(actor, q)


@router.get("/intervals", response_model=List[ProductIntervalRead], summary="Withholding periods read on labels")
@inject
async def intervals(
    product: Optional[str] = None, actor: Actor = Depends(get_actor),
    applications: ApplicationService = Depends(APPLICATIONS),
):
    return await applications.intervals(actor, product)


@router.get("/{application_id}", response_model=ApplicationRead, summary="An application record (its version in force)")
@inject
async def get_application(
    application_id: UUID, actor: Actor = Depends(get_actor), applications: ApplicationService = Depends(APPLICATIONS)
):
    return await applications.get(actor, application_id)


@router.get("/{application_id}/history", response_model=List[ApplicationRead], summary="Every version, oldest first")
@inject
async def application_history(
    application_id: UUID, actor: Actor = Depends(get_actor), applications: ApplicationService = Depends(APPLICATIONS)
):
    return await applications.history(actor, application_id)


@router.put("/{application_id}", response_model=ApplicationRead, summary="Edit a draft")
@inject
async def update_draft(
    application_id: UUID, body: ApplicationDraftUpdate, actor: Actor = Depends(get_actor),
    applications: ApplicationService = Depends(APPLICATIONS),
):
    return await applications.update_draft(actor, application_id, body)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a draft")
@inject
async def delete_draft(
    application_id: UUID, actor: Actor = Depends(get_actor), applications: ApplicationService = Depends(APPLICATIONS)
):
    await applications.delete_draft(actor, application_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{application_id}/confirm", response_model=ApplicationRead, summary="Confirm a draft into the record")
@inject
async def confirm_application(
    application_id: UUID, actor: Actor = Depends(get_actor), applications: ApplicationService = Depends(APPLICATIONS)
):
    """Writes its bitácora entry, takes what it used from stock and sets the treated lots' "no cosechar hasta"."""
    return await applications.confirm(actor, application_id)


@router.post("/{application_id}/corrections", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED,
             summary="Correct a confirmed record (a new version with its reason)")
@inject
async def correct_application(
    application_id: UUID, body: ApplicationCorrection, actor: Actor = Depends(get_actor),
    applications: ApplicationService = Depends(APPLICATIONS),
):
    return await applications.correct(actor, application_id, body)


@router.put("/{application_id}/followup", response_model=ApplicationRead,
            summary="Which follow-up (seguimiento) it treats: drafts and confirmed records alike, no new version")
@inject
async def link_application_followup(
    application_id: UUID, body: ApplicationFollowUpLink, actor: Actor = Depends(get_actor),
    applications: ApplicationService = Depends(APPLICATIONS),
):
    return await applications.link_followup(actor, application_id, body.followup_id)


@router.post("/{application_id}/void", response_model=ApplicationRead,
             summary="Void a confirmed record (owner/tecnico)")
@inject
async def void_application(
    application_id: UUID, body: ApplicationVoid, actor: Actor = Depends(get_actor),
    applications: ApplicationService = Depends(APPLICATIONS),
):
    return await applications.void(actor, application_id, body.reason)
