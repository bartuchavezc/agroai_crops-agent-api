from datetime import datetime
from typing import Iterable, Optional, Sequence
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.management.repository import IdFilter, _where_id

from .models import Task


class TaskRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def list(
        self,
        account_id: UUID,
        field_id: IdFilter = None,
        zone_id: Optional[UUID] = None,
        lot_ids: Optional[Iterable[UUID]] = None,
        plan_id: Optional[UUID] = None,
        statuses: Optional[Iterable[str]] = None,
        assigned_to: IdFilter = None,
        done_before: Optional[datetime] = None,
        done_since: Optional[datetime] = None,
        limit: int = 200,
    ) -> Sequence[Task]:
        stmt = select(Task).where(Task.account_id == account_id, Task.deleted_at.is_(None))
        stmt = _where_id(stmt, Task.field_id, field_id)
        stmt = _where_id(stmt, Task.assigned_to, assigned_to)
        if zone_id and lot_ids is not None:  # a zone's tasks include those of the lots growing in it
            stmt = stmt.where(or_(Task.zone_id == zone_id, Task.lot_id.in_(list(lot_ids))))
        elif zone_id:
            stmt = stmt.where(Task.zone_id == zone_id)
        elif lot_ids is not None:
            stmt = stmt.where(Task.lot_id.in_(list(lot_ids)))
        if plan_id:
            stmt = stmt.where(Task.plan_id == plan_id)
        if statuses:
            stmt = stmt.where(Task.status.in_(list(statuses)))
        if done_before:
            stmt = stmt.where(Task.completed_at < done_before)
        if done_since:
            stmt = stmt.where(Task.completed_at >= done_since)
        if done_before or done_since:
            stmt = stmt.order_by(Task.completed_at.desc())
        else:
            stmt = stmt.order_by(Task.due_date.asc().nulls_last(), Task.created_at.desc())
        async with self.session_factory() as session:
            return (await session.execute(stmt.limit(limit))).scalars().all()

    async def get(self, account_id: UUID, task_id: UUID) -> Optional[Task]:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(Task).where(Task.id == task_id, Task.account_id == account_id, Task.deleted_at.is_(None))
                )
            ).scalar_one_or_none()

    async def create(self, task: Task) -> Task:
        async with self.session_factory() as session:
            session.add(task)
            await session.commit()
            await session.refresh(task)
        return task

    async def update(self, account_id: UUID, task_id: UUID, values: dict) -> Optional[Task]:
        async with self.session_factory() as session:
            task = (
                await session.execute(
                    select(Task).where(Task.id == task_id, Task.account_id == account_id, Task.deleted_at.is_(None))
                )
            ).scalar_one_or_none()
            if task is None:
                return None
            for key, value in values.items():
                setattr(task, key, value)
            await session.commit()
            await session.refresh(task)
        return task

    async def delete(self, account_id: UUID, task_id: UUID) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(Task)
                .where(Task.id == task_id, Task.account_id == account_id, Task.deleted_at.is_(None))
                .values(deleted_at=func.now())
            )
            await session.commit()
        return result.rowcount > 0

    async def cancel_open_of_plan(self, account_id: UUID, plan_id: UUID) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(Task)
                .where(
                    Task.account_id == account_id, Task.plan_id == plan_id, Task.deleted_at.is_(None),
                    Task.status.in_(("pendiente", "en_curso", "bloqueada")),
                )
                .values(status="cancelada")
            )
            await session.commit()
