from dependency_injector import containers, providers
from src.app.auth.service.auth_service import AuthService

class AuthContainer(containers.DeclarativeContainer):
    config = providers.Configuration()
    user_service = providers.Dependency()
    auth_service = providers.Factory(
        AuthService,
        config=config,
        user_service=user_service
    ) 