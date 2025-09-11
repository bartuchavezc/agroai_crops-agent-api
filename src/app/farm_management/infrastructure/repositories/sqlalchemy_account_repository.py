from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, delete as sqlalchemy_delete, update as sqlalchemy_update

from src.app.farm_management.domain.account_model import AccountModel
from src.app.farm_management.domain.schemas.account_schema import AccountCreate, AccountUpdate
from src.app.farm_management.domain.repositories.account_repository import AccountRepositoryInterface

class SQLAlchemyAccountRepository(AccountRepositoryInterface):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def get_by_id(self, account_id: UUID) -> Optional[AccountModel]:
        async with self._session_factory() as session:
            result = await session.execute(select(AccountModel).filter(AccountModel.id == account_id))
            return result.scalars().first()

    async def create(self, account_create_dto: AccountCreate) -> AccountModel:
        db_account = AccountModel(**account_create_dto.model_dump())
        async with self._session_factory() as session:
            session.add(db_account)
            await session.commit()
            await session.refresh(db_account)
        return db_account

    async def update(self, account_id: UUID, account_update_dto: AccountUpdate) -> Optional[AccountModel]:
        async with self._session_factory() as session:
            update_data = account_update_dto.model_dump(exclude_unset=True)
            if not update_data:
                # If there is no data to update, maybe fetch and return the existing or raise error
                return await self.get_by_id(account_id) # Or handle as per specific app logic

            stmt = (
                sqlalchemy_update(AccountModel)
                .where(AccountModel.id == account_id)
                .values(**update_data)
                .returning(AccountModel)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.scalars().first()
    
    async def delete(self, account_id: UUID) -> bool:
        async with self._session_factory() as session:
            stmt = sqlalchemy_delete(AccountModel).where(AccountModel.id == account_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0 