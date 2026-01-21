# src/config/container.py
"""
Root dependency injection container for the application.
"""
from dependency_injector import containers, providers

from src.shared.database import get_session_factory
from src.shared.container import SharedContainer
from src.auth.container import AuthLayerContainer
from src.ingestion.container import IngestionContainer
from src.agent.container import AgentContainer
from src.action.container import ActionContainer


class Container(containers.DeclarativeContainer):
    """
    Root container for the application.
    
    Architecture: 3 Layers + Auth
    - Auth: Authentication and user management (separate)
    - Ingestion: Data reception, queues, and managers
    - Agent: Conversational AI, search, and reasoning
    - Action: Reports, storage, alerts, and commands
    
    Configuration is loaded and applied in src/__init__.py
    """
    
    # Configuration - will be populated by from_dict() in src/__init__.py
    config = providers.Configuration()
    
    # Database session factory (shared between containers)
    db_session_factory = providers.Singleton(
        lambda: get_session_factory()
    )

    # ============================================
    # SHARED SERVICES
    # ============================================
    shared = providers.Container(
        SharedContainer,
        db_session_factory=db_session_factory,
    )

    # ============================================
    # AUTH LAYER (Separate)
    # ============================================
    auth = providers.Container(
        AuthLayerContainer,
        config=config.auth,
        db_session_factory=db_session_factory,
        account_service=shared.account_service,
    )
    
    # ============================================
    # INGESTION LAYER
    # ============================================
    ingestion = providers.Container(
        IngestionContainer,
        config=config,
        db_session_factory=db_session_factory,
    )
    
    # ============================================
    # AGENT LAYER
    # ============================================
    agent = providers.Container(
        AgentContainer,
        config=config,
    )
    
    # ============================================
    # ACTION LAYER
    # ============================================
    action = providers.Container(
        ActionContainer,
        config=config,
        db_session_factory=db_session_factory,
        message_queue=ingestion.message_queue,
    )


# Backward compatibility aliases for gradual migration
class LegacyContainer(Container):
    """
    Legacy container with backwards compatibility mappings.
    Provides aliases to old container paths during migration.
    To be removed after full migration is complete.
    """
    pass
