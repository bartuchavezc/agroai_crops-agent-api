# src/action/container.py
"""
Dependency injection container for the Action layer.
"""
from dependency_injector import containers, providers

from .reports.report_service import ReportsService
from .reports.report_repository import SQLAlchemyReportsRepository
from .storage.storage_service import StorageService
from .storage.local_adapter import LocalFileRepository
from .alerts.alert_service import AlertService


class ActionContainer(containers.DeclarativeContainer):
    """Container for action-related services."""
    
    # Configuration (will be provided by parent container)
    config = providers.Configuration()
    
    # Database session factory (will be provided by parent container)
    db_session_factory = providers.Dependency()
    
    # Message queue (will be provided from ingestion container)
    message_queue = providers.Dependency(default=None)
    
    # ============================================
    # STORAGE
    # ============================================
    
    file_repository = providers.Singleton(
        LocalFileRepository,
        base_path=config.storage.base_data_path,
    )
    
    storage_service = providers.Factory(
        StorageService,
        file_repository=file_repository,
    )
    
    # ============================================
    # REPORTS
    # ============================================
    
    reports_repository = providers.Factory(
        SQLAlchemyReportsRepository,
        session_factory=db_session_factory,
    )
    
    reports_service = providers.Factory(
        ReportsService,
        reports_repository=reports_repository,
        config=config,
    )
    
    # ============================================
    # ALERTS
    # ============================================
    
    alert_service = providers.Factory(
        AlertService,
        queue=message_queue,
    )
    
    # ============================================
    # ANALYSIS SERVICES (placeholders)
    # These would be moved from legacy or reimplemented
    # ============================================
    
    # segmenter_service = providers.Dependency(default=None)
    # captioner_service = providers.Dependency(default=None)
