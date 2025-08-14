# src/app/storage/container.py
from dependency_injector import containers, providers

from src.app.storage.domain.repositories import FileRepository
from src.app.storage.infrastructure.disk_file_repository import DiskFileRepository
from src.app.storage.service.storage_service import StorageService

class StorageContainer(containers.DeclarativeContainer):
    """
    Container for storage-related dependencies.
    """
    config = providers.Configuration()

    # Repository provider
    # DiskFileRepository is used as the concrete implementation for FileRepository
    file_repository = providers.Singleton(
        DiskFileRepository,
        base_data_path=config.base_data_path
    )

    # Service provider
    storage_service = providers.Factory(
        StorageService,
        file_repository=file_repository
    ) 