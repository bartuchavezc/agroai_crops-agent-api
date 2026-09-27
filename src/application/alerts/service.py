"""
Alerts persisted in Postgres, scoped by account. Automatic alerts use a dedupe_key so the
proactive jobs can run repeatedly without creating duplicates.
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import NotFoundError

from .models import AlertModel
from .schemas import Alert, AlertCreate

logger = logging.getLogger(__name__)


class AlertService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def create_alert(self, actor: Actor, data: AlertCreate, source: str = "user") -> Alert:
        model = AlertModel(
            account_id=actor.account_id,
            field_id=data.field_id,
            title=data.title,
            message=data.message,
            severity=data.severity,
            alert_type=data.type,
            recommendations=data.recommendations,
            source=source,
        )
        async with self.session_factory() as session:
            session.add(model)
            await session.commit()
            await session.refresh(model)
        return Alert.from_model(model)

    async def create_system_alert(
        self,
        *,
        account_id: UUID,
        title: str,
        message: str,
        severity: str,
        alert_type: str,
        source: str,
        dedupe_key: str,
        field_id: Optional[UUID] = None,
        rule_id: Optional[str] = None,
        recommendations: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None,
    ) -> bool:
        """Insert unless an alert with the same dedupe_key exists. Returns True if created."""
        stmt = (
            insert(AlertModel.__table__)
            .values(
                id=uuid.uuid4(),
                account_id=account_id,
                field_id=field_id,
                title=title,
                message=message,
                severity=severity,
                type=alert_type,
                rule_id=rule_id,
                recommendations=recommendations or [],
                source=source,
                metadata=metadata or {},
                valid_from=valid_from,
                valid_to=valid_to,
                dedupe_key=dedupe_key,
                created_at=utcnow(),
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
        )
        async with self.session_factory() as session:
            result = await session.execute(stmt)
            await session.commit()
        return result.rowcount > 0

    async def get_alert(self, actor: Actor, alert_id: UUID) -> Alert:
        async with self.session_factory() as session:
            model = (
                await session.execute(
                    select(AlertModel).where(AlertModel.id == alert_id, AlertModel.account_id == actor.account_id)
                )
            ).scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"Alert {alert_id} not found.")
        return Alert.from_model(model)

    async def list_alerts(
        self,
        actor: Actor,
        acknowledged: Optional[bool] = None,
        severity: Optional[str] = None,
        field_id: Optional[UUID] = None,
        include_expired: bool = True,
        limit: int = 50,
    ) -> list[Alert]:
        stmt = select(AlertModel).where(AlertModel.account_id == actor.account_id)
        if acknowledged is True:
            stmt = stmt.where(AlertModel.acknowledged_at.is_not(None))
        elif acknowledged is False:
            stmt = stmt.where(AlertModel.acknowledged_at.is_(None))
        if severity:
            stmt = stmt.where(AlertModel.severity == severity)
        if field_id:
            stmt = stmt.where(AlertModel.field_id == field_id)
        if not include_expired:
            stmt = stmt.where((AlertModel.valid_to.is_(None)) | (AlertModel.valid_to >= utcnow()))
        stmt = stmt.order_by(AlertModel.created_at.desc()).limit(min(max(limit, 1), 500))
        async with self.session_factory() as session:
            return [Alert.from_model(m) for m in (await session.execute(stmt)).scalars().all()]

    async def get_active_alerts(self, actor: Actor, field_id: Optional[UUID] = None) -> list[Alert]:
        return await self.list_alerts(actor, acknowledged=False, field_id=field_id, include_expired=False)

    async def acknowledge_alert(self, actor: Actor, alert_id: UUID) -> Alert:
        async with self.session_factory() as session:
            result = await session.execute(
                update(AlertModel)
                .where(AlertModel.id == alert_id, AlertModel.account_id == actor.account_id)
                .values(acknowledged_at=utcnow(), acknowledged_by=actor.user_id)
            )
            await session.commit()
        if result.rowcount == 0:
            raise NotFoundError(f"Alert {alert_id} not found.")
        return await self.get_alert(actor, alert_id)

    async def delete_alert(self, actor: Actor, alert_id: UUID) -> None:
        async with self.session_factory() as session:
            result = await session.execute(
                delete(AlertModel).where(AlertModel.id == alert_id, AlertModel.account_id == actor.account_id)
            )
            await session.commit()
        if result.rowcount == 0:
            raise NotFoundError(f"Alert {alert_id} not found.")
