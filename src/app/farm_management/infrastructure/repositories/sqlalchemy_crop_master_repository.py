from typing import Optional, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, delete as sqlalchemy_delete, update as sqlalchemy_update

from src.app.farm_management.domain.crop_master_model import CropMasterModel
from src.app.farm_management.domain.schemas.crop_master_schema import CropMasterCreate, CropMasterUpdate
from src.app.farm_management.domain.repositories.crop_master_repository import CropMasterRepositoryInterface

class SQLAlchemyCropMasterRepository(CropMasterRepositoryInterface):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def get_by_id(self, crop_master_id: UUID) -> Optional[CropMasterModel]:
        async with self._session_factory() as session:
            result = await session.execute(select(CropMasterModel).filter(CropMasterModel.id == crop_master_id))
            return result.scalars().first()

    async def get_by_name(self, name: str) -> Optional[CropMasterModel]:
        async with self._session_factory() as session:
            result = await session.execute(select(CropMasterModel).filter(CropMasterModel.name == name))
            return result.scalars().first()

    async def get_all(self, skip: int = 0, limit: int = 100) -> List[CropMasterModel]:
        async with self._session_factory() as session:
            result = await session.execute(select(CropMasterModel).offset(skip).limit(limit))
            return result.scalars().all()

    async def create(self, crop_master_create_dto: CropMasterCreate) -> CropMasterModel:
        # Ensure name is unique if needed by checking get_by_name first in service layer
        db_crop_master = CropMasterModel(**crop_master_create_dto.model_dump())
        async with self._session_factory() as session:
            session.add(db_crop_master)
            await session.commit()
            await session.refresh(db_crop_master)
        return db_crop_master

    async def update(self, crop_master_id: UUID, crop_master_update_dto: CropMasterUpdate) -> Optional[CropMasterModel]:
        async with self._session_factory() as session:
            update_data = crop_master_update_dto.model_dump(exclude_unset=True)
            if not update_data:
                return await self.get_by_id(crop_master_id)

            stmt = (
                sqlalchemy_update(CropMasterModel)
                .where(CropMasterModel.id == crop_master_id)
                .values(**update_data)
                .returning(CropMasterModel)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.scalars().first()
    
    async def delete(self, crop_master_id: UUID) -> bool:
        async with self._session_factory() as session:
            stmt = sqlalchemy_delete(CropMasterModel).where(CropMasterModel.id == crop_master_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0 