"""
In-app notifications, fan-out to every user of an account (there is no finer-grained membership
than the account today, so "all users of a field" == "all users of the account that owns it").
DB-backed (the app lists them) and, when Web Push is configured, also pushed to the recipients' phones.
"""
import logging
import uuid
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.auth.adapters.user_repository import UserRepositoryInterface
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import NotFoundError

from .models import NotificationModel
from .schemas import EntityType, Notification, NotificationType

logger = logging.getLogger(__name__)

# Every bitácora entry notifies the other members in the app; on the phone that would be noise — the daily summary
# carries it. What reaches the phone is what asks for attention.
NOT_PUSHED = ("event",)


class NotificationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], user_repository: UserRepositoryInterface):
        self.session_factory = session_factory
        self.users = user_repository
        self.push = None  # PushService, set by the container once both exist

    def set_push(self, push_service) -> None:
        self.push = push_service

    async def notify_account(
        self,
        *,
        account_id: UUID,
        exclude_user_id: Optional[UUID],
        type: NotificationType,
        title: str,
        message: str,
        entity_type: EntityType,
        entity_id: UUID,
        field_id: Optional[UUID] = None,
        only_user_id: Optional[UUID] = None,
        zone_id: Optional[UUID] = None,
        lot_id: Optional[UUID] = None,
    ) -> None:
        """only_user_id: notify just that member (e.g. a reminder's assignee) instead of everyone."""
        members = await self.users.list_by_account(account_id)
        recipients = [
            m for m in members if m.id != exclude_user_id and (only_user_id is None or m.id == only_user_id)
        ]
        if not recipients:
            return
        now = utcnow()
        rows = [
            {
                "id": uuid.uuid4(),
                "account_id": account_id,
                "user_id": member.id,
                "field_id": field_id,
                "type": type,
                "title": title,
                "message": message,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "zone_id": zone_id,
                "lot_id": lot_id,
                "read_at": None,
                "created_at": now,
            }
            for member in recipients
        ]
        async with self.session_factory() as session:
            await session.execute(NotificationModel.__table__.insert(), rows)
            await session.commit()
        if self.push is not None and self.push.enabled and type not in NOT_PUSHED:
            try:
                await self.push.send(
                    [m.id for m in recipients], title, message, self.push.url_for(entity_type, entity_id, field_id),
                    tag=f"{entity_type}:{entity_id}",
                )
            except Exception:  # noqa: BLE001 - the in-app notification is already there
                logger.exception("Web push failed")

    async def list_for_user(
        self, actor: Actor, unread_only: bool = False, limit: int = 50, type: Optional[str] = None
    ) -> list[Notification]:
        stmt = select(NotificationModel).where(NotificationModel.user_id == actor.user_id)
        if type:
            stmt = stmt.where(NotificationModel.type == type)
        if unread_only:
            stmt = stmt.where(NotificationModel.read_at.is_(None))
        stmt = stmt.order_by(NotificationModel.created_at.desc()).limit(min(max(limit, 1), 200))
        async with self.session_factory() as session:
            return [Notification.from_model(m) for m in (await session.execute(stmt)).scalars().all()]

    async def unread_count(self, actor: Actor) -> int:
        stmt = select(func.count()).select_from(NotificationModel).where(
            NotificationModel.user_id == actor.user_id, NotificationModel.read_at.is_(None)
        )
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalar_one()

    async def mark_read(self, actor: Actor, notification_id: UUID) -> None:
        async with self.session_factory() as session:
            result = await session.execute(
                update(NotificationModel)
                .where(NotificationModel.id == notification_id, NotificationModel.user_id == actor.user_id)
                .values(read_at=utcnow())
            )
            await session.commit()
        if result.rowcount == 0:
            raise NotFoundError(f"Notification {notification_id} not found.")

    async def mark_all_read(self, actor: Actor) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(NotificationModel)
                .where(NotificationModel.user_id == actor.user_id, NotificationModel.read_at.is_(None))
                .values(read_at=utcnow())
            )
            await session.commit()

    async def dismiss(self, actor: Actor, notification_id: UUID) -> None:
        """Done with it: the notification leaves the list (a reminder's notice, once acted on)."""
        async with self.session_factory() as session:
            result = await session.execute(
                delete(NotificationModel).where(
                    NotificationModel.id == notification_id, NotificationModel.user_id == actor.user_id
                )
            )
            await session.commit()
        if result.rowcount == 0:
            raise NotFoundError(f"Notification {notification_id} not found.")

    async def clear(self, actor: Actor, read_only: bool = True) -> int:
        """Empties the list: the ones already read, or all of them."""
        stmt = delete(NotificationModel).where(NotificationModel.user_id == actor.user_id)
        if read_only:
            stmt = stmt.where(NotificationModel.read_at.is_not(None))
        async with self.session_factory() as session:
            result = await session.execute(stmt)
            await session.commit()
        return result.rowcount
