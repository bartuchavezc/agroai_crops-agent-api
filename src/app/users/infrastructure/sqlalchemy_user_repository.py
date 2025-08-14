from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select

from src.app.users.domain.user_model import User as UserModel
from src.app.users.domain.schemas.user_schema import UserCreate
from src.app.users.domain.user_repository import UserRepositoryInterface

class SQLAlchemyUserRepository(UserRepositoryInterface):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def get_by_id(self, user_id: UUID) -> Optional[UserModel]:
        async with self.session_factory() as session:
            result = await session.execute(select(UserModel).filter(UserModel.id == user_id))
            return result.scalars().first()

    async def get_by_email(self, email: str) -> Optional[UserModel]:
        async with self.session_factory() as session:
            result = await session.execute(select(UserModel).filter(UserModel.email == email))
            return result.scalars().first()

    async def create(self, user_create_dto: UserCreate) -> UserModel:
        # Convert DTO to dict and exclude password
        user_data = user_create_dto.model_dump(exclude={'password'})
        
        # Hash the password and add it as password_hash
        user_data['password_hash'] = UserModel.get_password_hash(user_create_dto.password)
        
        # Create the user model
        db_user = UserModel(**user_data)

        async with self.session_factory() as session:
            async with session.begin():
                session.add(db_user)
            await session.commit()
            await session.refresh(db_user)
        return db_user 