from dependency_injector import containers, providers

from .adapters.account_repository import SQLAlchemyAccountRepository
from .adapters.profile_repository import SQLAlchemyProfileRepository
from .adapters.user_repository import SQLAlchemyUserRepository
from .services.account_service import AccountService
from .services.auth_service import AuthService
from .services.profile_service import ProfileService
from .services.user_service import UserService


class AuthLayerContainer(containers.DeclarativeContainer):
    config = providers.Configuration()
    db_session_factory = providers.Dependency()

    user_repository = providers.Singleton(SQLAlchemyUserRepository, session_factory=db_session_factory)
    account_repository = providers.Singleton(SQLAlchemyAccountRepository, session_factory=db_session_factory)
    profile_repository = providers.Singleton(SQLAlchemyProfileRepository, session_factory=db_session_factory)

    account_service = providers.Singleton(AccountService, account_repository=account_repository)
    user_service = providers.Singleton(UserService, user_repository=user_repository, account_service=account_service)
    auth_service = providers.Singleton(AuthService, config=config, user_service=user_service)
    profile_service = providers.Singleton(
        ProfileService, profile_repository=profile_repository, user_repository=user_repository
    )
