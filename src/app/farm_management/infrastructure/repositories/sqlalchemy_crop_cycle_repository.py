from typing import Optional, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, delete as sqlalchemy_delete, update as sqlalchemy_update

from src.app.farm_management.domain.crop_cycle_model import CropCycleModel
from src.app.farm_management.domain.schemas.crop_cycle_schema import CropCycleCreate, CropCycleUpdate
from src.app.farm_management.domain.repositories.crop_cycle_repository import CropCycleRepositoryInterface

class SQLAlchemyCropCycleRepository(CropCycleRepositoryInterface):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def get_by_id(self, crop_cycle_id: UUID) -> Optional[CropCycleModel]:
        async with self._session_factory() as session:
            result = await session.execute(select(CropCycleModel).filter(CropCycleModel.id == crop_cycle_id))
            return result.scalars().first()

    async def get_by_field_id(self, field_id: UUID, active_only: bool = False) -> List[CropCycleModel]:
        async with self._session_factory() as session:
            stmt = select(CropCycleModel).filter(CropCycleModel.field_id == field_id)
            if active_only:
                stmt = stmt.filter(CropCycleModel.end_date == None) # Assuming active cycles have no end_date
            result = await session.execute(stmt.order_by(CropCycleModel.start_date.desc()))
            return result.scalars().all()

    async def get_by_crop_master_id(self, crop_master_id: UUID) -> List[CropCycleModel]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(CropCycleModel)
                .filter(CropCycleModel.crop_master_id == crop_master_id)
                .order_by(CropCycleModel.start_date.desc())
            )
            return result.scalars().all()

    async def get_all(self, active_only: bool = False) -> List[CropCycleModel]:
        """
        Retrieve all crop cycles from the database.
        
        Args:
            active_only (bool): If True, only return active crop cycles (not completed or cancelled)
            
        Returns:
            List[CropCycleModel]: List of all crop cycles
        """
        async with self._session_factory() as session:
            stmt = select(CropCycleModel)
            if active_only:
                stmt = stmt.filter(CropCycleModel.end_date == None)  # Assuming active cycles have no end_date
            result = await session.execute(stmt.order_by(CropCycleModel.start_date.desc()))
            return result.scalars().all()

    async def create(self, crop_cycle_create_dto: CropCycleCreate) -> CropCycleModel:
        db_crop_cycle = CropCycleModel(**crop_cycle_create_dto.model_dump())
        async with self._session_factory() as session:
            session.add(db_crop_cycle)
            await session.commit()
            await session.refresh(db_crop_cycle)
        return db_crop_cycle

    async def update(self, crop_cycle_id: UUID, crop_cycle_update_dto: CropCycleUpdate) -> Optional[CropCycleModel]:
        async with self._session_factory() as session:
            update_data = crop_cycle_update_dto.model_dump(exclude_unset=True)
            if not update_data:
                return await self.get_by_id(crop_cycle_id)

            stmt = (
                sqlalchemy_update(CropCycleModel)
                .where(CropCycleModel.id == crop_cycle_id)
                .values(**update_data)
                .returning(CropCycleModel)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.scalars().first()
    
    async def delete(self, crop_cycle_id: UUID) -> bool:
        async with self._session_factory() as session:
            stmt = sqlalchemy_delete(CropCycleModel).where(CropCycleModel.id == crop_cycle_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0 