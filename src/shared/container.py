# src/shared/container.py
"""
Dependency injection container for shared services.
"""
from dependency_injector import containers, providers

from .services.account_service import AccountService
from src.auth.adapters.account_repository import SQLAlchemyAccountRepository


class SharedContainer(containers.DeclarativeContainer):
    """Container for shared services."""
    
    # Database session factory (will be provided by parent container)
    db_session_factory = providers.Dependency()
    
    # Account repository
    account_repository = providers.Factory(
        SQLAlchemyAccountRepository,
        session_factory=db_session_factory
    )
    
    # Account service
    account_service = providers.Singleton(
        AccountService,
        account_repository=account_repository
    )
