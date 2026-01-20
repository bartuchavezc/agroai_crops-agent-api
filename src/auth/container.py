# src/auth/container.py
"""
Dependency injection container for the Auth layer.
"""
from dependency_injector import containers, providers

from .services.auth_service import AuthService
from .services.user_service import UserService
from .adapters.user_repository import SQLAlchemyUserRepository


class AuthLayerContainer(containers.DeclarativeContainer):
    """Container for authentication-related services."""
    
    # Configuration (will be provided by parent container)
    config = providers.Configuration()
    
    # Database session factory (will be provided by parent container)
    db_session_factory = providers.Dependency()
    
    # Optional account service dependency (for user-account relationship)
    account_service = providers.Dependency(default=None)
    
    # Repositories
    user_repository = providers.Factory(
        SQLAlchemyUserRepository,
        session_factory=db_session_factory
    )
    
    # Services
    user_service = providers.Factory(
        UserService,
        user_repository=user_repository,
        account_service=account_service
    )
    
    auth_service = providers.Factory(
        AuthService,
        config=config,
        user_service=user_service
    )
