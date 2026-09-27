"""
In-app notifications, fan-out to every user of an account (there is no finer-grained membership
than the account today, so "all users of a field" == "all users of the account that owns it").
No push/email — this is DB-backed and polled by the frontend.
"""
import uuid
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.auth.adapters.user_repository import UserRepositoryInterface
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import NotFoundError

from .models import NotificationModel
from .schemas import EntityType, Notification, NotificationType


class NotificationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], user_repository: UserRepositoryInterface):
        self.session_factory = session_factory
        self.users = user_repository

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
    ) -> None:
        members = await self.users.list_by_account(account_id)
        recipients = [m for m in members if m.id != exclude_user_id]
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
                "read_at": None,
                "created_at": now,
            }
            for member in recipients
        ]
        async with self.session_factory() as session:
            await session.execute(NotificationModel.__table__.insert(), rows)
            await session.commit()

    async def list_for_user(
        self, actor: Actor, unread_only: bool = False, limit: int = 50
    ) -> list[Notification]:
        stmt = select(NotificationModel).where(NotificationModel.user_id == actor.user_id)
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
