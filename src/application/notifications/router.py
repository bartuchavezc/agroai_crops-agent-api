from typing import List, Optional

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Response, status
from uuid import UUID

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor

from .schemas import Notification, NotificationType, UnreadCount
from .service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])

NOTIFICATIONS = Provide["application.notification_service"]


@router.get("", response_model=List[Notification], summary="List Notifications")
@inject
async def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    type: Optional[NotificationType] = None,
    actor: Actor = Depends(get_actor),
    notifications: NotificationService = Depends(NOTIFICATIONS),
):
    return await notifications.list_for_user(actor, unread_only=unread_only, limit=limit, type=type)


@router.get("/unread-count", response_model=UnreadCount, summary="Unread Notification Count")
@inject
async def unread_count(
    actor: Actor = Depends(get_actor), notifications: NotificationService = Depends(NOTIFICATIONS)
):
    return UnreadCount(count=await notifications.unread_count(actor))


@router.put("/read-all", status_code=status.HTTP_204_NO_CONTENT, summary="Mark All Notifications Read")
@inject
async def mark_all_read(
    actor: Actor = Depends(get_actor), notifications: NotificationService = Depends(NOTIFICATIONS)
):
    await notifications.mark_all_read(actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/clear", summary="Clear the list (read ones, or all)")
@inject
async def clear(
    read_only: bool = True, actor: Actor = Depends(get_actor),
    notifications: NotificationService = Depends(NOTIFICATIONS),
):
    return {"cleared": await notifications.clear(actor, read_only=read_only)}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Dismiss a notification")
@inject
async def dismiss(
    notification_id: UUID, actor: Actor = Depends(get_actor),
    notifications: NotificationService = Depends(NOTIFICATIONS),
):
    await notifications.dismiss(actor, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, summary="Mark Notification Read")
@inject
async def mark_read(
    notification_id: UUID,
    actor: Actor = Depends(get_actor),
    notifications: NotificationService = Depends(NOTIFICATIONS),
):
    await notifications.mark_read(actor, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
