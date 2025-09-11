from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.users.service.user_service import UserService
from src.app.users.domain.user_repository import UserRepositoryInterface
from src.app.users.infrastructure.sqlalchemy_user_repository import SQLAlchemyUserRepository
# UserRepositoryInterface is used by UserService, not directly by container for providers
from src.app.database import get_session_factory

class UserContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    # Use the session factory from the database module
    db_session_factory = providers.Singleton(get_session_factory)

    user_repository = providers.Factory(
        SQLAlchemyUserRepository,
        session_factory=db_session_factory
    )

    user_service = providers.Factory(
        UserService,
        user_repository=user_repository
    ) 