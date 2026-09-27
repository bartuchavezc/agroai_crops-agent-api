from typing import List, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Response, status

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor

from .service import AlertService
from .schemas import Alert, AlertCreate, Severity

router = APIRouter(prefix="/alerts", tags=["Alerts"])

ALERTS = Provide["application.alert_service"]


@router.post("", response_model=Alert, status_code=status.HTTP_201_CREATED, summary="Create Alert")
@inject
async def create_alert(body: AlertCreate, actor: Actor = Depends(get_actor), alerts: AlertService = Depends(ALERTS)):
    return await alerts.create_alert(actor, body, source="user")


@router.get("", response_model=List[Alert], summary="List Alerts")
@inject
async def list_alerts(
    acknowledged: Optional[bool] = None,
    severity: Optional[Severity] = None,
    field_id: Optional[UUID] = None,
    limit: int = 50,
    actor: Actor = Depends(get_actor),
    alerts: AlertService = Depends(ALERTS),
):
    return await alerts.list_alerts(actor, acknowledged=acknowledged, severity=severity, field_id=field_id, limit=limit)


@router.get("/active", response_model=List[Alert], summary="Get Active Alerts")
@inject
async def get_active_alerts(
    field_id: Optional[UUID] = None, actor: Actor = Depends(get_actor), alerts: AlertService = Depends(ALERTS)
):
    return await alerts.get_active_alerts(actor, field_id=field_id)


@router.get("/{alert_id}", response_model=Alert, summary="Get Alert")
@inject
async def get_alert(alert_id: UUID, actor: Actor = Depends(get_actor), alerts: AlertService = Depends(ALERTS)):
    return await alerts.get_alert(actor, alert_id)


@router.put("/{alert_id}/acknowledge", response_model=Alert, summary="Acknowledge Alert")
@inject
async def acknowledge_alert(alert_id: UUID, actor: Actor = Depends(get_actor), alerts: AlertService = Depends(ALERTS)):
    return await alerts.acknowledge_alert(actor, alert_id)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Alert")
@inject
async def delete_alert(alert_id: UUID, actor: Actor = Depends(get_actor), alerts: AlertService = Depends(ALERTS)):
    await alerts.delete_alert(actor, alert_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
