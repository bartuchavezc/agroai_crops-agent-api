from typing import Optional, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, delete as sqlalchemy_delete, update as sqlalchemy_update

from src.app.farm_management.domain.field_model import FieldModel
from src.app.farm_management.domain.schemas.field_schema import FieldCreate, FieldUpdate
from src.app.farm_management.domain.repositories.field_repository import FieldRepositoryInterface

class SQLAlchemyFieldRepository(FieldRepositoryInterface):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def get_by_id(self, field_id: UUID) -> Optional[FieldModel]:
        async with self._session_factory() as session:
            result = await session.execute(select(FieldModel).filter(FieldModel.id == field_id))
            return result.scalars().first()
    
    async def get_by_account_id(self, account_id: UUID) -> List[FieldModel]:
        async with self._session_factory() as session:
            result = await session.execute(select(FieldModel).filter(FieldModel.account_id == account_id))
            return result.scalars().all()

    async def create(self, field_create_dto: FieldCreate) -> FieldModel:
        db_field = FieldModel(**field_create_dto.model_dump())
        async with self._session_factory() as session:
            session.add(db_field)
            await session.commit()
            await session.refresh(db_field)
        return db_field

    async def update(self, field_id: UUID, field_update_dto: FieldUpdate) -> Optional[FieldModel]:
        async with self._session_factory() as session:
            update_data = field_update_dto.model_dump(exclude_unset=True)
            if not update_data:
                return await self.get_by_id(field_id)

            stmt = (
                sqlalchemy_update(FieldModel)
                .where(FieldModel.id == field_id)
                .values(**update_data)
                .returning(FieldModel)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.scalars().first()
    
    async def delete(self, field_id: UUID) -> bool:
        async with self._session_factory() as session:
            stmt = sqlalchemy_delete(FieldModel).where(FieldModel.id == field_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0 