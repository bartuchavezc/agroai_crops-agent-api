# src/action/api/alerts_router.py
"""
Alerts API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from dependency_injector.wiring import inject, Provide
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

router = APIRouter(prefix="/alerts", tags=["Alerts"])


class AlertCreate(BaseModel):
    """Schema for creating an alert."""
    title: str
    message: str
    severity: str = "medium"  # low, medium, high, critical
    type: str  # weather, pest, disease, nutrient, etc.
    region: Optional[str] = None
    field_id: Optional[str] = None


class Alert(AlertCreate):
    """Schema for alert response."""
    id: str
    created_at: datetime
    acknowledged: bool = False
    acknowledged_at: Optional[datetime] = None


class AlertAcknowledge(BaseModel):
    """Schema for acknowledging an alert."""
    acknowledged: bool = True


@router.post("", response_model=Alert, status_code=status.HTTP_201_CREATED, summary="Create Alert")
@inject
async def create_alert(
    alert_create: AlertCreate,
    alert_service = Depends(Provide["action.alert_service"]),
):
    """
    Create a new alert.
    """
    try:
        return await alert_service.create_alert(alert_create)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("", response_model=List[Alert], summary="List Alerts")
@inject
async def list_alerts(
    acknowledged: Optional[bool] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    alert_service = Depends(Provide["action.alert_service"]),
):
    """
    List alerts with optional filters.
    """
    return await alert_service.list_alerts(
        acknowledged=acknowledged,
        severity=severity,
        limit=limit,
    )


@router.get("/active", response_model=List[Alert], summary="Get Active Alerts")
@inject
async def get_active_alerts(
    alert_service = Depends(Provide["action.alert_service"]),
):
    """
    Get all unacknowledged alerts.
    """
    return await alert_service.get_active_alerts()


@router.get("/{alert_id}", response_model=Alert, summary="Get Alert")
@inject
async def get_alert(
    alert_id: str,
    alert_service = Depends(Provide["action.alert_service"]),
):
    """
    Get a specific alert by ID.
    """
    alert = await alert_service.get_alert(alert_id)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with ID {alert_id} not found"
        )
    return alert


@router.put("/{alert_id}/acknowledge", response_model=Alert, summary="Acknowledge Alert")
@inject
async def acknowledge_alert(
    alert_id: str,
    alert_service = Depends(Provide["action.alert_service"]),
):
    """
    Acknowledge an alert.
    """
    alert = await alert_service.acknowledge_alert(alert_id)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with ID {alert_id} not found"
        )
    return alert
